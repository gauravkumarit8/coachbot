"""Set up a NEW paying institute: python -m app.onboard <id> "<Institute Name>" [options]

Creates institutes/<id>/ (config.json + knowledge.md template), makes a strong owner key, and prints everything you
need next: the .env line, the owner page link, the website embed line and the go-live checks.
Options: --phone 919999999999   --telegram-chat 123456789   --email owner@example.com   --write-env   --domain https://your-host
Prospect demos are different: use `python -m app.new_demo`."""
import argparse
import json
import re
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,39}$")


def env_name(inst_id: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", inst_id.upper()).strip("_") + "_OWNER_KEY"


def make(inst_id: str, name: str, phone="", telegram_chat="", email="", root: Path | None = None, env_path: Path | None = None,
         write_env: bool = False) -> dict:
    root = root or HERE / "institutes"
    if not ID_RE.match(inst_id):
        raise ValueError("id must be 3 to 40 characters: lowercase letters, digits and hyphens (for example mcm-patna)")
    if not name.strip():
        raise ValueError("institute name is required")
    folder = root / inst_id
    if folder.exists():
        raise ValueError(f"institutes/{inst_id} already exists")
    cfg = {"id": inst_id, "name": name.strip(), "owner_key_env": env_name(inst_id),
           "website_handoff_message": "Our counsellor has been notified and will contact you shortly.", "daily_message_cap": 500}
    if phone:
        cfg["owner_phone"] = re.sub(r"\D", "", phone)
    alerts = {k: v for k, v in (("telegram_chat_id", telegram_chat.strip()), ("email", email.strip())) if v}
    if alerts:
        cfg["alerts"] = alerts
    folder.mkdir(parents=True)
    (folder / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tpl = (HERE / "templates" / "knowledge_template.md").read_text(encoding="utf-8")
    (folder / "knowledge.md").write_text(tpl.replace("{name}", name.strip()), encoding="utf-8")
    key, written = secrets.token_urlsafe(18), False
    if write_env and env_path:
        existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        if re.search(rf"^{cfg['owner_key_env']}=", existing, re.M):
            key = None  # never overwrite an existing key
        else:
            env_path.write_text(existing + ("" if not existing or existing.endswith("\n") else "\n") + f"{cfg['owner_key_env']}={key}\n", encoding="utf-8")
            written = True
    return {"id": inst_id, "config": cfg, "env_var": cfg["owner_key_env"], "key": key, "written": written, "folder": str(folder)}


def instructions(res: dict, domain: str = "https://YOUR-HOST") -> str:
    i, v = res["id"], res["env_var"]
    env = (f"Added {v} to .env (the key is hidden here; open .env to read it)." if res["written"] else
           f"Add this line to .env:\n    {v}={res['key']}" if res["key"] else f"{v} already exists in .env: left unchanged.")
    return f"""Created institutes/{i}/  (config.json + knowledge.md template)

1. Owner key
   {env}
   Give the key to the owner privately (not in a group chat). Restart the server after changing .env.
2. Fill in institutes/{i}/knowledge.md with the owner's real fees, batches and contact details.
   Anything unknown stays "NOT provided, counsellor must confirm". Keep it under 12,000 characters.
3. Owner page (they edit fees themselves):   {domain}/owner/{i}
4. Try the chat:                            {domain}/demo?institute={i}
5. Add this line to the institute's website, just before </body>:
   <script src="{domain}/widget.js" data-institute="{i}" data-title="Chat with us" async></script>
6. Alerts:  python -m app.notify test {i}
7. Go-live checks: ask the 20 toughest parent questions, one off-topic question, one refund request, and leave a test lead.
   See docs/ONBOARDING.md for the full checklist."""


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.onboard", description=__doc__.split("\n")[0])
    ap.add_argument("id"); ap.add_argument("name")
    ap.add_argument("--phone", default=""); ap.add_argument("--telegram-chat", default=""); ap.add_argument("--email", default="")
    ap.add_argument("--write-env", action="store_true"); ap.add_argument("--domain", default="https://YOUR-HOST")
    a = ap.parse_args(argv)
    try:
        res = make(a.id, a.name, a.phone, a.telegram_chat, a.email, env_path=HERE / ".env", write_env=a.write_env)
    except ValueError as e:
        print(f"Not created: {e}")
        return 2
    print(instructions(res, a.domain.rstrip("/")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
