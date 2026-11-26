import hmac
import json
import logging
import os
import re
import time
from urllib.parse import quote
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel

from dotenv import load_dotenv

load_dotenv()  # read .env before the modules below read their settings

from . import brain, channels, company, db, export, jobs, limits, llm, notify, registry, suggestions, weekly  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("coachbot")
STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="CoachBot")
# MVP: open CORS so any client website can embed the widget. Restrict to client domains later.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
db.init()

def _warm_llm():
    llm.get_llm().warm()


channels.run_in_background(_warm_llm)  # first customer message shouldn't pay for the cold connection
reg = registry.Registry()  # reloads institutes/*/config.json + knowledge.md automatically when they change
WEB_HANDOFF = "Our team has been notified and will contact you shortly."


def notify_owner(inst_id: str, text: str):
    """Alert the owner on WhatsApp. NOTE: outside the 24h window Meta requires an approved
    template message, so for production send a template here (see README)."""
    inst = reg.get(inst_id)
    if not inst:
        return
    cfg = inst["config"]
    first = text.splitlines()[0] if text else ""
    log.info("OWNER ALERT [%s]: %s", inst_id, re.sub(r"\+?\d[\d\s-]{6,}\d", "[number]", first)[:80])  # no phone numbers in logs
    if cfg.get("alerts"):  # Telegram / email: free, instant, no Meta approval needed
        channels.run_in_background(notify.send_alerts, cfg["alerts"], text)
    wa = channels.wa_settings(cfg)
    placeholder = any("REPLACE" in str(v) or "XXXX" in str(v)
                      for v in (cfg.get("owner_phone"), wa.get("phone_number_id"), wa.get("send_url")))
    if cfg.get("owner_phone") and cfg.get("whatsapp") and not placeholder:
        channels.run_in_background(channels.send_whatsapp, wa, cfg["owner_phone"], text)
    elif placeholder:
        log.info("(owner alert not sent: fill in owner_phone and WhatsApp settings in config.json)")


# ---------- WhatsApp ----------
@app.get("/webhook/whatsapp")
def wa_verify(mode: str = Query(None, alias="hub.mode"), token: str = Query(None, alias="hub.verify_token"),
              challenge: str = Query(None, alias="hub.challenge")):
    if mode == "subscribe" and token and token == os.getenv("VERIFY_TOKEN"):
        return PlainTextResponse(challenge)
    raise HTTPException(403)


@app.post("/webhook/whatsapp")
async def wa_in(request: Request, bg: BackgroundTasks):
    body = await request.body()
    if not channels.verify_signature(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(403)
    for pnid, m in channels.parse_whatsapp(json.loads(body)):
        inst = reg.by_wa(pnid)
        if inst:
            bg.add_task(handle_whatsapp, inst, m)
    return {"ok": True}  # always 200 fast, or Meta retries


@app.post("/webhook/bsp/{institute_id}")
async def bsp_in(institute_id: str, request: Request, bg: BackgroundTasks, key: str = ""):
    """Inbound WhatsApp from an institute's BSP. Set the BSP's webhook to
    https://YOUR-URL/webhook/bsp/<institute_id>?key=<secret>  (secret = env var named in config)."""
    inst = reg.get(institute_id)
    wa = channels.wa_settings(inst["config"]) if inst else {}
    expected = os.getenv(wa.get("webhook_key_env", ""), "") if wa.get("webhook_key_env") else ""
    if not inst or wa.get("provider") != "bsp" or not expected or not hmac.compare_digest(key.encode(), expected.encode()):
        raise HTTPException(403)
    for _, m in channels.parse_whatsapp(await request.json()):
        bg.add_task(handle_whatsapp, inst, m)
    return {"ok": True}


def handle_whatsapp(inst, m):
    if not db.first_time_seen(m["id"]):
        return
    wa, sender = channels.wa_settings(inst["config"]), m["from"]
    if m.get("type") != "text":
        channels.send_whatsapp(wa, sender, "Please type your question and I'll help you. "
                                           "(Voice notes and images aren't supported yet.)")
        return
    out = brain.run_turn(inst, "whatsapp", sender, m["text"]["body"], notify=notify_owner)
    if out["reply"]:
        channels.send_whatsapp(wa, sender, out["reply"])


# ---------- Instagram + Facebook (Meta Messenger platform) ----------
@app.get("/webhook/meta")
def meta_verify(mode: str = Query(None, alias="hub.mode"), token: str = Query(None, alias="hub.verify_token"),
                challenge: str = Query(None, alias="hub.challenge")):
    return wa_verify(mode, token, challenge)


@app.post("/webhook/meta")
async def meta_in(request: Request, bg: BackgroundTasks):
    body = await request.body()
    if not channels.verify_signature(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(403)
    data = json.loads(body)
    channel = "instagram" if data.get("object") == "instagram" else "facebook"
    for entry in data.get("entry", []):
        inst = reg.by_meta(entry.get("id"))
        for ev in entry.get("messaging", []) if inst else []:
            msg = ev.get("message") or {}
            if msg.get("is_echo"):
                continue  # our own outgoing message
            bg.add_task(handle_meta, inst, channel, ev["sender"]["id"], msg)
    return {"ok": True}


def handle_meta(inst, channel, sender, msg):
    if msg.get("mid") and not db.first_time_seen(msg["mid"]):
        return
    if not msg.get("text"):
        channels.send_meta(sender, "Please type your question and I'll help you.", inst["config"].get("meta_token_env", "META_PAGE_TOKEN"))
        return
    out = brain.run_turn(inst, channel, sender, msg["text"], notify=notify_owner)
    if out["reply"]:
        channels.send_meta(sender, out["reply"], inst["config"].get("meta_token_env", "META_PAGE_TOKEN"))


# ---------- Website widget ----------
class ChatIn(BaseModel):
    session_id: str
    message: str


LIMITER = limits.Limiter()
CHAT_IP_PER_MIN = int(os.getenv("CHAT_IP_PER_MIN", "20"))   # messages per minute from one visitor address
CHAT_DAILY_CAP = int(os.getenv("CHAT_DAILY_CAP", "2000"))   # customer messages per institute per day (0 = no cap)
CAP_REPLY = "This assistant has reached its daily limit. Please contact the institute directly."
_cap_alerted: set = set()


def _rate_ok(key: str, limit=15, window=60) -> bool:
    """Public endpoint = abuse risk (costs money). Sliding-window limit per key."""
    return LIMITER.allow(key, limit, window)


@app.post("/chat/{institute_id}")
def web_chat(institute_id: str, body: ChatIn, request: Request):
    inst = reg.get(institute_id)
    if not inst:
        raise HTTPException(404)
    ip = limits.client_ip(request.headers, request.client.host if request.client else None)
    # keyed by the visitor's address, not only by the session id, which anyone can change on every request
    if not _rate_ok(f"ip:{ip}", CHAT_IP_PER_MIN) or not _rate_ok(body.session_id[:64]):
        raise HTTPException(429, "Too many messages, please wait a moment.")
    cap = inst["config"].get("daily_message_cap", CHAT_DAILY_CAP)
    if cap and db.count_user_messages_today(institute_id) >= cap:
        day = db.today_str()
        if (institute_id, day) not in _cap_alerted:
            _cap_alerted.add((institute_id, day))
            notify_owner(institute_id, f"The chat assistant for {inst['config']['name']} reached its daily limit of {cap} messages. "
                                       "Visitors are asked to contact you directly. Raise daily_message_cap in config.json if this is real traffic.")
        return {"reply": CAP_REPLY, "handoff": False}
    out = brain.run_turn(inst, "website", body.session_id[:64], body.message[:1000], notify=notify_owner)
    res = {"reply": out["reply"] or inst["config"].get("website_handoff_message", WEB_HANDOFF), "handoff": out["handoff"]}
    if out.get("actions"):
        res["actions"] = out["actions"]
    return res


@app.get("/", include_in_schema=False)
def root():
    """Our company home page (settings in site.json). The demo chat is at /demo."""
    return HTMLResponse(company.render("site.html"))


@app.get("/privacy", include_in_schema=False)
def privacy():
    return HTMLResponse(company.render("privacy.html"))


@app.get("/robots.txt", include_in_schema=False)
def robots():
    return PlainTextResponse(company.robots())  # home + privacy may be indexed; demos, owner pages, admin and APIs may not


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request):
    return PlainTextResponse(company.sitemap(str(getattr(request, "base_url", "") or "")), media_type="application/xml")


class ContactIn(BaseModel):
    name: str
    institute: str = ""
    city: str = ""
    phone: str = ""
    email: str = ""
    message: str = ""
    consent: bool = False
    website: str = ""  # hidden field: real visitors leave it empty, simple bots fill it in


@app.post("/api/contact")
def contact(body: ContactIn, request: Request):
    """Pilot enquiry from our home page: saved, and sent to us as an alert (alerts in site.json)."""
    ip = limits.client_ip(request.headers, request.client.host if request.client else None)
    if not _rate_ok(f"contact:{ip}", 5, 3600):
        raise HTTPException(429, "Too many attempts. Please try again later.")
    if body.website.strip():
        return {"ok": True}  # a bot: pretend it worked, store nothing
    fields, problem = company.clean_contact(body)
    if problem:
        raise HTTPException(400, problem)
    db.save_inquiry(**fields)
    log.info("NEW WEBSITE ENQUIRY: %s, %s", fields["name"], fields["institute"] or "-")
    alerts = company.load().get("alerts")
    if alerts:
        channels.run_in_background(notify.send_alerts, alerts, (
            f"New {company.load()['product_name']} enquiry\nName: {fields['name']}\nInstitute: {fields['institute'] or '-'}\n"
            f"City: {fields['city'] or '-'}\nPhone: {fields['phone'] or '-'}\nEmail: {fields['email'] or '-'}\nMessage: {fields['message'] or '-'}"))
    return {"ok": True}


@app.get("/widget.js")
def widget():
    return FileResponse(STATIC / "widget.js", media_type="application/javascript")


@app.get("/demo")
def demo():
    return FileResponse(STATIC / "demo.html")


@app.get("/api/public/{institute_id}")
def public_info(institute_id: str):
    """What the demo page needs to know. Public by design: the chat widget is public anyway."""
    inst = reg.get(institute_id)
    if not inst:
        raise HTTPException(404)
    cfg = inst["config"]
    return {"name": cfg["name"], "unofficial": bool(cfg.get("unofficial_demo")),
            "suggestions": suggestions.suggest(inst["knowledge"], 6, cfg.get("suggested_questions"))}


# ---------- Owner page: each institute edits its own fees/batches ----------
def _owner(institute_id: str, request: Request, key: str | None):
    ip = limits.client_ip(request.headers, request.client.host if request.client else None)
    if not _rate_ok(f"owner:{ip}:{institute_id}", limit=30):
        raise HTTPException(429)
    inst = reg.get(institute_id)
    if not inst or not registry.check_owner_key(inst["config"], key):
        raise HTTPException(403)  # same answer for "no such institute" and "wrong key"
    return inst


@app.get("/owner/{institute_id}", include_in_schema=False)
def owner_page(institute_id: str):
    return FileResponse(STATIC / "owner.html")


@app.get("/api/owner/{institute_id}/knowledge")
def owner_get(institute_id: str, request: Request, x_owner_key: str = Header(None)):
    inst = _owner(institute_id, request, x_owner_key)
    return {"name": inst["config"]["name"], "text": inst["knowledge"], "max_chars": registry.MAX_KNOWLEDGE_CHARS}


class KnowledgeIn(BaseModel):
    text: str


@app.put("/api/owner/{institute_id}/knowledge")
def owner_put(institute_id: str, body: KnowledgeIn, request: Request, x_owner_key: str = Header(None)):
    _owner(institute_id, request, x_owner_key)
    try:
        return {"ok": True, "chars": reg.save_knowledge(institute_id, body.text)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/owner/{institute_id}/undo")
def owner_undo(institute_id: str, request: Request, x_owner_key: str = Header(None)):
    _owner(institute_id, request, x_owner_key)
    try:
        return {"ok": True, "chars": reg.undo_knowledge(institute_id)}
    except ValueError as e:
        raise HTTPException(400, str(e))


def _when(ts) -> str:
    return db.fmt_time(ts)  # in the owners' time zone (IST by default), not the server's


@app.get("/api/owner/{institute_id}/leads")
def owner_leads(institute_id: str, request: Request, x_owner_key: str = Header(None)):
    _owner(institute_id, request, x_owner_key)
    return [{"id": l["id"], "when": _when(l["ts"]), "name": l["name"], "phone": l["phone"], "exam_or_class": l["exam_or_class"],
             "city": l["city"], "interest": l["interest"], "demo_time": l["demo_time"], "channel": l["channel"],
             "status": l.get("status") or "new", "note": l.get("note") or ""}
            for l in db.list_leads(institute_id, 200)]


class LeadStatusIn(BaseModel):
    status: str
    note: str | None = None


@app.post("/api/owner/{institute_id}/leads/{lead_id}")
def owner_lead_status(institute_id: str, lead_id: int, body: LeadStatusIn, request: Request, x_owner_key: str = Header(None)):
    """The owner marks a lead New / Called / Demo booked / Joined / Not interested, with an optional short note."""
    _owner(institute_id, request, x_owner_key)
    if body.status not in db.LEAD_STATUSES:
        raise HTTPException(400, "Unknown status.")
    if not db.set_lead_status(institute_id, lead_id, body.status, body.note):
        raise HTTPException(404)
    return {"ok": True}


@app.get("/api/owner/{institute_id}/summary")
def owner_summary(institute_id: str, request: Request, x_owner_key: str = Header(None)):
    """This week's summary, the same text that is sent on Mondays."""
    inst = _owner(institute_id, request, x_owner_key)
    return {"text": weekly.build(inst)}


@app.get("/api/owner/{institute_id}/leads.csv")
def owner_leads_csv(institute_id: str, request: Request, x_owner_key: str = Header(None)):
    _owner(institute_id, request, x_owner_key)
    return PlainTextResponse(export.leads_csv(db.list_leads(institute_id, 5000)), media_type="text/csv; charset=utf-8")


def _chat_list(institute_id: str):
    return [{"ref": c["ref"], "channel": c["channel"], "who": c["who"], "started": _when(c["started"]), "last": _when(c["last"]),
             "messages": c["messages"], "first_question": c["first_question"], "lead": c["lead"]}
            for c in db.list_conversations(institute_id)]


def _chat_one(institute_id: str, ref: int):
    conv = db.get_conversation(institute_id, ref)
    if not conv:
        raise HTTPException(404)
    return {"channel": conv["channel"], "who": conv["who"],
            "messages": [{"role": m["role"], "text": m["text"], "when": _when(m["ts"])} for m in conv["messages"]]}


@app.get("/api/owner/{institute_id}/chats")
def owner_chats(institute_id: str, request: Request, x_owner_key: str = Header(None)):
    _owner(institute_id, request, x_owner_key)
    return _chat_list(institute_id)


@app.get("/api/owner/{institute_id}/chats/{ref}")
def owner_chat(institute_id: str, ref: int, request: Request, x_owner_key: str = Header(None)):
    _owner(institute_id, request, x_owner_key)
    return _chat_one(institute_id, ref)


@app.get("/api/owner/{institute_id}/unanswered")
def owner_unanswered(institute_id: str, request: Request, x_owner_key: str = Header(None)):
    _owner(institute_id, request, x_owner_key)
    return [{"question": r["question"], "count": r["n"], "last": _when(r["last"])} for r in db.list_unanswered(institute_id)]


@app.post("/api/owner/{institute_id}/unanswered/clear")
def owner_unanswered_clear(institute_id: str, request: Request, x_owner_key: str = Header(None)):
    _owner(institute_id, request, x_owner_key)
    db.clear_unanswered(institute_id)
    return {"ok": True}


# ---------- Admin (protect with ADMIN_TOKEN) ----------
def _admin(token):
    if not os.getenv("ADMIN_TOKEN"):
        raise HTTPException(503, "Set ADMIN_TOKEN first")
    if token != os.getenv("ADMIN_TOKEN"):
        raise HTTPException(403)


@app.get("/admin/leads/{institute_id}")
def leads(institute_id: str, x_admin_token: str = Header(None)):
    _admin(x_admin_token)
    return db.list_leads(institute_id)


@app.get("/admin/leads/{institute_id}/csv")
def leads_csv(institute_id: str, x_admin_token: str = Header(None)):
    _admin(x_admin_token)
    return PlainTextResponse(export.leads_csv(db.list_leads(institute_id, 5000)), media_type="text/csv; charset=utf-8")


@app.get("/admin/inquiries")
def admin_inquiries(x_admin_token: str = Header(None)):
    """Pilot enquiries from our home page."""
    _admin(x_admin_token)
    return [{**i, "when": _when(i["ts"])} for i in db.list_inquiries()]


@app.get("/admin/chats/{institute_id}")
def admin_chats(institute_id: str, x_admin_token: str = Header(None)):
    """Review real conversations (also for demo institutes, which have no owner page). Phone numbers/session ids are masked."""
    _admin(x_admin_token)
    return _chat_list(institute_id)


@app.get("/admin/chats/{institute_id}/{ref}")
def admin_chat(institute_id: str, ref: int, x_admin_token: str = Header(None)):
    _admin(x_admin_token)
    return _chat_one(institute_id, ref)


class Resume(BaseModel):
    institute: str
    channel: str
    user_id: str


@app.post("/admin/resume")
def resume(body: Resume, x_admin_token: str = Header(None)):
    """Give a chat back to the bot after staff has finished helping."""
    _admin(x_admin_token)
    db.set_handoff(body.institute, body.channel, body.user_id, active=False)
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True, "institutes": len(reg.all()), "llm": llm.info()}  # a count, never the ids: private demo ids must not leak


@app.get("/{institute_id}", include_in_schema=False)
def institute_shortcut(institute_id: str):
    """/<id> opens the demo chat for an institute. Keep this the LAST route so it never hides the others.
    Unofficial (prospect) demos have no shortcut: their long random id is their only protection, so guessing /name gives 404."""
    inst = reg.get(institute_id)
    if not inst or inst["config"].get("unofficial_demo"):
        raise HTTPException(404)
    return RedirectResponse(f"/demo?institute={quote(institute_id)}")


jobs.start(reg.all)  # daily cleanup + Monday summaries (an hourly check in a background thread; off with COACHBOT_BACKGROUND_JOBS=0)
