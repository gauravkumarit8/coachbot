"""Offline tests: private demo links, chat viewer, CSV export, owners' time zone, new_demo and the alert test command.
Run: python -m tests.test_viewer_privacy_export"""
import csv, io, json, logging, os, re, tempfile, types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests import fastapi_stub
fastapi_stub.install()
os.environ.update(COACHBOT_DB=os.path.join(tempfile.mkdtemp(), "t.db"), LLM_PROVIDER="anthropic", OWNER_A_KEY="owner-a-key-123456",
                  ADMIN_TOKEN="admin-token-123456", TG_TOKEN="123:tok")
for k in ("META_APP_SECRET", "TRUST_PROXY", "COACHBOT_UTC_OFFSET_MIN"):
    os.environ.pop(k, None)

from app import db, export, main, new_demo, notify, registry  # noqa: E402
from fastapi import HTTPException  # noqa: E402

logging.disable(logging.CRITICAL)
db.init()
KB = "## About\nA coaching institute in Patna with batches for classes 9 to 12 and fees listed here.\n"
root = Path(tempfile.mkdtemp())
def make(iid, **cfg):
    d = root / iid; d.mkdir()
    (d / "config.json").write_text(json.dumps({"id": iid, "name": iid.title(), **cfg})); (d / "knowledge.md").write_text(KB)
make("official", owner_key_env="OWNER_A_KEY", alerts={"telegram_chat_id": "42", "telegram_token_env": "TG_TOKEN"})
make("other", owner_key_env="OWNER_A_KEY")
make("tribac-k4x9m2qa", unofficial_demo=True)
main.reg = registry.Registry(root)

class Req:
    def __init__(self, host="9.9.9.9"): self.headers, self.client = {}, types.SimpleNamespace(host=host)
def code_of(fn, *a, **k):
    try:
        fn(*a, **k)
    except HTTPException as e:
        return e.status_code
    return 200
KEY, ADMIN = "owner-a-key-123456", "admin-token-123456"

# ---------- 1. private demo links ----------
assert code_of(main.institute_shortcut, "tribac-k4x9m2qa") == 404              # unofficial demos have no /<id> shortcut
assert code_of(main.institute_shortcut, "tribac") == 404                        # guessing the plain name finds nothing
assert main.institute_shortcut("official").url == "/demo?institute=official"    # normal institutes keep it
assert main.public_info("tribac-k4x9m2qa")["unofficial"] is True               # the real link (demo page) still works
assert "Disallow: /demo" in main.robots().body and "Disallow: /owner/" in main.robots().body and "Disallow: /\n" not in main.robots().body   # home page stays indexable
assert "tribac" not in json.dumps(main.health())                                # health never lists ids
assert 'name="robots" content="noindex' in (Path(__file__).resolve().parent.parent / "static" / "demo.html").read_text(encoding="utf-8")

# ---------- 2. chat viewer ----------
db.add_message("official", "website", "session-secret-ab12", "user", "What are the fees?")
db.add_message("official", "website", "session-secret-ab12", "assistant", "Class 11 is Rs 45,000.")
db.add_message("official", "whatsapp", "919900011122", "user", "Batch timing?")
db.add_message("other", "website", "x-other-9999", "user", "secret question of another institute")
db.save_lead("official", "website", "session-secret-ab12", name="Ravi", phone="9990001111")
chats = main.owner_chats("official", Req(), KEY)
assert len(chats) == 2 and {c["channel"] for c in chats} == {"website", "whatsapp"}, chats
raw = json.dumps(chats)
assert "session-secret" not in raw and "919900011122" not in raw and "other institute" not in raw   # masked, and only THEIR chats
web = next(c for c in chats if c["channel"] == "website")
assert web["who"] == "…ab12" and web["lead"] is True and web["messages"] == 2 and web["first_question"] == "What are the fees?"
assert next(c for c in chats if c["channel"] == "whatsapp")["lead"] is False
one = main.owner_chat("official", web["ref"], Req(), KEY)
assert [m["role"] for m in one["messages"]] == ["user", "assistant"] and one["messages"][1]["text"].startswith("Class 11") and one["who"] == "…ab12"
other_ref = main.owner_chats("other", Req(), KEY)[0]["ref"]
assert code_of(main.owner_chat, "official", other_ref, Req(), KEY) == 404       # a ref from another institute finds nothing
assert code_of(main.owner_chat, "official", 999999, Req(), KEY) == 404
assert code_of(main.owner_chats, "official", Req(), "wrong") == 403 and code_of(main.owner_chat, "official", web["ref"], Req(), None) == 403
assert len(main.admin_chats("official", ADMIN)) == 2 and main.admin_chat("official", web["ref"], ADMIN)["messages"]
assert code_of(main.admin_chats, "official", "nope") == 403 and code_of(main.admin_chat, "official", web["ref"], None) == 403
assert code_of(main.admin_chat, "official", other_ref, ADMIN) == 404

# ---------- 3. CSV export ----------
db.save_lead("official", "website", "u-evil", name="=HYPERLINK(\"http://x\")", phone="+91 98000 00000", exam_or_class="JEE", city="Patna",
             interest="line1\nline2", demo_time="Sat 5pm")
text = export.leads_csv(db.list_leads("official"))
assert text.startswith("\ufeff")                                                 # Excel reads Hindi names correctly
rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
assert rows[0] == ["When", "Name", "Phone", "Class / exam", "City", "Interest", "Demo time", "Channel", "Status", "Note"] and len(rows) == 3, rows
evil = next(r for r in rows[1:] if r[7] == "website" and r[2].startswith("+91 98"))
assert evil[1].startswith("'=") and evil[5] == "line1 line2" and evil[3] == "JEE"      # formulas defused, newlines flattened
assert evil[2] == "+91 98000 00000"                                                  # a plain phone number is left alone
resp = main.owner_leads_csv("official", Req(), KEY)
assert resp.media_type.startswith("text/csv") and "Ravi" in resp.body and code_of(main.owner_leads_csv, "official", Req(), "bad") == 403
assert "secret" not in resp.body and main.leads_csv("official", ADMIN).body == resp.body and code_of(main.leads_csv, "official", "nope") == 403

# ---------- 4. owners' time zone (IST by default, whatever the server's clock zone) ----------
utc = lambda *a: datetime(*a, tzinfo=timezone.utc).timestamp()
t = utc(2026, 11, 25, 20, 0)                                                     # 01:30 on 26 Nov in India
assert db.today_str(t) == "2026-11-26" and db.day_start(t) == utc(2026, 11, 25, 18, 30)
assert db.fmt_time(t) == "26 Nov 2026, 01:30 AM"
os.environ["COACHBOT_UTC_OFFSET_MIN"] = "0"
assert db.today_str(t) == "2026-11-25" and db.day_start(t) == utc(2026, 11, 25)
os.environ["COACHBOT_UTC_OFFSET_MIN"] = "banana"                                 # a typo must not crash the chat
assert db.today_str(t) == "2026-11-26"
os.environ.pop("COACHBOT_UTC_OFFSET_MIN")
with db.conn() as c:                                                             # the daily cap counts from the IST midnight
    start = db.day_start()
    for ts in (start - 5, start + 5, start + 10):
        c.execute("INSERT INTO messages(institute,channel,user_id,role,text,ts) VALUES('captest','website','u','user','hi',?)", (ts,))
assert db.count_user_messages_today("captest") == 2

# ---------- 5. new_demo makes private copies ----------
src = Path(tempfile.mkdtemp()); (src / "acme" / "history").mkdir(parents=True)
(src / "acme" / "config.json").write_text(json.dumps({"id": "acme", "name": "Acme", "owner_key_env": "K", "owner_phone": "91999", "alerts": {"email": "a@b.c"},
                                                      "whatsapp": {"provider": "meta"}, "meta_ids": ["1"], "website_handoff_message": "hi"}))
(src / "acme" / "knowledge.md").write_text(KB); (src / "acme" / "history" / "knowledge-0000000000000000001.md").write_text("old")
a, b = new_demo.make("acme", "Acme Patna!", root=src), new_demo.make("acme", root=src)
assert re.fullmatch(r"acmepatna-[a-z0-9]{8}", a) and re.fullmatch(r"acme-[a-z0-9]{8}", b) and a != b
cfg = json.loads((src / a / "config.json").read_text())
assert cfg["id"] == a and cfg["unofficial_demo"] is True and cfg["website_handoff_message"] == "hi"
assert not {"owner_key_env", "owner_phone", "alerts", "whatsapp", "meta_ids"} & set(cfg)         # a prospect demo never messages anyone
assert (src / a / "knowledge.md").exists() and not (src / a / "history").exists() and "owner_key_env" in json.loads((src / "acme" / "config.json").read_text())
assert registry.load_all(src)[a]["config"]["unofficial_demo"] is True
try:
    new_demo.make("missing", root=src); raise AssertionError("should have refused")
except SystemExit:
    pass

# ---------- 6. alert test command ----------
sent = []
notify.send_telegram = lambda token, chat, text, post=None: sent.append((token, chat, text)) or True
assert notify.send_alerts({"telegram_chat_id": "42", "telegram_token_env": "TG_TOKEN"}, "x") == {"telegram": True} and sent[-1][:2] == ("123:tok", "42")
assert notify.send_alerts({}, "x") == {}
sent.clear(); assert notify.send_test("official", root) == 0 and len(sent) == 1 and "test alert" in sent[0][2] and "Official" in sent[0][2]
notify.send_telegram = lambda *a, **k: False
assert notify.send_test("official", root) == 1                                   # configured but failing: not a silent success
os.environ.pop("TG_TOKEN"); assert notify.send_test("official", root) == 1       # token missing: reported as failure
assert notify.send_test("other", root) == 2 and notify.send_test("nope", root) == 2   # no alerts block / no such institute
print("viewer, privacy and export tests passed")
