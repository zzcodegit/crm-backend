#!/usr/bin/env python3
"""Download migration media and normalize /uploads URLs in DB (relative paths)."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

import psycopg2

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DIR = BACKEND_DIR / "export" / "migration_2026-06-07"
UPLOADS_DIR = BACKEND_DIR / "uploads"

HOSTS = ("155.212.143.145", "79.137.221.142")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    p.add_argument("--database-url", default="postgresql://postgres:postgres@localhost:5432/crm")
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--skip-db", action="store_true")
    return p.parse_args()


def collect_urls(migration_dir: Path) -> list[str]:
    urls: set[str] = set()
    for name in ("chat_media_urls.json", "report_media_urls.json"):
        path = migration_dir / name
        if path.exists():
            urls.update(json.loads(path.read_text(encoding="utf-8")))
    return sorted(urls)


def download_files(urls: list[str]) -> tuple[int, int]:
    UPLOADS_DIR.mkdir(exist_ok=True)
    ok = skip = 0
    for url in urls:
        name = url.rsplit("/uploads/", 1)[-1]
        dest = UPLOADS_DIR / name
        if dest.exists() and dest.stat().st_size > 0:
            skip += 1
            continue
        urllib.request.urlretrieve(url, dest)
        ok += 1
        print(f"  downloaded {name}")
    return ok, skip


def normalize_db_urls(database_url: str) -> None:
    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            for host in HOSTS:
                pattern = rf"^https?://{re.escape(host)}"
                cur.execute(
                    f"UPDATE chat_message_attachments SET url = regexp_replace(url, %s, '') "
                    f"WHERE url ~ %s",
                    [pattern, pattern],
                )
                print(f"  chat_message_attachments ({host}): {cur.rowcount}")
                for col in ("z_report_urls", "card_reconciliation_urls"):
                    cur.execute(
                        f"UPDATE daily_reports SET {col} = "
                        f"replace({col}::text, %s, '')::jsonb "
                        f"WHERE {col}::text LIKE %s",
                        [f"http://{host}", f"%{host}%"],
                    )
                    print(f"  daily_reports.{col} ({host}): {cur.rowcount}")
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    args = parse_args()
    urls = collect_urls(args.dir.resolve())
    print(f"Media URLs in manifest: {len(urls)}")

    if not args.skip_download:
        print("Downloading missing files...")
        ok, skip = download_files(urls)
        print(f"Downloaded: {ok}, already present: {skip}")

    if not args.skip_db:
        print("Normalizing DB URLs to /uploads/...")
        normalize_db_urls(args.database_url)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
