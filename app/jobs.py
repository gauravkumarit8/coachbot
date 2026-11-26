"""Background jobs, checked every hour: daily data cleanup and the Monday weekly summary.
Each job notes in the database that it ran, so restarting the server never repeats it.
Switch off with COACHBOT_BACKGROUND_JOBS=0."""
import logging
import os
import threading
import time

from . import db, notify, retention, weekly

log = logging.getLogger("coachbot")


def tick(institutes: dict, now=None, send=None) -> dict:
    """One check. Safe to call as often as you like."""
    now = time.time() if now is None else now
    out = {}
    key = f"retention:{db.today_str(now)}"
    if not db.job_done(key):
        out["retention"] = retention.run(institutes, now)
        db.mark_job(key, now)
    if weekly.due(now):
        out["weekly"] = weekly.send_due(institutes, now, send=send or notify.send_alerts)
    return out


def start(get_institutes, first_delay: float = 60, every: float = 3600):
    """Start the hourly checker in a background thread. Returns the thread, or None when switched off."""
    if os.getenv("COACHBOT_BACKGROUND_JOBS", "1") == "0":
        return None

    def loop():
        time.sleep(first_delay)
        while True:
            try:
                tick(get_institutes())
            except Exception:
                log.exception("background job failed")
            time.sleep(every)

    t = threading.Thread(target=loop, name="coachbot-jobs", daemon=True)
    t.start()
    return t
