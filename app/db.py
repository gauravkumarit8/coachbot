"""Tiny SQLite layer. One file DB, fine for the first 10-20 institutes."""
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

DB_PATH = os.getenv("COACHBOT_DB", "coachbot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY, institute TEXT, channel TEXT, user_id TEXT,
  role TEXT, text TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS idx_msg ON messages(institute, channel, user_id, id);
CREATE TABLE IF NOT EXISTS leads(
  id INTEGER PRIMARY KEY, institute TEXT, channel TEXT, user_id TEXT,
  name TEXT, phone TEXT, exam_or_class TEXT, city TEXT, interest TEXT,
  demo_time TEXT, ts REAL, status TEXT DEFAULT 'new', note TEXT, status_ts REAL);
CREATE TABLE IF NOT EXISTS handoffs(
  institute TEXT, channel TEXT, user_id TEXT, reason TEXT, summary TEXT,
  active INTEGER DEFAULT 1, ts REAL, PRIMARY KEY(institute, channel, user_id));
CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY, ts REAL);
CREATE TABLE IF NOT EXISTS unanswered(
  id INTEGER PRIMARY KEY, institute TEXT, question TEXT, ts REAL, resolved INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_unans ON unanswered(institute, resolved);
CREATE TABLE IF NOT EXISTS inquiries(
  id INTEGER PRIMARY KEY, name TEXT, institute TEXT, city TEXT, phone TEXT, email TEXT, message TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS jobs(key TEXT PRIMARY KEY, ts REAL);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        have = {r["name"] for r in c.execute("PRAGMA table_info(leads)")}   # databases made by older versions get the new columns
        for col, ddl in (("status", "TEXT DEFAULT 'new'"), ("note", "TEXT"), ("status_ts", "REAL")):
            if col not in have:
                c.execute(f"ALTER TABLE leads ADD COLUMN {col} {ddl}")


def job_done(key: str) -> bool:
    """Scheduled jobs (daily cleanup, weekly summary) note here that they ran, so a restart never repeats them."""
    with conn() as c:
        return c.execute("SELECT 1 FROM jobs WHERE key=?", (key,)).fetchone() is not None


def mark_job(key: str, now=None):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO jobs(key, ts) VALUES(?,?)", (key, time.time() if now is None else now))


def first_time_seen(msg_id: str) -> bool:
    """Webhooks get retried by Meta. Returns False if we already handled this id."""
    with conn() as c:
        try:
            c.execute("INSERT INTO seen VALUES(?,?)", (msg_id, time.time()))
            return True
        except sqlite3.IntegrityError:
            return False


def add_message(inst, channel, user_id, role, text):
    with conn() as c:
        c.execute("INSERT INTO messages(institute,channel,user_id,role,text,ts) VALUES(?,?,?,?,?,?)",
                  (inst, channel, user_id, role, text, time.time()))


def history(inst, channel, user_id, limit=20):
    with conn() as c:
        rows = c.execute(
            "SELECT role,text FROM messages WHERE institute=? AND channel=? AND user_id=? "
            "ORDER BY id DESC LIMIT ?", (inst, channel, user_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


LEAD_FIELDS = ("name", "phone", "exam_or_class", "city", "interest", "demo_time")


def save_lead(inst, channel, user_id, **f) -> str:
    """One lead per chat: later calls fill in details instead of creating duplicates.
    Returns 'new', 'updated' (something changed) or 'same'."""
    with conn() as c:
        row = c.execute("SELECT * FROM leads WHERE institute=? AND channel=? AND user_id=? ORDER BY id DESC LIMIT 1",
                        (inst, channel, user_id)).fetchone()
        if not row:
            c.execute("INSERT INTO leads(institute,channel,user_id,name,phone,exam_or_class,city,interest,demo_time,ts) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (inst, channel, user_id, *[f.get(k) for k in LEAD_FIELDS], time.time()))
            return "new"
        changes = {k: f[k] for k in LEAD_FIELDS if f.get(k) and f[k] != row[k]}
        if not changes:
            return "same"
        c.execute("UPDATE leads SET " + ", ".join(f"{k}=?" for k in changes) + ", ts=? WHERE id=?",
                  (*changes.values(), time.time(), row["id"]))
        return "updated"


def save_inquiry(name, institute="", city="", phone="", email="", message="") -> int:
    """A visitor to OUR company page asking for a pilot (not a parent chatting with an institute's assistant)."""
    with conn() as c:
        return c.execute("INSERT INTO inquiries(name,institute,city,phone,email,message,ts) VALUES(?,?,?,?,?,?,?)",
                         (name, institute, city, phone, email, message, time.time())).lastrowid


def list_inquiries(limit=100):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM inquiries ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


LEAD_STATUSES = {"new": "New", "called": "Called", "demo_booked": "Demo booked", "joined": "Joined", "not_interested": "Not interested"}


def set_lead_status(inst, lead_id, status, note=None) -> bool:
    """The owner marks what happened to a lead. False if the status is unknown or the lead is not this institute's."""
    if status not in LEAD_STATUSES:
        return False
    with conn() as c:
        row = c.execute("SELECT id, status FROM leads WHERE id=? AND institute=?", (lead_id, inst)).fetchone()
        if not row:
            return False
        changed = (row["status"] or "new") != status
        sets, vals = ["status=?"], [status]
        if changed:
            sets.append("status_ts=?"); vals.append(time.time())
        if note is not None:
            sets.append("note=?"); vals.append(str(note).strip()[:300])
        c.execute("UPDATE leads SET " + ", ".join(sets) + " WHERE id=?", (*vals, lead_id))
    return True


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def forget(inst, key, dry_run=True) -> dict:
    """Delete-on-request: everything about one person at one institute. `key` is a phone number (matched on its last 10
    digits in leads, user ids and chat text) or a chat/session id. Returns what was (or, with dry_run, would be) deleted."""
    digits = _digits(key)[-10:] if len(_digits(key)) >= 7 else ""
    flat = lambda col: f"replace(replace(replace({col},' ',''),'-',''),'+','')"
    with conn() as c:
        queries = [("SELECT channel,user_id FROM messages WHERE institute=? AND user_id=?", (inst, str(key))),
                   ("SELECT channel,user_id FROM leads WHERE institute=? AND user_id=?", (inst, str(key)))]
        if digits:
            queries += [(f"SELECT channel,user_id FROM leads WHERE institute=? AND {flat('phone')} LIKE ?", (inst, f"%{digits}")),
                        ("SELECT channel,user_id FROM messages WHERE institute=? AND user_id LIKE ?", (inst, f"%{digits}")),
                        (f"SELECT channel,user_id FROM messages WHERE institute=? AND {flat('text')} LIKE ?", (inst, f"%{digits}%"))]
        pairs = set()
        for sql, args in queries:
            pairs.update((r[0], r[1]) for r in c.execute(sql, args))
        lead_ids = set()
        for ch, uid in pairs:
            lead_ids.update(r[0] for r in c.execute("SELECT id FROM leads WHERE institute=? AND channel=? AND user_id=?", (inst, ch, uid)))
        if digits:
            lead_ids.update(r[0] for r in c.execute(f"SELECT id FROM leads WHERE institute=? AND {flat('phone')} LIKE ?", (inst, f"%{digits}")))
        count = lambda t: sum(c.execute(f"SELECT COUNT(*) FROM {t} WHERE institute=? AND channel=? AND user_id=?", (inst, ch, uid)).fetchone()[0]
                              for ch, uid in pairs)
        counts = {"chats": len(pairs), "messages": count("messages"), "leads": len(lead_ids), "handoffs": count("handoffs")}
        if not dry_run:
            for ch, uid in pairs:
                for t in ("messages", "handoffs"):
                    c.execute(f"DELETE FROM {t} WHERE institute=? AND channel=? AND user_id=?", (inst, ch, uid))
            for lid in lead_ids:
                c.execute("DELETE FROM leads WHERE id=?", (lid,))
    return counts


def has_lead(inst, channel, user_id) -> bool:
    with conn() as c:
        return c.execute("SELECT 1 FROM leads WHERE institute=? AND channel=? AND user_id=? LIMIT 1", (inst, channel, user_id)).fetchone() is not None


def list_leads(inst, limit=100):
    with conn() as c:
        rows = c.execute("SELECT * FROM leads WHERE institute=? ORDER BY id DESC LIMIT ?",
                         (inst, limit)).fetchall()
    return [dict(r) for r in rows]


def set_handoff(inst, channel, user_id, reason="", summary="", active=True):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO handoffs VALUES(?,?,?,?,?,?,?)",
                  (inst, channel, user_id, reason, summary, 1 if active else 0, time.time()))


def is_handoff(inst, channel, user_id, max_minutes=None) -> bool:
    """True while a human owns this chat. With max_minutes, the lock expires so the bot can resume."""
    with conn() as c:
        r = c.execute("SELECT active, ts FROM handoffs WHERE institute=? AND channel=? AND user_id=?",
                      (inst, channel, user_id)).fetchone()
    if not r or not r["active"]:
        return False
    return max_minutes is None or (time.time() - r["ts"]) < max_minutes * 60


def add_unanswered(inst, question):
    """Remember a question the bot could not answer from the institute's details. Phone-like numbers are masked."""
    q = re.sub(r"\+?\d[\d\s-]{6,}\d", "[number]", question).strip()[:300]
    if q:
        with conn() as c:
            c.execute("INSERT INTO unanswered(institute,question,ts) VALUES(?,?,?)", (inst, q, time.time()))


def list_unanswered(inst, limit=50):
    """Open questions grouped by wording: [{'question', 'n', 'last'}], most asked first."""
    with conn() as c:
        rows = c.execute(
            "SELECT MIN(question) AS question, COUNT(*) AS n, MAX(ts) AS last FROM unanswered "
            "WHERE institute=? AND resolved=0 GROUP BY lower(trim(question)) ORDER BY n DESC, last DESC LIMIT ?",
            (inst, limit)).fetchall()
    return [dict(r) for r in rows]


def clear_unanswered(inst):
    with conn() as c:
        c.execute("UPDATE unanswered SET resolved=1 WHERE institute=?", (inst,))


def _tz():
    """Owners are in India. A hosted server usually runs in UTC, so do not trust the server's own clock zone.
    Default is IST (UTC+5:30); set COACHBOT_UTC_OFFSET_MIN to change it (e.g. 0 for UTC)."""
    try:
        return timezone(timedelta(minutes=int(os.getenv("COACHBOT_UTC_OFFSET_MIN", "330"))))
    except ValueError:
        return timezone(timedelta(minutes=330))


def day_start(now=None) -> float:
    """Timestamp of the most recent midnight in the owners' time zone."""
    dt = datetime.fromtimestamp(time.time() if now is None else now, _tz())
    return dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def today_str(now=None) -> str:
    return datetime.fromtimestamp(time.time() if now is None else now, _tz()).strftime("%Y-%m-%d")


def fmt_time(ts) -> str:
    return datetime.fromtimestamp(ts, _tz()).strftime("%d %b %Y, %I:%M %p")


def count_user_messages_today(inst) -> int:
    """Customer messages since midnight in the owners' time zone (used for the daily cap)."""
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM messages WHERE institute=? AND role='user' AND ts>=?",
                         (inst, day_start())).fetchone()[0]


def mask_id(user_id: str) -> str:
    """Show only the last 4 characters of a phone number / session id."""
    u = str(user_id or "")
    return ("…" + u[-4:]) if len(u) > 4 else "…"


def list_conversations(inst, limit=50):
    """Recent chats for the owner's viewer, newest first. 'ref' is the id of the chat's first message: it identifies the
    chat without putting the visitor's phone number or session id in a URL."""
    with conn() as c:
        rows = c.execute(
            "SELECT channel, user_id, MIN(id) AS ref, MAX(ts) AS last, MIN(ts) AS first, COUNT(*) AS n, "
            "SUM(role='user') AS asked FROM messages WHERE institute=? GROUP BY channel, user_id "
            "ORDER BY last DESC LIMIT ?", (inst, limit)).fetchall()
        out = []
        for r in rows:
            first_q = c.execute("SELECT text FROM messages WHERE institute=? AND channel=? AND user_id=? AND role='user' "
                                "ORDER BY id LIMIT 1", (inst, r["channel"], r["user_id"])).fetchone()
            lead = c.execute("SELECT 1 FROM leads WHERE institute=? AND channel=? AND user_id=? LIMIT 1",
                             (inst, r["channel"], r["user_id"])).fetchone()
            out.append({"ref": r["ref"], "channel": r["channel"], "who": mask_id(r["user_id"]), "started": r["first"],
                        "last": r["last"], "messages": r["n"], "asked": r["asked"] or 0,
                        "first_question": (first_q["text"] if first_q else "")[:120], "lead": bool(lead)})
    return out


def get_conversation(inst, ref, limit=300):
    """Messages of one chat, or None. The chat must belong to `inst`, so a ref from another institute finds nothing."""
    with conn() as c:
        first = c.execute("SELECT channel, user_id FROM messages WHERE id=? AND institute=?", (ref, inst)).fetchone()
        if not first:
            return None
        rows = c.execute("SELECT role, text, ts FROM messages WHERE institute=? AND channel=? AND user_id=? "
                         "ORDER BY id LIMIT ?", (inst, first["channel"], first["user_id"], limit)).fetchall()
    return {"channel": first["channel"], "who": mask_id(first["user_id"]), "messages": [dict(r) for r in rows]}
