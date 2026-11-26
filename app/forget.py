"""Delete-on-request: python -m app.forget <institute_id> <phone-or-chat-id> [--yes]

Finds every chat, lead and handoff for that person (by phone number or chat/session id) and deletes it.
Without --yes it only shows what it would delete. Take a backup of coachbot.db first."""
import sys

from . import db

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    args = [a for a in sys.argv[1:] if a != "--yes"]
    if len(args) != 2:
        raise SystemExit(__doc__)
    db.init()
    dry = "--yes" not in sys.argv
    counts = db.forget(args[0], args[1], dry_run=dry)
    print(("WOULD delete: " if dry else "Deleted: ") + ", ".join(f"{k} {v}" for k, v in counts.items()))
    if dry:
        print("Nothing was deleted. Run again with --yes to delete.")
