"""Offline tests: onboarding script and pilot report. Run: python -m tests.test_onboard_report"""
import json, os, tempfile, time
from datetime import datetime, timezone
from pathlib import Path

os.environ["COACHBOT_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.pop("COACHBOT_UTC_OFFSET_MIN", None)
from app import db, onboard, registry, report  # noqa: E402

db.init()
root, envp = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()) / ".env"

# ---- onboarding ----
r = onboard.make("mcm-patna", "MCM Patna", phone="+91 99999 00001", telegram_chat="42", email="o@x.in", root=root, env_path=envp, write_env=True)
cfg = json.loads((root / "mcm-patna" / "config.json").read_text())
assert cfg["id"] == "mcm-patna" and cfg["owner_key_env"] == "MCM_PATNA_OWNER_KEY" and cfg["owner_phone"] == "919999900001"
assert cfg["alerts"] == {"telegram_chat_id": "42", "email": "o@x.in"} and not cfg.get("unofficial_demo")
kn = (root / "mcm-patna" / "knowledge.md").read_text()
assert "MCM Patna" in kn and "{name}" not in kn and kn.count("NOT provided, counsellor must confirm") >= 8 and len(kn) < registry.MAX_KNOWLEDGE_CHARS
line = [l for l in envp.read_text().splitlines() if l.startswith("MCM_PATNA_OWNER_KEY=")][0]
assert len(line.split("=", 1)[1]) >= 12 and line.split("=", 1)[1] == r["key"] and r["written"]       # strong enough for the owner page
assert r["key"] not in onboard.instructions(r)                                                         # key not echoed when written to .env
assert registry.Registry(root).get("mcm-patna")["config"]["name"] == "MCM Patna"                       # the app can load it
assert "widget.js" in onboard.instructions(r, "https://x.in") and 'data-institute="mcm-patna"' in onboard.instructions(r, "https://x.in")
# a second institute without --write-env prints the key instead; an existing key is never overwritten
r2 = onboard.make("abc-classes", "ABC Classes", root=root, env_path=envp)
assert not r2["written"] and r2["key"] in onboard.instructions(r2) and "alerts" not in r2["config"]
before = envp.read_text()
(root / "x1").mkdir(); (root / "x1").rmdir()
r3 = onboard.make("mcm-patna2", "M2", root=root, env_path=envp, write_env=True)
envp.write_text(before + "ZED_OWNER_KEY=keepme-keepme-1\n")
r4 = onboard.make("zed", "Zed", root=root, env_path=envp, write_env=True)
assert r4["key"] is None and "keepme-keepme-1" in envp.read_text() and envp.read_text().count("ZED_OWNER_KEY=") == 1
for bad, name, why in (("MCM Patna", "x", "uppercase/space"), ("ab", "x", "too short"), ("mcm-patna", "Again", "exists"), ("good-id", "  ", "no name"), ("../evil", "x", "path")):
    try:
        onboard.make(bad, name, root=root); raise AssertionError(f"should refuse: {why}")
    except ValueError:
        pass
assert not (root.parent / "evil").exists()

# ---- pilot report ----
ist = lambda y, m, d, h, mi=0: datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp() - 5.5 * 3600        # a clock time in India
now = ist(2026, 11, 20, 12)
def msg(user, ts, role="user", inst="p1"):
    with db.conn() as c:
        c.execute("INSERT INTO messages(institute,channel,user_id,role,text,ts) VALUES(?,?,?,?,?,?)", (inst, "website", user, role, "hi", ts))
msg("a", ist(2026, 11, 19, 22, 30)); msg("a", ist(2026, 11, 19, 22, 31), "assistant")     # 10:30 pm: after hours
msg("b", ist(2026, 11, 19, 6, 0))                                                           # 6 am: after hours
msg("c", ist(2026, 11, 19, 11, 0))                                                          # 11 am: office hours
msg("c", ist(2026, 11, 19, 23, 0))                                                          # later message of an office-hours chat: not counted
msg("old", ist(2026, 10, 1, 22, 0))                                                         # outside the 14 days
msg("other", ist(2026, 11, 19, 23, 0), inst="p2")                                           # another institute
for u, ts, demo in (("a", ist(2026, 11, 19, 22, 40), "Sat 5pm"), ("c", ist(2026, 11, 19, 11, 5), None)):
    db.save_lead("p1", "website", u, name="N" + u, phone="9990001111", demo_time=demo)
with db.conn() as c:
    c.execute("UPDATE leads SET ts=? WHERE institute='p1'", (now - 3600,))
db.add_unanswered("p1", "hostel ac?")
r = report.build("p1", 14, now=now)
assert (r["chats"], r["after_hours_chats"], r["leads"], r["demo_requests"], r["customer_messages"]) == (3, 2, 2, 1, 4), r
assert r["lead_rate"] == 66.7 and r["unanswered_questions"] == 1 and r["handoffs"] == 0
assert report.build("p1", 14, 9, 23, now=now)["after_hours_chats"] == 1                       # a longer working day changes the count
empty = report.build("nobody", 14, now=now)
assert empty["chats"] == 0 and empty["lead_rate"] == 0.0 and "After-hours enquiries answered : 0" in report.render(empty)
assert "Leads captured" in report.render(r) and "Demo classes requested" in report.render(r)
print("onboard and report tests passed")
