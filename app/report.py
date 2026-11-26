"""Pilot report: python -m app.report <institute_id> [days]  (default 14 days)

Prints the three numbers a pilot is judged on, plus a few health numbers, for one institute:
  1. enquiries answered AFTER HOURS (first message of a chat outside office hours, Indian time)
  2. leads captured
  3. demo classes booked (leads that came with a preferred demo time)
Office hours default to 09:00 to 19:00 (--open / --close)."""
import argparse
import time
from datetime import datetime

from . import db


def build(inst: str, days: int = 14, open_h: int = 9, close_h: int = 19, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    since = now - days * 86400
    tz = db._tz()
    with db.conn() as c:
        firsts = c.execute("SELECT channel, user_id, MIN(ts) AS t FROM messages WHERE institute=? AND ts>=? AND role='user' "
                           "GROUP BY channel, user_id", (inst, since)).fetchall()
        msgs = c.execute("SELECT COUNT(*) FROM messages WHERE institute=? AND ts>=? AND role='user'", (inst, since)).fetchone()[0]
        leads = c.execute("SELECT * FROM leads WHERE institute=? AND ts>=?", (inst, since)).fetchall()
        unanswered = c.execute("SELECT COUNT(*) FROM unanswered WHERE institute=? AND ts>=?", (inst, since)).fetchone()[0]
        handoffs = c.execute("SELECT COUNT(*) FROM handoffs WHERE institute=? AND ts>=?", (inst, since)).fetchone()[0]
    after = sum(1 for r in firsts if not (open_h <= datetime.fromtimestamp(r["t"], tz).hour < close_h))
    followed = sum(1 for l in leads if (l["status"] or "new") != "new")
    joined = sum(1 for l in leads if l["status"] == "joined")
    chats = len(firsts)
    return {"institute": inst, "days": days, "chats": chats, "customer_messages": msgs, "after_hours_chats": after,
            "leads": len(leads), "demo_requests": sum(1 for l in leads if (l["demo_time"] or "").strip()),
            "lead_rate": round(100 * len(leads) / chats, 1) if chats else 0.0, "leads_followed_up": followed, "leads_joined": joined, "unanswered_questions": unanswered, "handoffs": handoffs,
            "office_hours": f"{open_h:02d}:00 to {close_h:02d}:00"}


def render(r: dict) -> str:
    return f"""Pilot report for {r['institute']}: last {r['days']} days
  THE 3 PILOT NUMBERS
  1. After-hours enquiries answered : {r['after_hours_chats']}   (chats that started outside {r['office_hours']} IST)
  2. Leads captured                 : {r['leads']}   ({r['lead_rate']}% of {r['chats']} chats)
  3. Demo classes requested         : {r['demo_requests']}
  FOLLOW-UP (marked by the institute on its owner page)
  Leads followed up: {r['leads_followed_up']} of {r['leads']}.  Joined: {r['leads_joined']}
  HEALTH
  Chats {r['chats']}, customer messages {r['customer_messages']}, handoffs {r['handoffs']}, questions the details did not cover {r['unanswered_questions']}"""


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(); ap.add_argument("institute"); ap.add_argument("days", nargs="?", type=int, default=14)
    ap.add_argument("--open", type=int, default=9); ap.add_argument("--close", type=int, default=19)
    a = ap.parse_args()
    db.init()
    print(render(build(a.institute, a.days, a.open, a.close)))
