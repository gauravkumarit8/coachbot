"""Wiring tests for app/main.py using stand-ins for FastAPI (no server, no network). Run: python -m tests.test_api"""
import asyncio, hashlib, hmac, json, logging, os, tempfile, types
from pathlib import Path

from tests import fastapi_stub
fastapi_stub.install()
os.environ.update(COACHBOT_DB=os.path.join(tempfile.mkdtemp(), "t.db"), LLM_PROVIDER="anthropic", DEMO_OWNER_KEY="owner-key-123456",
                  ADMIN_TOKEN="admin-token-123456", VERIFY_TOKEN="vtok", WA_KEY="wa-token", BSP_KEY="bsp-key", BSP_HOOK="hookkey123456")
for k in ("META_APP_SECRET", "TRUST_PROXY"):
    os.environ.pop(k, None)

from app import channels, db, limits, llm, main, notify, registry  # noqa: E402
from app.llm import Turn  # noqa: E402
from fastapi import BackgroundTasks, HTTPException  # noqa: E402

logging.disable(logging.CRITICAL)
KB = (Path(__file__).resolve().parent.parent / "institutes" / "demo" / "knowledge.md").read_text(encoding="utf-8")


class FakeLLM:
    reply = "Class 11-12 Science is Rs 45,000 per year."
    def complete(self, system, msgs, tools, max_tokens=600, allow_tools=True):
        return Turn("YES") if "message router" in system else Turn(self.reply)
    def extend(self, *a): pass
    def warm(self): pass
llm.get_llm = lambda: FakeLLM()

root = Path(tempfile.mkdtemp())
def make(iid, **cfg):
    d = root / iid; d.mkdir()
    (d / "config.json").write_text(json.dumps({"id": iid, "name": iid.title() + " Academy", **cfg})); (d / "knowledge.md").write_text(KB)
make("demo", whatsapp={"provider": "meta", "phone_number_id": "111", "api_key_env": "WA_KEY"}, meta_ids=["pg1"], owner_phone="919800000000",
     owner_key_env="DEMO_OWNER_KEY", alerts={"telegram_chat_id": "42"})
make("bspinst", whatsapp={"provider": "bsp", "send_url": "https://bsp.example/messages", "api_key_env": "BSP_KEY", "webhook_key_env": "BSP_HOOK"})
make("capinst", daily_message_cap=2)
main.reg = registry.Registry(root)


class Req:
    def __init__(self, headers=None, body=b"", host="1.2.3.4"):
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self._body, self.client = body, (types.SimpleNamespace(host=host) if host else None)
    async def body(self): return self._body
    async def json(self): return json.loads(self._body)

def code_of(fn, *a, **k):
    try:
        fn(*a, **k)
    except HTTPException as e:
        return e.status_code
    return 200
def run(coro): return asyncio.run(coro)
def chat(iid, sid, msg="fees?", host="1.2.3.4", headers=None): return main.web_chat(iid, main.ChatIn(session_id=sid, message=msg), Req(headers, host=host))


# 1. Basic pages and info
assert main.health()["institutes"] == 3 and "demo" not in str(main.health()["institutes"]) and "provider" in main.health()["llm"]   # a count: ids (private demo links) are never listed
info = main.public_info("demo")
assert info["name"] == "Demo Academy" and info["unofficial"] is False and "Which courses do you offer?" in info["suggestions"], info
assert code_of(main.public_info, "nope") == 404 and code_of(main.institute_shortcut, "nope") == 404
assert main.institute_shortcut("demo").url == "/demo?institute=demo" and "<html" in main.root().body

# 2. Website chat
out = chat("demo", "s1")
assert out == {"reply": FakeLLM.reply, "handoff": False}
assert code_of(chat, "nope", "s1") == 404

# 3. Abuse protection: the limit follows the visitor's ADDRESS, so rotating session ids does not help
main.LIMITER = limits.Limiter()
assert all(code_of(chat, "demo", f"rot{i}", host="9.9.9.9") == 200 for i in range(main.CHAT_IP_PER_MIN))
assert code_of(chat, "demo", "rot-new", host="9.9.9.9") == 429          # 21st message, brand-new session id, same address
assert code_of(chat, "demo", "other", host="8.8.8.8") == 200            # a different visitor is unaffected
main.LIMITER = limits.Limiter()
assert all(code_of(chat, "demo", "same-session", host=f"7.7.7.{i}") == 200 for i in range(15))
assert code_of(chat, "demo", "same-session", host="7.7.7.99") == 429    # one session id from many addresses is limited too
main.LIMITER = limits.Limiter()
os.environ["TRUST_PROXY"] = "1"                                         # behind a tunnel: all traffic arrives from 127.0.0.1
assert all(code_of(chat, "demo", f"p{i}", host="127.0.0.1", headers={"cf-connecting-ip": f"5.5.5.{i % 3}"}) == 200 for i in range(30))  # 3 visitors, 10 msgs each
assert code_of(chat, "demo", "pz", host="127.0.0.1", headers={"cf-connecting-ip": "5.5.5.0"}) == 200
os.environ.pop("TRUST_PROXY")
main.LIMITER = limits.Limiter()
assert code_of(chat, "demo", "forged", host="127.0.0.1", headers={"cf-connecting-ip": "1.1.1.1"}) == 200   # header ignored without TRUST_PROXY

# 4. Daily cap (per-institute override), alert only once per day
alerts = []; real_notify = main.notify_owner; main.notify_owner = lambda iid, text: alerts.append((iid, text))
main.LIMITER = limits.Limiter()
assert chat("capinst", "c1")["reply"] == FakeLLM.reply and chat("capinst", "c2")["reply"] == FakeLLM.reply
assert chat("capinst", "c3") == {"reply": main.CAP_REPLY, "handoff": False} and chat("capinst", "c4")["reply"] == main.CAP_REPLY
assert len(alerts) == 1 and alerts[0][0] == "capinst" and "daily limit of 2" in alerts[0][1]
assert chat("demo", "c5")["reply"] == FakeLLM.reply                    # other institutes keep working
main.notify_owner = real_notify

# 5. Owner alerts: every configured channel, and NO phone numbers in the server log
logging.disable(logging.NOTSET); lines = []; logging.getLogger("coachbot").propagate = False   # capture quietly
h = logging.Handler(); h.emit = lambda r: lines.append(r.getMessage()); logging.getLogger("coachbot").addHandler(h)
got = {"alerts": [], "wa": []}
real = (channels.run_in_background, notify.send_alerts, channels.send_whatsapp)
channels.run_in_background = lambda fn, *a: fn(*a)
notify.send_alerts = lambda a, t: got["alerts"].append((a, t))
channels.send_whatsapp = lambda wa, to, t: got["wa"].append((to, t))
main.notify_owner("demo", "New lead for Demo Academy\nName: Ravi\nPhone: +91 99900 01111")
main.notify_owner("demo", "Bot error. Latest: website s1: call me on 9990001111 please")
channels.run_in_background, notify.send_alerts, channels.send_whatsapp = real
logging.getLogger("coachbot").removeHandler(h); logging.getLogger("coachbot").propagate = True; logging.disable(logging.CRITICAL)
assert got["alerts"][0][0] == {"telegram_chat_id": "42"} and "99900 01111" in got["alerts"][0][1]    # the owner DOES get the details
assert got["wa"][0][0] == "919800000000"
assert lines and not any("9990001111" in l or "99900 01111" in l or "Ravi" in l for l in lines), lines   # the log does not

# 6. Owner API: key required, leads and unanswered questions, saving details
KEY = "owner-key-123456"
assert code_of(main.owner_get, "demo", Req(host="2.2.2.2"), "wrong") == 403 and code_of(main.owner_get, "demo", Req(host="2.2.2.2"), None) == 403
assert code_of(main.owner_get, "bspinst", Req(host="2.2.2.2"), KEY) == 403 and code_of(main.owner_get, "nope", Req(host="2.2.2.2"), KEY) == 403
assert main.owner_get("demo", Req(host="2.2.2.2"), KEY)["name"] == "Demo Academy"
db.save_lead("demo", "website", "u1", name="Ravi", phone="+91 99900 01111", exam_or_class="JEE", city="Patna")
db.save_lead("capinst", "website", "u2", name="Other", phone="8888888888")
leads = main.owner_leads("demo", Req(host="2.2.2.2"), KEY)
assert [l["name"] for l in leads] == ["Ravi"] and leads[0]["phone"] == "+91 99900 01111" and leads[0]["when"]      # only THEIR leads
for q in ("Is there parking?", "is there parking?  ", "My number is 9990001111, is there food?"): db.add_unanswered("demo", q)
un = main.owner_unanswered("demo", Req(host="2.2.2.2"), KEY)
assert un[0]["count"] == 2 and un[0]["question"].lower().startswith("is there parking") and any("[number]" in u["question"] and "9990001111" not in u["question"] for u in un)
assert main.owner_unanswered_clear("demo", Req(host="2.2.2.2"), KEY) == {"ok": True} and main.owner_unanswered("demo", Req(host="2.2.2.2"), KEY) == []
assert main.owner_put("demo", main.KnowledgeIn(text=KB.replace("45,000", "47,000")), Req(host="2.2.2.2"), KEY)["ok"]
assert "47,000" in main.reg.get("demo")["knowledge"] and main.owner_undo("demo", Req(host="2.2.2.2"), KEY)["ok"] and "45,000" in main.reg.get("demo")["knowledge"]
assert code_of(main.owner_put, "demo", main.KnowledgeIn(text="short"), Req(host="2.2.2.2"), KEY) == 400
main.LIMITER = limits.Limiter()
assert [code_of(main.owner_get, "demo", Req(host="3.3.3.3"), "bad") for _ in range(31)][-1] == 429       # guessing keys is throttled

# 7. WhatsApp (Meta direct): verification, signature, answer, duplicate ignored, non-text
assert main.wa_verify("subscribe", "vtok", "abc").body == "abc" and code_of(main.wa_verify, "subscribe", "bad", "abc") == 403
def wa_payload(pnid, mid, typ="text", text="fees?"):
    m = {"id": mid, "from": "919900000001", "type": typ}
    if typ == "text": m["text"] = {"body": text}
    return json.dumps({"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": pnid}, "messages": [m]}}]}]}).encode()
sent = []; channels.send_whatsapp = lambda wa, to, t: sent.append((wa["provider"], to, t)) or True
assert run(main.wa_in(Req(body=wa_payload("111", "wamid.1")), BackgroundTasks())) == {"ok": True}
assert sent == [("meta", "919900000001", FakeLLM.reply)]
run(main.wa_in(Req(body=wa_payload("111", "wamid.1")), BackgroundTasks()));  assert len(sent) == 1                  # Meta retry: ignored
run(main.wa_in(Req(body=wa_payload("111", "wamid.2", typ="audio")), BackgroundTasks())); assert "type your question" in sent[-1][2]
run(main.wa_in(Req(body=wa_payload("999", "wamid.3")), BackgroundTasks()));  assert len(sent) == 2                  # unknown number: ignored
os.environ["META_APP_SECRET"] = "s3cret"; body = wa_payload("111", "wamid.4")
good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
assert code_of(lambda: run(main.wa_in(Req({"x-hub-signature-256": "sha256=bad"}, body), BackgroundTasks()))) == 403
assert code_of(lambda: run(main.wa_in(Req(body=body), BackgroundTasks()))) == 403                                   # unsigned
run(main.wa_in(Req({"x-hub-signature-256": good}, body), BackgroundTasks())); assert len(sent) == 3   # reply, audio note, signed message
os.environ.pop("META_APP_SECRET")

# 8. WhatsApp through a BSP: per-institute secret in the URL
bsp_body = wa_payload("whatever", "bsp.1")
assert code_of(lambda: run(main.bsp_in("bspinst", Req(body=bsp_body), BackgroundTasks(), key="wrong"))) == 403
assert code_of(lambda: run(main.bsp_in("demo", Req(body=bsp_body), BackgroundTasks(), key="hookkey123456"))) == 403   # demo is not a BSP institute
assert code_of(lambda: run(main.bsp_in("nope", Req(body=bsp_body), BackgroundTasks(), key="hookkey123456"))) == 403
n = len(sent); assert run(main.bsp_in("bspinst", Req(body=bsp_body), BackgroundTasks(), key="hookkey123456")) == {"ok": True}
assert sent[n] == ("bsp", "919900000001", FakeLLM.reply)

# 9. Instagram / Facebook
msent = []; channels.send_meta = lambda to, t, env="META_PAGE_TOKEN": msent.append((to, t)) or True
meta = lambda mid, ob="instagram": json.dumps({"object": ob, "entry": [{"id": "pg1", "messaging": [{"sender": {"id": "u9"}, "message": {"mid": mid, "text": "fees?"}}]}]}).encode()
assert main.meta_verify("subscribe", "vtok", "xyz").body == "xyz"
run(main.meta_in(Req(body=meta("m1")), BackgroundTasks())); run(main.meta_in(Req(body=meta("m1")), BackgroundTasks()))
assert msent == [("u9", FakeLLM.reply)]                                                                             # answered once
echo = json.dumps({"object": "page", "entry": [{"id": "pg1", "messaging": [{"sender": {"id": "u9"}, "message": {"mid": "m2", "text": "x", "is_echo": True}}]}]}).encode()
run(main.meta_in(Req(body=echo), BackgroundTasks())); assert len(msent) == 1                                          # our own echo: ignored

# 10. Admin
assert code_of(main.leads, "demo", "wrong") == 403 and [l["name"] for l in main.leads("demo", "admin-token-123456")] == ["Ravi"]
admin = os.environ.pop("ADMIN_TOKEN"); assert code_of(main.leads, "demo", "x") == 503; os.environ["ADMIN_TOKEN"] = admin
print("api wiring tests passed")

# CORS: every site by default, or exactly the websites listed in CORS_ORIGINS
os.environ.pop("CORS_ORIGINS", None); assert main._cors_origins() == ["*"]
os.environ["CORS_ORIGINS"] = " https://a.com/ , https://www.b.in,, "; assert main._cors_origins() == ["https://a.com", "https://www.b.in"]
os.environ["CORS_ORIGINS"] = "*"; assert main._cors_origins() == ["*"]
os.environ.pop("CORS_ORIGINS")
