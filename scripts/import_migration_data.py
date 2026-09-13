#!/usr/bin/env python3
"""Import migration SQL into CRM PostgreSQL with idempotent conflict handling."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2 import sql

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DIR = BACKEND_DIR / "export" / "migration_2026-06-07"

TABLE_CONFLICT = {
    "daily_reports": "id",
    "order_1c_exchange_logs": "id",
    "manual_employee_debts": "id",
    "chat_messages": "id",
    "chat_message_attachments": "id",
}

# Refresh existing rows on conflict (export snapshot is authoritative).
UPSERT_TABLES = {"daily_reports", "chat_messages"}

IMPORT_FILES = [
    "reports.sql",
    "order_1c_exchange_logs_bonus_all.sql",
    "order_1c_exchange_logs_today.sql",
    "manual_employee_debts.sql",
    "chat_messages.sql",
    "chat_message_attachments.sql",
]

SEQUENCES = [
    ("daily_reports_id_seq", "daily_reports"),
    ("order_1c_exchange_logs_id_seq", "order_1c_exchange_logs"),
    ("manual_employee_debts_id_seq", "manual_employee_debts"),
    ("chat_messages_id_seq", "chat_messages"),
    ("chat_message_attachments_id_seq", "chat_message_attachments"),
]

INSERT_START_RE = re.compile(r"^INSERT INTO (\w+)", re.IGNORECASE)
INSERT_PARTS_RE = re.compile(
    r"^INSERT INTO (\w+) \((.+?)\) VALUES \((.*)\)\s*;?\s*$",
    re.DOTALL | re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument(
        "--database-url",
        default="postgresql://postgres:postgres@localhost:5432/crm",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=BACKEND_DIR / "export" / "backups",
    )
    parser.add_argument("--skip-backup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def backup_database(database_url: str, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = backup_dir / f"crm_pre_migration_{stamp}.sql.gz"
    print(f"Creating backup: {out}")
    with out.open("wb") as fh:
        subprocess.run(
            ["pg_dump", database_url, "--no-owner", "--no-acl"],
            check=True,
            stdout=fh,
        )
    return out


def split_insert_statements(text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if INSERT_START_RE.match(line) and current:
            statements.append("\n".join(current))
            current = [line]
        elif INSERT_START_RE.match(line) or current:
            current.append(line)
            if line.rstrip().endswith(");"):
                statements.append("\n".join(current))
                current = []
    if current:
        statements.append("\n".join(current))
    return [s.strip() for s in statements if s.strip().startswith("INSERT INTO")]


def load_table_columns(conn) -> dict[str, set[str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = ANY(%s)
            """,
            [list(TABLE_CONFLICT.keys())],
        )
        cols: dict[str, set[str]] = {t: set() for t in TABLE_CONFLICT}
        for table, column in cur.fetchall():
            cols[table].add(column)
        return cols


def filter_statement_columns(statement: str, allowed_cols: set[str]) -> str | None:
    match = INSERT_PARTS_RE.match(statement.strip())
    if not match:
        return None
    table, columns_raw, values_raw = match.group(1), match.group(2), match.group(3)
    columns = [c.strip() for c in columns_raw.split(",")]
    values = split_sql_values(values_raw)
    if len(columns) != len(values):
        return None

    kept_cols: list[str] = []
    kept_vals: list[str] = []
    for col, val in zip(columns, values):
        if col in allowed_cols:
            kept_cols.append(col)
            kept_vals.append(val)
    if not kept_cols:
        return None
    return f"INSERT INTO {table} ({', '.join(kept_cols)}) VALUES ({', '.join(kept_vals)});"


def wrap_on_conflict(statement: str) -> str | None:
    match = INSERT_PARTS_RE.match(statement.strip())
    if not match:
        match_start = INSERT_START_RE.match(statement)
        if not match_start:
            return None
        table = match_start.group(1)
        conflict_col = TABLE_CONFLICT.get(table)
        if not conflict_col:
            return None
        body = statement.rstrip().removesuffix(";").rstrip()
        return f"{body} ON CONFLICT ({conflict_col}) DO NOTHING;"

    table, columns_raw, _values_raw = match.group(1), match.group(2), match.group(3)
    conflict_col = TABLE_CONFLICT.get(table)
    if not conflict_col:
        return None
    body = statement.rstrip().removesuffix(";").rstrip()

    if table in UPSERT_TABLES:
        columns = [c.strip() for c in columns_raw.split(",")]
        updates = [
            f"{col} = EXCLUDED.{col}"
            for col in columns
            if col != conflict_col
        ]
        if not updates:
            return f"{body} ON CONFLICT ({conflict_col}) DO NOTHING;"
        return (
            f"{body} ON CONFLICT ({conflict_col}) DO UPDATE SET "
            f"{', '.join(updates)};"
        )

    return f"{body} ON CONFLICT ({conflict_col}) DO NOTHING;"


def nullify_missing_order_id(statement: str, existing_orders: set[int]) -> str:
    if not statement.startswith("INSERT INTO order_1c_exchange_logs"):
        return statement
    # order_id is 12th value; find it via column list position
    cols_match = re.search(r"INSERT INTO order_1c_exchange_logs \((.+?)\) VALUES", statement, re.DOTALL)
    if not cols_match:
        return statement
    columns = [c.strip() for c in cols_match.group(1).split(",")]
    try:
        idx = columns.index("order_id")
    except ValueError:
        return statement

    values_match = re.search(r"VALUES \((.*)\)\s*;?\s*$", statement, re.DOTALL)
    if not values_match:
        return statement
    parts = split_sql_values(values_match.group(1))
    if idx >= len(parts):
        return statement

    raw = parts[idx].strip()
    if raw.upper() == "NULL":
        return statement
    try:
        order_id = int(raw)
    except ValueError:
        return statement
    if order_id in existing_orders:
        return statement

    parts[idx] = "NULL"
    new_values = ", ".join(parts)
    return re.sub(
        r"VALUES \(.*\)\s*;?\s*$",
        f"VALUES ({new_values});",
        statement,
        count=1,
        flags=re.DOTALL,
    )


def split_sql_values(values: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False
    i = 0
    while i < len(values):
        ch = values[i]
        if in_string:
            current.append(ch)
            if ch == "'":
                if i + 1 < len(values) and values[i + 1] == "'":
                    current.append(values[i + 1])
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if ch == "'":
            in_string = True
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        parts.append("".join(current).strip())
    return parts


def import_sql_file(
    conn,
    path: Path,
    existing_orders: set[int],
    table_columns: dict[str, set[str]],
    dry_run: bool,
) -> dict[str, int]:
    stats = {"parsed": 0, "inserted": 0, "skipped": 0, "errors": 0}
    statements = split_insert_statements(path.read_text(encoding="utf-8"))

    with conn.cursor() as cur:
        for raw in statements:
            table_match = INSERT_START_RE.match(raw)
            table = table_match.group(1) if table_match else ""
            allowed = table_columns.get(table, set())

            stmt = nullify_missing_order_id(raw, existing_orders)
            stmt = filter_statement_columns(stmt, allowed) or stmt
            query = wrap_on_conflict(stmt)
            if not query:
                stats["errors"] += 1
                continue
            stats["parsed"] += 1
            if dry_run:
                continue
            try:
                cur.execute(query)
                if cur.rowcount:
                    stats["inserted"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as exc:
                conn.rollback()
                stats["errors"] += 1
                preview = query[:120].replace("\n", " ")
                print(f"  ERROR in {path.name}: {exc} | {preview}...", file=sys.stderr)

        if not dry_run:
            conn.commit()

    return stats


def reset_sequences(conn) -> None:
    with conn.cursor() as cur:
        for seq, table in SEQUENCES:
            cur.execute(
                sql.SQL("SELECT setval({seq}, COALESCE((SELECT MAX(id) FROM {tbl}), 1))").format(
                    seq=sql.Literal(seq),
                    tbl=sql.Identifier(table),
                )
            )
            cur.execute(sql.SQL("SELECT last_value FROM {}").format(sql.Identifier(seq)))
            print(f"  {seq} -> {cur.fetchone()[0]}")
        conn.commit()


def main() -> int:
    args = parse_args()
    migration_dir = args.dir.resolve()
    if not migration_dir.is_dir():
        print(f"Migration dir not found: {migration_dir}", file=sys.stderr)
        return 1

    if not args.skip_backup and not args.dry_run:
        backup_database(args.database_url, args.backup_dir)

    conn = psycopg2.connect(args.database_url)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM orders")
            existing_orders = {row[0] for row in cur.fetchall()}
        table_columns = load_table_columns(conn)
        print(f"Known orders: {len(existing_orders)}")

        all_stats: list[tuple[str, dict[str, int]]] = []
        for filename in IMPORT_FILES:
            path = migration_dir / filename
            if not path.exists():
                print(f"SKIP missing file: {filename}")
                continue
            print(f"\nImporting {filename} ...")
            stats = import_sql_file(conn, path, existing_orders, table_columns, args.dry_run)
            all_stats.append((filename, stats))
            print(
                f"  parsed={stats['parsed']} inserted={stats['inserted']} "
                f"skipped={stats['skipped']} errors={stats['errors']}"
            )

        if not args.dry_run:
            print("\nResetting sequences:")
            reset_sequences(conn)

        print("\n=== Import summary ===")
        for name, stats in all_stats:
            print(
                f"{name}: parsed={stats['parsed']} inserted={stats['inserted']} "
                f"skipped={stats['skipped']} errors={stats['errors']}"
            )
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
