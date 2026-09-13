import json, re, sys
sys.path.insert(0, "/home/crm-backend")
from database import SessionLocal
from models import Order1cExchangeLog

VZAIM_RE = re.compile(r"Взаимозачет", re.I)
NUM_RE = re.compile(r"(\d{6,})")

db = SessionLocal()
logs = db.query(Order1cExchangeLog).filter(Order1cExchangeLog.json_parse_ok == True).all()
by_key = {}
dups = []
for lg in logs:
    try:
        p = json.loads(lg.body_text or "{}")
    except Exception:
        continue
    ba = p.get("bonus_arr")
    if not isinstance(ba, list):
        continue
    for row in ba:
        if not isinstance(row, dict):
            continue
        doc = str(row.get("doc") or "")
        if not VZAIM_RE.search(doc):
            continue
        on = str(row.get("order_number") or "").replace("\xa0", " ").strip()
        od = str(row.get("operation_date") or "")
        year = od[:4] if len(od) >= 4 else "?"
        m = NUM_RE.search(doc)
        num = m.group(1) if m else doc
        key = (year, on)
        entry = (num, lg.id, doc[:60])
        if key in by_key:
            dups.append((key, by_key[key], entry))
        else:
            by_key[key] = entry

print("total vzaim keys", len(by_key))
print("duplicates", len(dups))
for d in dups[:15]:
    print(" DUP", d[0], "existing", d[1], "new", d[2])
db.close()
