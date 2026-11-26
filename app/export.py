"""CSV export of leads for owners (opens in Excel / Google Sheets)."""
import csv
import io
import re

from . import db

COLUMNS = [("When", "ts"), ("Name", "name"), ("Phone", "phone"), ("Class / exam", "exam_or_class"),
           ("City", "city"), ("Interest", "interest"), ("Demo time", "demo_time"), ("Channel", "channel"), ("Status", "status"), ("Note", "note")]


_PHONE = re.compile(r"^\+?[\d\s()-]+$")


def _safe(v) -> str:
    """A cell that starts with = + - @ can run as a formula when the file is opened in Excel: defuse it with a quote."""
    s = "" if v is None else str(v).replace("\r", " ").replace("\n", " ")
    if _PHONE.match(s):
        return s  # a phone number like +91 99900 01111 is only digits: harmless, and an owner should not see a stray quote
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t") else s


def leads_csv(leads: list) -> str:
    """`leads` = rows from db.list_leads. Starts with a byte-order mark so Excel reads Hindi names correctly."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([h for h, _ in COLUMNS])
    for l in leads:
        w.writerow([db.fmt_time(l["ts"]) if k == "ts" else _safe(db.LEAD_STATUSES.get(l.get("status") or "new", l.get("status")) if k == "status" else l.get(k))
                    for _, k in COLUMNS])
    return "\ufeff" + buf.getvalue()
