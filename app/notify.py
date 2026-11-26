"""Owner alerts that need no Meta approval: Telegram (free, instant) and email. Configure per institute in config.json:
  "alerts": {"telegram_chat_id": "123456789", "telegram_token_env": "TELEGRAM_BOT_TOKEN", "email": "owner@example.com"}"""
import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger("coachbot")


def _httpx_post(url, json, timeout):
    import httpx  # lazy: keeps this module importable (and testable) without the dependency
    return httpx.post(url, json=json, timeout=timeout)


def send_telegram(token: str, chat_id: str, text: str, post=None) -> bool:
    try:
        r = (post or _httpx_post)(f"https://api.telegram.org/bot{token}/sendMessage",
                                   {"chat_id": chat_id, "text": text[:4000]}, 15)
    except Exception as e:  # never log the URL or the exception text: both can contain the bot token
        log.error("Telegram alert failed: %s", type(e).__name__)
        return False
    if r.status_code >= 400:
        log.error("Telegram alert failed: HTTP %s %s", r.status_code, str(r.text)[:150])
        return False
    return True


def send_email(to: str, subject: str, body: str, env=None) -> bool:
    env = env if env is not None else os.environ
    host, user, pwd = (env.get(k, "").strip() for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))
    if not (host and user and pwd):
        log.warning("Email alert not sent: set SMTP_HOST, SMTP_USER and SMTP_PASSWORD in .env")
        return False
    port = int(env.get("SMTP_PORT", "587") or 587)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = env.get("SMTP_FROM") or user, to, subject[:150]
    msg.set_content(body)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as s:
                s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls()
                s.login(user, pwd)
                s.send_message(msg)
    except Exception as e:
        log.error("Email alert failed: %s", type(e).__name__)
        return False
    return True


def send_alerts(alerts: dict, text: str):
    """Send `text` on every alert channel configured for an institute. Misconfiguration is logged, never raised."""
    results = {}  # what happened per channel: True sent, False failed, missing = not configured
    chat = str(alerts.get("telegram_chat_id") or "").strip()
    if chat:
        env_name = alerts.get("telegram_token_env", "TELEGRAM_BOT_TOKEN")
        token = os.getenv(env_name, "").strip()
        if token:
            results["telegram"] = bool(send_telegram(token, chat, text))
        else:
            log.warning("Telegram alert not sent: environment variable %s is empty", env_name)
            results["telegram"] = False
    if alerts.get("email"):
        results["email"] = bool(send_email(alerts["email"], (text.splitlines() or ["CoachBot alert"])[0], text))
    return results


def parse_chat_ids(updates: dict) -> list:
    """From Telegram's getUpdates answer: [(chat_id, name)] of people who have messaged the bot."""
    seen, out = set(), []
    for u in updates.get("result", []):
        chat = (u.get("message") or {}).get("chat") or {}
        if chat.get("id") is not None and chat["id"] not in seen:
            seen.add(chat["id"])
            out.append((chat["id"], " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("title", "")))
    return out


def send_test(inst_id: str, root=None) -> int:
    """python -m app.notify test <institute_id>: sends one test alert through that institute's alert settings and says
    what happened. Returns a process exit code (0 = every configured channel worked)."""
    from . import registry
    inst = registry.Registry(root).get(inst_id)
    if not inst:
        print(f"No institute with id '{inst_id}' in institutes/.")
        return 2
    alerts = inst["config"].get("alerts") or {}
    if not alerts:
        print(f"'{inst_id}' has no \"alerts\" block in config.json (telegram_chat_id and/or email).")
        return 2
    res = send_alerts(alerts, f"CoachBot test alert for {inst['config']['name']}. If you can read this, alerts work.")
    for ch in ("telegram", "email"):
        if ch in res:
            print(f"{ch}: {'sent' if res[ch] else 'FAILED (see the log lines above for the reason)'}")
    return 0 if res and all(res.values()) else 1


if __name__ == "__main__":  # python -m app.notify  -> chat ids of people who have started your bot;  python -m app.notify test <id>
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    if sys.argv[1:2] == ["test"]:
        logging.basicConfig(level=logging.INFO)
        raise SystemExit(send_test(sys.argv[2]) if len(sys.argv) > 2 else "Usage: python -m app.notify test <institute_id>")
    import httpx
    tok = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not tok:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env first (create a bot with @BotFather).")
    found = parse_chat_ids(httpx.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=15).json())
    print("\n".join(f"chat id {i}  ({n})" for i, n in found) or "Nobody has messaged the bot yet. Open the bot in Telegram, press Start, send 'hi', then run this again.")
