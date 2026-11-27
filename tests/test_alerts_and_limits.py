"""Offline tests: limiter, Telegram/email alerts, unanswered-question tracking. Run: python -m tests.test_alerts_and_limits"""
import logging, os, tempfile, time, types

os.environ["COACHBOT_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from app import brain, db, limits, notify  # noqa: E402
from app.llm import Turn  # noqa: E402

db.init()

# ---------- Limiter ----------
now = [1000.0]; lim = limits.Limiter(clock=lambda: now[0])
assert [lim.allow("a", 3, 60) for _ in range(4)] == [True, True, True, False]       # 4th within the window is refused
assert lim.allow("b", 3, 60)                                                         # other keys are independent
now[0] += 61; assert lim.allow("a", 3, 60)                                           # window passed: allowed again
now[0] += 1; [lim.allow(f"k{i}", 1, 1) for i in range(6000)]; now[0] += 5; lim.allow("z", 1, 1)
assert len(lim._hits) < 100                                                          # idle keys are forgotten (memory stays small)

# ---------- client_ip ----------
H = {"cf-connecting-ip": "5.5.5.5", "x-forwarded-for": "6.6.6.6, 10.0.0.1"}
assert limits.client_ip(H, "127.0.0.1", trust_proxy=False) == "127.0.0.1"           # forged headers ignored by default
assert limits.client_ip(H, "127.0.0.1", trust_proxy=True) == "5.5.5.5"
XF = {"x-forwarded-for": "9.9.9.9, 6.6.6.6, 10.0.0.1"}                              # 9.9.9.9 was typed by the visitor; the proxies appended the rest
assert limits.client_ip(XF, "127.0.0.1", trust_proxy=True) == "10.0.0.1"             # counted from the right: one proxy of ours
assert limits.client_ip(XF, "127.0.0.1", trust_proxy=True, hops=2) == "6.6.6.6" and limits.client_ip(XF, "127.0.0.1", trust_proxy="xff", hops=2) == "6.6.6.6"
assert limits.client_ip(XF, "127.0.0.1", trust_proxy=True, hops=9) == "9.9.9.9"      # more hops than entries: nearest entry
assert limits.client_ip({"x-forwarded-for": "6.6.6.6"}, "127.0.0.1", trust_proxy=True) == "6.6.6.6"
assert limits.client_ip(H, "127.0.0.1", trust_proxy="xff") == "10.0.0.1"              # xff mode ignores CF-Connecting-IP (a visitor could forge it behind nginx)
assert limits.client_ip({"cf-connecting-ip": "5.5.5.5"}, "127.0.0.1", trust_proxy="xff") == "127.0.0.1"
os.environ["TRUST_PROXY"] = "xff"; os.environ["PROXY_HOPS"] = "2"; assert limits.client_ip(XF, "127.0.0.1") == "6.6.6.6"
os.environ["PROXY_HOPS"] = "junk"; assert limits.client_ip(XF, "127.0.0.1") == "10.0.0.1"; os.environ.pop("PROXY_HOPS"); os.environ.pop("TRUST_PROXY")
assert limits.client_ip({}, "127.0.0.1", trust_proxy=True) == "127.0.0.1" and limits.client_ip({}, None, trust_proxy=False) == "?"

# ---------- Telegram ----------
class Resp:
    def __init__(self, code, text=""): self.status_code, self.text = code, text
calls = []
def ok_post(url, payload, timeout): calls.append((url, payload)); return Resp(200)
assert notify.send_telegram("123:SECRETTOKEN", "42", "hello", post=ok_post)
assert calls[0][0] == "https://api.telegram.org/bot123:SECRETTOKEN/sendMessage" and calls[0][1] == {"chat_id": "42", "text": "hello"}
notify.send_telegram("t", "42", "x" * 9000, post=ok_post); assert len(calls[-1][1]["text"]) == 4000
logs = []; h = logging.Handler(); h.emit = lambda r: logs.append(r.getMessage()); logging.getLogger("coachbot").addHandler(h)
def boom(url, payload, timeout): raise ConnectionError(f"cannot reach {url}")
assert notify.send_telegram("123:SECRETTOKEN", "42", "hi", post=boom) is False
assert notify.send_telegram("123:SECRETTOKEN", "42", "hi", post=lambda u, p, t: Resp(401, '{"description":"Unauthorized"}')) is False
assert logs and not any("SECRETTOKEN" in l for l in logs), logs                      # the bot token never reaches the log

# ---------- Email ----------
sent = []
class FakeSMTP:
    def __init__(self, host, port, timeout=0): self.kind = type(self).__name__; sent.append(("connect", self.kind, host, port))
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self): sent.append(("starttls",))
    def login(self, u, p): sent.append(("login", u, p))
    def send_message(self, m): sent.append(("send", m["To"], m["Subject"], m["From"], m.get_content()))
class FakeSSL(FakeSMTP): pass
notify.smtplib = types.SimpleNamespace(SMTP=FakeSMTP, SMTP_SSL=FakeSSL)
ENV = {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "bot@example.com", "SMTP_PASSWORD": "pw"}
assert notify.send_email("owner@x.com", "New lead", "Name: Ravi", env=ENV)
assert [x[0] for x in sent] == ["connect", "starttls", "login", "send"] and sent[0][3] == 587
assert sent[-1][1:4] == ("owner@x.com", "New lead", "bot@example.com") and "Name: Ravi" in sent[-1][4]
sent.clear(); notify.send_email("o@x.com", "s", "b", env={**ENV, "SMTP_PORT": "465", "SMTP_FROM": "alerts@x.com"})
assert sent[0][1] == "FakeSSL" and "starttls" not in [x[0] for x in sent] and sent[-1][3] == "alerts@x.com"
sent.clear(); assert notify.send_email("o@x.com", "s", "b", env={"SMTP_HOST": "h"}) is False and sent == []   # not configured: nothing sent
class BadSMTP(FakeSMTP):
    def login(self, u, p): raise RuntimeError("auth failed for pw")
notify.smtplib = types.SimpleNamespace(SMTP=BadSMTP, SMTP_SSL=BadSMTP)
assert notify.send_email("o@x.com", "s", "b", env=ENV) is False and not any("pw" in l.replace("password", "") and "auth failed" in l for l in logs)

# ---------- send_alerts routing ----------
routed = []
notify.send_telegram = lambda tok, chat, text, post=None: routed.append(("tg", tok, chat, text)) or True
notify.send_email = lambda to, subj, body, env=None: routed.append(("mail", to, subj, body)) or True
os.environ["MY_TG"] = "tok123"; os.environ.pop("TELEGRAM_BOT_TOKEN", None)
notify.send_alerts({"telegram_chat_id": 42, "telegram_token_env": "MY_TG", "email": "o@x.com"}, "New lead for X\nName: Ravi")
assert routed == [("tg", "tok123", "42", "New lead for X\nName: Ravi"), ("mail", "o@x.com", "New lead for X", "New lead for X\nName: Ravi")]
routed.clear(); notify.send_alerts({"telegram_chat_id": "42"}, "x")                   # no token in the environment: skipped, not crashed
assert routed == []; notify.send_alerts({}, "x"); assert routed == []
logging.getLogger("coachbot").removeHandler(h); logging.disable(logging.CRITICAL)

# ---------- Telegram chat id helper ----------
upd = {"result": [{"message": {"chat": {"id": 111, "first_name": "Ravi", "last_name": "K"}}}, {"message": {"chat": {"id": 111, "first_name": "Ravi"}}},
                  {"message": {"chat": {"id": -222, "title": "Staff group"}}}, {"edited_message": {}}]}
assert notify.parse_chat_ids(upd) == [(111, "Ravi K"), (-222, "Staff group")]

# ---------- Unanswered questions (database) ----------
db.add_unanswered("demo", "Is there parking?"); db.add_unanswered("demo", "  is there parking?  "); db.add_unanswered("demo", "Hostel food?")
db.add_unanswered("demo", "call me on +91 99900 01111 about food"); db.add_unanswered("other", "Another institute's question"); db.add_unanswered("demo", "   ")
rows = db.list_unanswered("demo")
assert rows[0]["n"] == 2 and rows[0]["question"].lower().strip() == "is there parking?"                  # grouped, most asked first
assert len(rows) == 3 and any(r["question"] == "call me on [number] about food" for r in rows)            # numbers masked, blanks ignored
assert not any("9990001111" in r["question"].replace(" ", "") for r in rows) and [r["question"] for r in db.list_unanswered("other")] == ["Another institute's question"]
db.clear_unanswered("demo"); assert db.list_unanswered("demo") == [] and len(db.list_unanswered("other")) == 1   # clears only that institute

# ---------- Daily message count ----------
for t, label in ((time.time(), "today"), (time.time() - 3 * 86400, "old")):
    with db.conn() as c:
        c.execute("INSERT INTO messages(institute,channel,user_id,role,text,ts) VALUES('cnt','website','u','user',?,?)", (label, t))
with db.conn() as c:
    c.execute("INSERT INTO messages(institute,channel,user_id,role,text,ts) VALUES('cnt','website','u','assistant','bot reply',?)", (time.time(),))
assert db.count_user_messages_today("cnt") == 1                                                          # not old messages, not bot replies

# ---------- NOINFO marker: strip it, remember the question ----------
INST = brain.load_institutes()["demo"]
class Fake:
    def __init__(self, *answers): self.answers = list(answers)
    def complete(self, system, msgs, tools, max_tokens=600, allow_tools=True):
        return Turn("YES") if "message router" in system else self.answers.pop(0)
    def extend(self, *a): pass
def ask(uid, msg, answer):
    return brain.run_turn(INST, "website", uid, msg, None, Fake(Turn(answer)))["reply"]
r = ask("n1", "do you have parking?", "[[NOINFO]] I don't have that detail. Please call the institute.")
assert r == "I don't have that detail. Please call the institute." and "NOINFO" not in r
assert [x["question"] for x in db.list_unanswered("demo")] == ["do you have parking?"]
assert "NOINFO" not in ask("n2", "is there hostel food?", "I don't have that detail [[ noinfo ]] sorry.")      # any spelling/position is stripped
assert ask("n3", "what is the fee for class 11 science?", "Class 11-12 Science is Rs 45,000 per year.").startswith("Class 11-12")
ask("n4", "does it have a canteen?", "That is not listed in my details, please call us.")                     # no marker, but says so
ask("n5", "hello", "Hi! How can I help?")
qs = [x["question"] for x in db.list_unanswered("demo")]
assert set(qs) == {"do you have parking?", "is there hostel food?", "does it have a canteen?"}, qs              # normal answers are NOT recorded
brain.run_turn(INST, "website", "n6", "2+4", None, Fake()); assert len(db.list_unanswered("demo")) == 3      # off-topic refusals are not recorded
assert brain.run_turn(INST, "website", "n7", "fees?", None, Fake(Turn("[[NOINFO]]")))["reply"] == brain.FALLBACK  # a bare marker never shows
assert "[[NOINFO]]" in brain.SYSTEM and "removed before the user sees it" in brain.SYSTEM
print("alerts and limits tests passed")
