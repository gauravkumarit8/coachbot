"""Weekly summary for each institute owner, sent to their alerts (Telegram / email) every Monday after 9 am Indian time
(or the first time the server checks after that, if it was off). Also shown on the owner page and printable:
python -m app.weekly <institute_id> [--send]"""
import logging
import time
from datetime import datetime, timedelta

from . import db, notify, report

log = logging.getLogger("coachbot")


def _dt(now):
    return datetime.fromtimestamp(now, db._tz())


def week_key(now) -> str:
    y, w, _ = _dt(now).isocalendar()
    return f"{y}-W{w:02d}"


def due(now=None) -> bool:
    """True from Monday 9:00 (Indian time) onwards; the 'already sent this week' note stops repeats."""
    d = _dt(time.time() if now is None else now)
    return d.weekday() > 0 or d.hour >= 9


def collect(inst: dict, now=None) -> dict:
    now = time.time() if now is None else now
    cfg = inst["config"]
    oh = cfg.get("office_hours") or [9, 19]
    r = report.build(cfg["id"], 7, int(oh[0]), int(oh[1]), now=now)
    since = now - 7 * 86400
    with db.conn() as c:
        waiting = c.execute("SELECT COUNT(*) FROM leads WHERE institute=? AND COALESCE(status,'new')='new' AND ts>=?",
                            (cfg["id"], now - 30 * 86400)).fetchone()[0]
        joined = c.execute("SELECT COUNT(*) FROM leads WHERE institute=? AND status='joined' AND status_ts>=?", (cfg["id"], since)).fetchone()[0]
    r.update(waiting=waiting, joined_week=joined, unanswered_top=db.list_unanswered(cfg["id"], 5), name=cfg["name"],
             start=_dt(since).strftime("%d %b"), end=_dt(now).strftime("%d %b"), office=f"{int(oh[0]):02d}:00 to {int(oh[1]):02d}:00")
    return r


def render(d: dict, owner_url: str = "") -> str:
    lines = [f"CoachBot weekly summary: {d['name']}", f"{d['start']} to {d['end']}", "",
             f"Chats: {d['chats']} ({d['after_hours_chats']} started outside {d['office']}, when nobody was at the desk)",
             f"Leads this week: {d['leads']} ({d['demo_requests']} asked for a demo class)",
             f"Still waiting for your call: {d['waiting']}",
             f"Joined this week: {d['joined_week']}"]
    if d["unanswered_top"]:
        lines += ["", "Questions the assistant could not answer (add these to your details):"]
        lines += [f" - {'%dx ' % q['n'] if q['n'] > 1 else ''}{q['question']}" for q in d["unanswered_top"]]
    tips = []
    if d["waiting"]:
        tips.append(f"Call the {d['waiting']} lead(s) still marked New, then mark them Called on your owner page.")
    if d["unanswered_top"]:
        tips.append("Add answers for the questions above, then press 'Mark all as done'.")
    if not d["chats"]:
        tips.append("No chats this week. Check that the chat button shows on your website, and share your website link on WhatsApp and Instagram.")
    elif not d["leads"]:
        tips.append("Parents chatted but nobody asked for a callback. Check your fees and admission details are complete.")
    if tips:
        lines += ["", "What to do this week:"] + [f" - {t}" for t in tips]
    if owner_url:
        lines += ["", f"Your owner page: {owner_url}"]
    return "\n".join(lines)


def build(inst: dict, now=None) -> str:
    from . import company
    domain = company.load().get("domain", "")
    return render(collect(inst, now), f"{domain}/owner/{inst['config']['id']}" if domain and inst["config"].get("owner_key_env") else "")


def send_due(institutes: dict, now=None, force=False, send=None) -> list:
    """Send this week's summary to every institute with alerts that has not had it yet. Returns the ids it sent to.
    Demos and institutes with "weekly_summary": false are skipped. A failed send is retried at the next check."""
    now = time.time() if now is None else now
    send = send or notify.send_alerts
    sent = []
    for iid, inst in institutes.items():
        cfg = inst["config"]
        alerts = cfg.get("alerts")
        if not alerts or cfg.get("unofficial_demo") or cfg.get("weekly_summary") is False:
            continue
        key = f"weekly:{iid}:{week_key(now)}"
        if db.job_done(key) and not force:
            continue
        try:
            res = send(alerts, build(inst, now)) or {}
        except Exception:
            log.exception("weekly summary failed for %s", iid)
            continue
        if res and any(res.values()):
            db.mark_job(key, now)
            sent.append(iid)
            log.info("WEEKLY SUMMARY sent for %s", iid)
        else:
            log.warning("weekly summary for %s could not be delivered; will retry", iid)
    return sent


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    from . import registry
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        raise SystemExit(__doc__)
    db.init()
    inst = registry.Registry().get(args[0])
    if not inst:
        raise SystemExit(f"No institute '{args[0]}'")
    print(build(inst))
    if "--send" in sys.argv:
        print("\nSent." if send_due({args[0]: inst}, force=True) else "\nNot sent: the institute has no alerts, or delivery failed (see log).")
