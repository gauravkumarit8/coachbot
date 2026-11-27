"""Make a PRIVATE demo copy of an institute: python -m app.new_demo <source_id> [slug]

The copy gets an id like tribac-k4x9m2qa. The random part is the only thing protecting a prospect's demo link,
so there is no /<id> shortcut for unofficial demos and the id is never listed anywhere. Owner page, alerts and
WhatsApp/Meta settings are NOT copied: a prospect demo must never message anyone."""
import json
import re
import secrets
import shutil
import string
import sys
from pathlib import Path

from . import registry

ROOT = registry.ROOT
ALPHABET = string.ascii_lowercase + string.digits
STRIP = ("owner_key_env", "owner_phone", "whatsapp", "meta_ids", "meta_token_env", "alerts")


def make(source_id: str, slug: str | None = None, root: Path = ROOT) -> str:
    src = root / source_id
    if not (src / "config.json").exists():
        raise SystemExit(f"No institute '{source_id}' in {root}")
    slug = re.sub(r"[^a-z0-9]+", "", (slug or source_id.split("-")[0]).lower()) or "demo"
    new_id = f"{slug}-{''.join(secrets.choice(ALPHABET) for _ in range(8))}"
    dst = root / new_id
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("history", "*.tmp"))
    cfg = json.loads((dst / "config.json").read_text(encoding="utf-8"))
    cfg["id"], cfg["unofficial_demo"] = new_id, True
    for k in STRIP:
        cfg.pop(k, None)
    (dst / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return new_id


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m app.new_demo <source_id> [slug]")
    new = make(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"Created institutes/{new}\nEdit its knowledge.md, then the private link is:  <your-url>/demo?institute={new}")
