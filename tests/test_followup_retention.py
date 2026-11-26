"""Offline tests: lead follow-up status, weekly summary, data retention, delete-on-request, scheduler.
Run: python -m tests.test_followup_retention"""
import csv, io, json, logging, os, sqlite3, tempfile, time, types
from datetime import datetime, timezone
from pathlib import Path

from tests import fastapi_stub
fastapi_stub.install()
DBFILE = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(COACHBOT_DB=DBFILE, LLM_PROVIDER="anthropic", OWNER_A_KEY="owner-a-key-123456", ADMIN_TOKEN="admin-token-123456", COACHBOT_BACKGROUND_JOBS="0")
for k in ("COACHBOT_UTC_OFFSET_MIN", "RETENTION_DAYS", "LEAD_RETENTION_DAYS"):
    os.environ.pop(k, None)

# an OLD database (made before follow-up statuses existed) must be upgraded in place, keeping its leads
old = sqlite3.connect(DBFILE)
old.executescript("""CREATE TABLE leads(id INTEGER PRIMARY KEY, institute TEXT, channel TEXT, user_id TEXT, name TEXT, phone TEXT,
    exam_or_class TEXT, city TEXT, interest TEXT, demo_time TEXT, ts REAL);
    INSERT INTO leads(institute,channel,user_id,name,phone,ts) VALUES('official','website','legacy','Old Lead','9000000001',1.0);""")
old.commit(); old.close()

from app import company, db, export, jobs, main, notify, registry, report, retention, weekly  # noqa: E402
from fastapi import HTTPException  # noqa: E402

logging.disable(logging.CRITICAL)
db.init(); db.init()                                                               # twice: the upgrade is safe to repeat
assert db.list_leads("official")[0]["status"] == "new" and db.list_leads("official")[0]["name"] == "Old Lead"

KB = "## About\nA coaching institute in Patna with batches for classes 9 to 12 and fees listed here.\n"
root = Path(tempfile.mkdtemp())
def make(iid, **cfg):
    d = root / iid; d.mkdir()
    (d / "config.json").write_text(json.dumps({"id": iid, "name": iid.title(), **cfg})); (d / "knowledge.md").write_text(KB)
make("official", owner_key_env="OWNER_A_KEY", alerts={"telegram_chat_id": "42"})
make("quiet", owner_key_env="OWNER_A_KEY", alerts={"telegram_chat_id": "43"}, weekly_summary=False, retention_days=30, lead_retention_days=0)
make("noalerts", owner_key_env="OWNER_A_KEY")
make("demo-abc12345", unofficial_demo=True, alerts={"telegram_chat_id": "44"})
reg = registry.Registry(root); main.reg = reg
INSTS = reg.all()

class Req:
    def __init__(self, host="9.9.9.9"): self.headers, self.client = {}, types.SimpleNamespace(host=host)
def code_of(fn, *a, **k):
    try:
        fn(*a, **k)
    except HTTPException as e:
        return e.status_code
    return 200
KEY = "owner-a-key-123456"
DAY = 86400
ist = lambda y, m, d, h, mi=0: datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp() - 5.5 * 3600
NOW = ist(2026, 11, 26, 12)                                                       # Thursday noon in India

def msg(inst, user, ts, role="user", text="hi", channel="website"):
    with db.conn() as c:
        c.execute("INSERT INTO messages(institute,channel,user_id,role,text,ts) VALUES(?,?,?,?,?,?)", (inst, channel, user, role, text, ts))
def set_lead_ts(inst, ts):
    with db.conn() as c:
        c.execute("UPDATE leads SET ts=? WHERE institute=?", (ts, inst))

# ================= 1. lead follow-up status =================
db.save_lead("official", "website", "u1", name="Ravi", phone="9990001111", demo_time="Sat 5pm")
db.save_lead("official", "website", "u2", name="Sita", phone="9990002222")
db.save_lead("quiet", "website", "q1", name="Other", phone="9990003333")
leads = main.owner_leads("official", Req(), KEY)
ravi = next(l for l in leads if l["name"] == "Ravi")
assert ravi["status"] == "new" and ravi["note"] == "" and isinstance(ravi["id"], int)
assert main.owner_lead_status("official", ravi["id"], main.LeadStatusIn(status="called", note="Will visit Sunday"), Req(), KEY) == {"ok": True}
row = next(l for l in db.list_leads("official") if l["id"] == ravi["id"])
assert row["status"] == "called" and row["note"] == "Will visit Sunday" and row["status_ts"]
t1 = row["status_ts"]; time.sleep(0.01)
main.owner_lead_status("official", ravi["id"], main.LeadStatusIn(status="called", note="Rang twice"), Req(), KEY)           # note changes, status does not
row = next(l for l in db.list_leads("official") if l["id"] == ravi["id"])
assert row["note"] == "Rang twice" and row["status_ts"] == t1                                                              # status time only moves on a real change
main.owner_lead_status("official", ravi["id"], main.LeadStatusIn(status="joined"), Req(), KEY)                             # no note sent: old note kept
row = next(l for l in db.list_leads("official") if l["id"] == ravi["id"])
assert row["status"] == "joined" and row["note"] == "Rang twice" and row["status_ts"] > t1
db.save_lead("official", "website", "u1", city="Patna")                                                                    # the parent chats again: status survives
assert next(l for l in db.list_leads("official") if l["id"] == ravi["id"])["status"] == "joined"
other = db.list_leads("quiet")[0]["id"]
assert code_of(main.owner_lead_status, "official", other, main.LeadStatusIn(status="called"), Req(), KEY) == 404          # another institute's lead
assert code_of(main.owner_lead_status, "official", 99999, main.LeadStatusIn(status="called"), Req(), KEY) == 404
assert code_of(main.owner_lead_status, "official", ravi["id"], main.LeadStatusIn(status="hacked"), Req(), KEY) == 400
assert code_of(main.owner_lead_status, "official", ravi["id"], main.LeadStatusIn(status="called"), Req(), "wrong") == 403
assert db.list_leads("quiet")[0]["status"] == "new"
rows = list(csv.reader(io.StringIO(export.leads_csv(db.list_leads("official")).lstrip("\ufeff"))))
assert rows[0][-2:] == ["Status", "Note"] and any(r[1] == "Ravi" and r[8] == "Joined" and r[9] == "Rang twice" for r in rows[1:]) and any(r[8] == "New" for r in rows[1:])
db.set_lead_status("official", ravi["id"], "not_interested", note="=cmd()")
assert "'=cmd()" in export.leads_csv(db.list_leads("official"))                                                            # notes cannot become spreadsheet formulas
db.set_lead_status("official", ravi["id"], "joined")
html = (Path(__file__).resolve().parent.parent / "static" / "owner.html").read_text(encoding="utf-8")
assert all(s in html for s in ("Called", "Demo booked", "Joined", "Not interested", "still waiting for your call", "What happened?"))

# ================= 2. weekly summary =================
msg("official", "a", ist(2026, 11, 24, 22, 30)); msg("official", "b", ist(2026, 11, 25, 11, 0)); msg("official", "c", ist(2026, 11, 25, 6, 0))
msg("official", "old", ist(2026, 11, 1, 22, 0))                                                                          # outside the 7 days
set_lead_ts("official", NOW - 2 * DAY)
db.add_unanswered("official", "hostel with ac?"); db.add_unanswered("official", "Hostel with AC?"); db.add_unanswered("official", "bus facility?")
text = weekly.build(INSTS["official"], NOW)
assert "Official" in text and "Chats: 3 (2 started outside 09:00 to 19:00" in text, text
assert "Leads this week: 3 (1 asked for a demo class)" in text and "Joined this week: 1" in text and "Still waiting for your call: 2" in text
assert " - 2x hostel with ac?" in text.lower() and "bus facility?" in text
assert "Call the 2 lead(s) still marked New" in text and "Mark all as done" in text
assert weekly.render({**weekly.collect(INSTS["official"], NOW), "chats": 0, "leads": 0, "waiting": 0, "unanswered_top": []})  .count("No chats this week") == 1
assert "nobody asked for a callback" in weekly.render({**weekly.collect(INSTS["official"], NOW), "leads": 0, "waiting": 0, "unanswered_top": []})
assert main.owner_summary("official", Req(), KEY)["text"].startswith("CoachBot weekly summary: Official") and code_of(main.owner_summary, "official", Req(), "no") == 403
# when it is due, and sent at most once a week
assert not weekly.due(ist(2026, 11, 23, 8, 59)) and weekly.due(ist(2026, 11, 23, 9, 0)) and weekly.due(ist(2026, 11, 24, 0, 5)) and weekly.due(ist(2026, 11, 29, 20))
assert weekly.week_key(ist(2026, 11, 23, 9)) == weekly.week_key(ist(2026, 11, 29, 23)) != weekly.week_key(ist(2026, 11, 30, 9))
sent = []
def ok_send(alerts, text): sent.append((alerts, text)); return {"telegram": True}
MON = ist(2026, 11, 30, 10)
assert weekly.send_due(INSTS, MON, send=ok_send) == ["official"]                                                         # not quiet (switched off), noalerts, demo
assert sent[0][0] == {"telegram_chat_id": "42"} and "weekly summary: Official" in sent[0][1]
assert weekly.send_due(INSTS, MON + 3600, send=ok_send) == [] and len(sent) == 1                                         # already sent this week
assert weekly.send_due(INSTS, MON + 3600, force=True, send=ok_send) == ["official"]                                      # forced (manual --send)
assert weekly.send_due(INSTS, MON + 7 * DAY, send=ok_send) == ["official"]                                               # next week: sent again
fails = []
make("flaky", owner_key_env="OWNER_A_KEY", alerts={"email": "o@x.in"}); INSTS = reg.all()
def bad_send(alerts, text): fails.append(1); return {"email": False}
assert weekly.send_due({"flaky": INSTS["flaky"]}, MON, send=bad_send) == [] and weekly.send_due({"flaky": INSTS["flaky"]}, MON + 3600, send=bad_send) == [] and len(fails) == 2   # failed: retried
def boom(alerts, text): raise RuntimeError("smtp down")
assert weekly.send_due({"flaky": INSTS["flaky"]}, MON, send=boom) == []                                                  # never crashes the checker
assert weekly.send_due({"flaky": INSTS["flaky"]}, MON, send=ok_send) == ["flaky"]

# ================= 3. data retention =================
old_ts, new_ts = NOW - 200 * DAY, NOW - 10 * DAY
for inst in ("official", "quiet"):
    msg(inst, "r-old", old_ts); msg(inst, "r-old", old_ts + 5, "assistant"); msg(inst, "r-new", new_ts)
    db.add_unanswered(inst, "very old question")
with db.conn() as c:
    c.execute("UPDATE unanswered SET ts=? WHERE question='very old question'", (old_ts,))
    c.execute("INSERT INTO seen VALUES('wamid.old', ?), ('wamid.new', ?)", (NOW - 9 * DAY, NOW - 3600))
    c.execute("INSERT INTO handoffs(institute,channel,user_id,reason,summary,active,ts) VALUES('official','website','r-old','refund','s',1,?)", (old_ts,))
    c.execute("INSERT INTO leads(institute,channel,user_id,name,phone,ts,status) VALUES('official','website','L-old','Ancient','9111111111',?,'new')", (NOW - 400 * DAY,))
    c.execute("INSERT INTO leads(institute,channel,user_id,name,phone,ts,status) VALUES('official','website','L-mid','Mid','9222222222',?,'new')", (NOW - 200 * DAY,))
    c.execute("INSERT INTO leads(institute,channel,user_id,name,phone,ts,status) VALUES('quiet','website','L-q','QuietOld','9333333333',?,'new')", (NOW - 900 * DAY,))
    c.execute("INSERT INTO inquiries(name,ts) VALUES('Old inquiry', ?), ('New inquiry', ?)", (NOW - 400 * DAY, NOW - DAY))
    n_msgs = lambda inst, u: c.execute("SELECT COUNT(*) FROM messages WHERE institute=? AND user_id=?", (inst, u)).fetchone()[0]
assert retention.settings({}) == (180, 365) and retention.settings({"retention_days": 30, "lead_retention_days": 0}) == (30, None)
os.environ["RETENTION_DAYS"] = "90"; assert retention.settings({}) == (90, 365) and retention.settings({"retention_days": 7})[0] == 7
os.environ["RETENTION_DAYS"] = "junk"; assert retention.settings({})[0] == 180; os.environ["RETENTION_DAYS"] = "0"; assert retention.settings({})[0] is None
os.environ.pop("RETENTION_DAYS")
def count(sql, *a):
    with db.conn() as c: return c.execute(sql, a).fetchone()[0]
dry = retention.run(INSTS, NOW, dry_run=True)
assert dry["official"]["messages"] == 2 and dry["official"]["leads"] == 1 and dry["quiet"]["messages"] == 2 and dry["_shared"]["webhook_ids"] == 1
assert count("SELECT COUNT(*) FROM messages WHERE user_id='r-old'") == 4 and count("SELECT COUNT(*) FROM leads WHERE user_id='L-old'") == 1   # dry run deleted nothing
res = retention.run(INSTS, NOW)
assert res["official"] == {"messages": 2, "leads": 1, "handoffs": 1, "unanswered": 1}, res["official"]
assert count("SELECT COUNT(*) FROM messages WHERE institute='official' AND user_id='r-old'") == 0                         # old chat gone
assert count("SELECT COUNT(*) FROM messages WHERE institute='official' AND user_id='r-new'") == 1                         # recent chat kept
assert count("SELECT COUNT(*) FROM leads WHERE user_id='L-old'") == 0 and count("SELECT COUNT(*) FROM leads WHERE user_id='L-mid'") == 1   # leads live longer than chats
assert count("SELECT COUNT(*) FROM leads WHERE user_id='L-q'") == 1                                                       # lead_retention_days 0 = keep forever
assert count("SELECT COUNT(*) FROM messages WHERE institute='quiet' AND user_id='r-old'") == 0 and count("SELECT COUNT(*) FROM messages WHERE institute='quiet' AND user_id='r-new'") == 1
assert count("SELECT COUNT(*) FROM seen WHERE id='wamid.old'") == 0 and count("SELECT COUNT(*) FROM seen WHERE id='wamid.new'") == 1
assert count("SELECT COUNT(*) FROM inquiries WHERE name='Old inquiry'") == 0 and count("SELECT COUNT(*) FROM inquiries WHERE name='New inquiry'") == 1
assert count("SELECT COUNT(*) FROM messages WHERE institute='ghost'") == 0 and retention.run({}, NOW)["_shared"]["webhook_ids"] == 0   # unknown institutes are not touched
assert sum(retention.run(INSTS, NOW)["official"].values()) == 0                                                           # second run: nothing left to remove

# ================= 4. delete on request =================
db.save_lead("official", "website", "sess-777", name="Parent", phone="+91 98765 43210")
msg("official", "sess-777", NOW, text="my number is 98765-43210"); msg("official", "sess-777", NOW, "assistant", "ok")
msg("official", "sess-888", NOW, text="please call 9876543210 tomorrow")                                                  # same person, chat before the lead
msg("official", "919876543210", NOW, text="hello", channel="whatsapp")                                                    # WhatsApp: the id IS the number
msg("official", "sess-999", NOW, text="unrelated parent")
db.save_lead("official", "website", "sess-999", name="Other", phone="9000000009")
msg("quiet", "sess-777", NOW, text="my number is 98765-43210")                                                           # same text at ANOTHER institute
dry = db.forget("official", "98765 43210")
assert dry == {"chats": 3, "messages": 4, "leads": 1, "handoffs": 0}, dry
assert count("SELECT COUNT(*) FROM messages WHERE institute='official' AND user_id='sess-777'") == 2                    # dry run is the default
done = db.forget("official", "+91 98765 43210", dry_run=False)
assert done == dry
assert count("SELECT COUNT(*) FROM messages WHERE institute='official' AND user_id IN ('sess-777','sess-888','919876543210')") == 0
assert count("SELECT COUNT(*) FROM leads WHERE phone LIKE '%43210%'") == 0
assert count("SELECT COUNT(*) FROM messages WHERE user_id='sess-999'") == 1 and count("SELECT COUNT(*) FROM leads WHERE user_id='sess-999'") == 1   # others untouched
assert count("SELECT COUNT(*) FROM messages WHERE institute='quiet' AND user_id='sess-777'") == 1                         # other institute untouched
assert db.forget("official", "sess-999", dry_run=False)["leads"] == 1 and count("SELECT COUNT(*) FROM leads WHERE user_id='sess-999'") == 0   # by chat id
assert db.forget("official", "123", dry_run=False) == {"chats": 0, "messages": 0, "leads": 0, "handoffs": 0}              # too short to be a phone: matches nothing
db.save_lead("official", "website", "gone-chat", name="Lonely", phone="9555555555")
with db.conn() as c: c.execute("DELETE FROM messages WHERE user_id='gone-chat'")
assert db.forget("official", "9555555555", dry_run=False)["leads"] == 1                                                   # lead whose chat was already deleted

# ================= 5. background jobs =================
retention_runs = []
real_run = retention.run; retention.run = lambda *a, **k: retention_runs.append(1) or real_run(*a, **k)
sent.clear()
msg("official", "late", ist(2026, 12, 14, 9, 30))
T = ist(2026, 12, 14, 10)                                                                                                  # a Monday
out = jobs.tick(reg.all(), T, send=ok_send)
assert "retention" in out and sorted(out["weekly"]) == ["flaky", "official"] and len(sent) == 2
out = jobs.tick(reg.all(), T + 3600, send=ok_send)
assert "retention" not in out and out["weekly"] == [] and len(retention_runs) == 1 and len(sent) == 2                      # nothing repeats
out = jobs.tick(reg.all(), T + DAY + 3600, send=ok_send)
assert "retention" in out and out["weekly"] == [] and len(retention_runs) == 2                                            # cleanup runs daily, summary weekly
assert "weekly" not in jobs.tick(reg.all(), ist(2026, 12, 21, 8), send=ok_send)                                           # Monday 8 am: too early
retention.run = real_run
assert jobs.start(reg.all) is None                                                                                        # switched off in tests
os.environ["COACHBOT_BACKGROUND_JOBS"] = "1"
th = jobs.start(lambda: {}, first_delay=3600); assert th.daemon and th.is_alive()                                         # a daemon thread, never blocks shutdown
os.environ["COACHBOT_BACKGROUND_JOBS"] = "0"

# ================= 6. report shows follow-up =================
r = report.build("official", 14, now=NOW)
assert r["leads_followed_up"] >= 1 and r["leads_joined"] >= 1 and "Leads followed up" in report.render(r)
print("follow-up, weekly summary and retention tests passed")
