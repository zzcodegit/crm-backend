import os
import re
import sys
from collections import defaultdict

from sqlalchemy.orm import Session

# When run as: python3 /.../scripts/<script>.py
# Python's sys.path may not include the crm-backend root, so adjust it.
BACKEND_ROOT = os.path.dirname(os.path.dirname(__file__))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from database import SessionLocal
from models import Manufacturer, PricelistGroup, PricelistItem


HEADING_SUFFIX_GROUP = "- группа"
HEADING_SUFFIX_GROUP_PLURAL = "- групппа"


def _parse_input_text(text: str) -> dict[str, set[str]]:
    """
    Parse structure like:
      <Group name> - группа
      <Item line 1>
      <Item line 2>
      ...
    Returns: { group_name: { item_name, ... } }
    """
    out: dict[str, set[str]] = defaultdict(set)
    current_group: str | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        if HEADING_SUFFIX_GROUP in line:
            current_group = line.split(HEADING_SUFFIX_GROUP, 1)[0].strip()
            continue
        if HEADING_SUFFIX_GROUP_PLURAL in line:
            current_group = line.split(HEADING_SUFFIX_GROUP_PLURAL, 1)[0].strip()
            continue

        if current_group is None:
            continue

        # Keep original as lens_name; CRM should store exactly what user wrote.
        out[current_group].add(line)

    return out


def _normalize_token(tok: str) -> str:
    tok = tok.strip()
    tok = re.sub(r"^[^0-9A-Za-zА-Яа-я]+", "", tok)
    tok = re.sub(r"[^0-9A-Za-zА-Яа-я]+$", "", tok)
    return tok


def _pick_manufacturer_token(lens_name: str) -> str | None:
    tokens = re.split(r"\s+", lens_name.strip())
    tokens = [t for t in tokens if t]

    # Prefer tokens containing Latin letters (brands are often written in Latin).
    for tok in tokens[:8]:
        if re.search(r"[A-Za-z]", tok) and len(tok) >= 2:
            tok = _normalize_token(tok)
            if tok:
                return tok

    # Fallback: prefer short-ish all-caps tokens (acronyms).
    for tok in tokens[:8]:
        tok = _normalize_token(tok)
        if not tok:
            continue
        if len(tok) >= 2 and len(tok) <= 12 and tok.upper() == tok:
            return tok

    return None


def _canonical_manufacturer_name(tok: str) -> str:
    tok = _normalize_token(tok)
    if not tok:
        return "Generic"
    if tok.isupper() or any(ch.isdigit() for ch in tok):
        return tok
    # e.g. "Zeiss" / "Hoya"
    return tok[:1].upper() + tok[1:].lower()


def _get_or_create_manufacturer(db: Session, manufacturers_by_lower: dict[str, int], lens_name: str) -> int:
    tok = _pick_manufacturer_token(lens_name)
    canonical = _canonical_manufacturer_name(tok) if tok else "Generic"
    key = canonical.strip().lower()

    existing_id = manufacturers_by_lower.get(key)
    if existing_id is not None:
        return existing_id

    # Case-insensitive lookup to avoid duplicates if "Zeiss" vs "ZEISS".
    existing = db.query(Manufacturer).filter(Manufacturer.name.ilike(canonical)).first()
    if existing:
        manufacturers_by_lower[key] = existing.id
        return existing.id

    obj = Manufacturer(name=canonical)
    db.add(obj)
    db.flush()
    manufacturers_by_lower[key] = obj.id
    return obj.id


def _get_or_create_group(db: Session, groups_by_name: dict[str, int], group_name: str, sort_index: int) -> int:
    existing_id = groups_by_name.get(group_name)
    if existing_id is not None:
        return existing_id

    obj = PricelistGroup(name=group_name, sort_index=sort_index)
    db.add(obj)
    db.flush()
    groups_by_name[group_name] = obj.id
    return obj.id


def main() -> None:
    if sys.stdin.isatty():
        print("Provide input text via stdin. Example: cat file.txt | python ...", file=sys.stderr)
        sys.exit(2)

    raw_text = sys.stdin.read()
    groups_to_items = _parse_input_text(raw_text)
    if not groups_to_items:
        print("No groups/items parsed from stdin.", file=sys.stderr)
        sys.exit(1)

    price = 1.0
    if "--price" in sys.argv:
        idx = sys.argv.index("--price")
        try:
            price = float(sys.argv[idx + 1])
        except Exception:
            print("Invalid --price value", file=sys.stderr)
            sys.exit(2)

    db = SessionLocal()
    try:
        manufacturers_by_lower: dict[str, int] = {
            m.name.strip().lower(): m.id for m in db.query(Manufacturer).all()
        }
        groups_by_name: dict[str, int] = {
            g.name.strip(): g.id for g in db.query(PricelistGroup).all()
        }

        # Ensure groups exist first.
        group_names_sorted = sorted(groups_to_items.keys())
        for i, gn in enumerate(group_names_sorted):
            _get_or_create_group(db, groups_by_name, gn, sort_index=500 + i)

        # Preload existing lens_names per group to avoid obvious duplicates.
        # (Do it group-by-group to keep SQL manageable.)
        existing_by_group: dict[str, set[str]] = {}
        for gn in group_names_sorted:
            names = groups_to_items[gn]
            if not names:
                existing_by_group[gn] = set()
                continue
            rows = (
                db.query(PricelistItem.lens_name)
                .filter(PricelistItem.group == gn, PricelistItem.lens_name.in_(list(names)))
                .all()
            )
            existing_by_group[gn] = {r[0] for r in rows}

        created = 0
        skipped_existing = 0
        created_manufacturers = 0

        # Track manufacturers created in this run by snapshotting ids map size.
        initial_mfr_count = len(manufacturers_by_lower)

        for gn in group_names_sorted:
            existing_names = existing_by_group.get(gn, set())
            for lens_name in sorted(groups_to_items[gn]):
                if lens_name in existing_names:
                    skipped_existing += 1
                    continue

                manufacturer_id = _get_or_create_manufacturer(db, manufacturers_by_lower, lens_name)
                obj = PricelistItem(
                    manufacturer_id=manufacturer_id,
                    lens_name=lens_name,
                    price=price,
                    group=gn,
                )
                db.add(obj)
                created += 1

        db.commit()

        created_manufacturers = max(0, len(manufacturers_by_lower) - initial_mfr_count)
        print(
            f"Import done. created_pricelist_items={created}, skipped_existing={skipped_existing}, created_manufacturers={created_manufacturers}",
            file=sys.stdout,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

