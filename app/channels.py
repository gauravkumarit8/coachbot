"""Inbound parsing + outbound sending.

WhatsApp can run two ways, chosen per institute in config.json ("whatsapp.provider"):
  "meta": you call Meta's Graph API directly (needs your own Meta app + approvals).
  "bsp" : the institute's number lives at a BSP that mirrors Meta's Cloud API format
          (e.g. 360dialog: POST {send_url} with an API-key header). Same JSON, different URL + auth.
To support a BSP with a different format, add a branch in send_whatsapp() and a parser next to parse_whatsapp().
Check endpoints against the provider's current docs before going live."""
import hashlib
import hmac
import logging
import os
import threading

log = logging.getLogger("coachbot")
GRAPH = f"https://graph.facebook.com/{os.getenv('GRAPH_VERSION', 'v21.0')}"


def run_in_background(fn, *args):
    """Run fn(*args) in a thread so slow side-effects (owner alerts) never delay the customer's reply."""
    def _run():
        try:
            fn(*args)
        except Exception:
            log.exception("background task failed")
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def verify_signature(body: bytes, header: str | None) -> bool:
    """Meta signs every webhook POST with your app secret. Reject anything unsigned/forged."""
    secret = os.getenv("META_APP_SECRET")
    if not secret:
        log.warning("META_APP_SECRET not set: webhook signatures NOT verified (dev only)")
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def _post(url: str, headers: dict, payload: dict) -> bool:
    import httpx  # lazy: keeps parsing/tests importable without the dependency
    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code >= 400:
            log.error("POST %s -> %s %s", url, r.status_code, r.text[:300])
        return r.status_code < 400
    except httpx.HTTPError as e:
        log.error("request to %s failed: %s", url, type(e).__name__)
        return False


# ---------- WhatsApp ----------
def wa_settings(inst_cfg: dict) -> dict:
    wa = dict(inst_cfg.get("whatsapp") or {})
    wa.setdefault("provider", "meta")
    return wa


def send_whatsapp(wa: dict, to: str, text: str) -> bool:
    payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
               "type": "text", "text": {"body": text[:4000]}}
    env = wa.get("api_key_env", "WHATSAPP_TOKEN")
    key = os.getenv(env, "").strip()  # stray spaces/newlines in .env make an illegal header
    if not key:
        log.warning("WhatsApp message not sent: environment variable %s is empty (set it in .env)", env)
        return False
    if wa["provider"] == "bsp":
        header = wa.get("auth_header", "Authorization")  # e.g. "D360-API-KEY" for 360dialog
        headers = {header: f"Bearer {key}" if header.lower() == "authorization" else key}
        return _post(wa["send_url"], headers, payload)
    return _post(f"{GRAPH}/{wa['phone_number_id']}/messages", {"Authorization": f"Bearer {key}"}, payload)


def parse_whatsapp(payload: dict) -> list:
    """Meta-format webhook -> [(phone_number_id, message_dict)]. Status updates (sent/read) are ignored."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            v = change.get("value", {})
            pnid = v.get("metadata", {}).get("phone_number_id")
            out += [(pnid, m) for m in v.get("messages", [])]
    return out


# ---------- Instagram + Facebook ----------
def send_meta(recipient_id: str, text: str, token_env: str = "META_PAGE_TOKEN") -> bool:
    """Facebook Messenger and Instagram DMs (same endpoint, page access token)."""
    token = os.getenv(token_env, "").strip()
    if not token:
        log.warning("Message not sent: environment variable %s is empty (set it in .env)", token_env)
        return False
    return _post(f"{GRAPH}/me/messages", {"Authorization": f"Bearer {token}"},
                 {"recipient": {"id": recipient_id}, "messaging_type": "RESPONSE",
                  "message": {"text": text[:1900]}})
