"""Automatic data retention: old chats and leads are deleted on a schedule.

Defaults: chat messages 180 days, leads 365 days (a lead's age counts from its last update).
Change for everyone with RETENTION_DAYS / LEAD_RETENTION_DAYS in .env, or per institute with "retention_days" and
"lead_retention_days" in config.json. 0 means keep forever.
Run by hand (shows counts only unless you add --yes): python -m app.retention [--yes]"""
import logging
import os
import time

from . import db

log = logging.getLogger("coachbot")
DEFAULT_MESSAGE_DAYS, DEFAULT_LEAD_DAYS = 180, 365
DAY = 86400


def _days(value, env: str, default: int):
    raw = value if value is not None else os.getenv(env, "")
    try:
        n = int(raw) if str(raw).strip() != "" else default
    except (TypeError, ValueError):
        n = default
    return n if n > 0 else None  # 0 or less: keep forever


def settings(cfg: dict) -> tuple:
    """(message_days, lead_days); None means keep forever."""
    return (_days(cfg.get("retention_days"), "RETENTION_DAYS", DEFAULT_MESSAGE_DAYS),
            _days(cfg.get("lead_retention_days"), "LEAD_RETENTION_DAYS", DEFAULT_LEAD_DAYS))


def _purge(c, table: str, where: str, args: tuple, dry_run: bool) -> int:
    n = c.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", args).fetchone()[0]
    if n and not dry_run:
        c.execute(f"DELETE FROM {table} WHERE {where}", args)
    return n


def purge_institute(inst_id: str, message_days, lead_days, now=None, dry_run=False) -> dict:
    now = time.time() if now is None else now
    out = {"messages": 0, "leads": 0, "handoffs": 0, "unanswered": 0}
    with db.conn() as c:
        if message_days:
            cut = now - message_days * DAY
            out["messages"] = _purge(c, "messages", "institute=? AND ts<?", (inst_id, cut), dry_run)
            out["handoffs"] = _purge(c, "handoffs", "institute=? AND ts<?", (inst_id, cut), dry_run)
            out["unanswered"] = _purge(c, "unanswered", "institute=? AND ts<?", (inst_id, cut), dry_run)
        if lead_days:
            out["leads"] = _purge(c, "leads", "institute=? AND ts<?", (inst_id, now - lead_days * DAY), dry_run)
    return out


def run(institutes: dict, now=None, dry_run=False) -> dict:
    """Clean every known institute by its own settings, then the shared tables. Returns {institute: counts}."""
    now = time.time() if now is None else now
    result = {}
    for iid, inst in institutes.items():
        m, l = settings(inst["config"])
        result[iid] = purge_institute(iid, m, l, now, dry_run)
    _, lead_days = settings({})
    with db.conn() as c:                                       # shared tables
        shared = {"webhook_ids": _purge(c, "seen", "ts<?", (now - 7 * DAY,), dry_run),
                  "inquiries": _purge(c, "inquiries", "ts<?", (now - lead_days * DAY,), dry_run) if lead_days else 0,
                  "jobs": _purge(c, "jobs", "ts<?", (now - 400 * DAY,), dry_run)}
    result["_shared"] = shared
    total = sum(sum(v.values()) for v in result.values())
    if total:
        log.info("RETENTION %s: removed %s", "(dry run)" if dry_run else "done", {k: v for k, v in result.items() if any(v.values())})
    return result


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    from . import registry
    db.init()
    dry = "--yes" not in sys.argv
    res = run(registry.Registry().all(), dry_run=dry)
    for k, v in res.items():
        print(f"{k}: " + ", ".join(f"{a} {b}" for a, b in v.items()))
    print("This was a dry run: nothing was deleted. Add --yes to delete." if dry else "Deleted.")
