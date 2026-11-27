"""All institutes live in institutes/<id>/{config.json, knowledge.md}.
The Registry notices when those files change (edited by hand or via the owner page) and reloads them
without restarting the server. A broken edit never takes the bot down: the last good copy stays active."""
import hmac
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

from . import channels

log = logging.getLogger("coachbot")
SHIPPED = Path(__file__).resolve().parent.parent / "institutes"   # the institutes that come with the code
ROOT = Path(os.getenv("COACHBOT_INSTITUTES_DIR") or SHIPPED)       # where they live while running (a persistent disk on Render)
MAX_KNOWLEDGE_CHARS = 12000   # every message sends this to the model, so keep it lean (cost + speed)
KEEP_VERSIONS = 20            # old versions kept per institute for "undo"


def load_all(root) -> dict:
    out = {}
    for d in sorted(Path(root).iterdir()) if Path(root).exists() else []:
        cfg_file, kb_file = d / "config.json", d / "knowledge.md"
        if d.is_dir() and cfg_file.exists() and kb_file.exists():
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            out[cfg["id"]] = {"config": cfg, "knowledge": kb_file.read_text(encoding="utf-8")}
    return out


def _num(p: Path) -> int:
    try:
        return int(p.stem.split("-")[1])
    except (IndexError, ValueError):
        return -1


def _versions(hist: Path) -> list:
    """Backups oldest -> newest. Files are named knowledge-<number>.md and sorted by that number."""
    return sorted(hist.glob("knowledge-*.md"), key=_num)


def check_owner_key(cfg: dict, key: str | None) -> bool:
    """Owner key lives in an env var named by config 'owner_key_env'. Fails closed if missing/too short."""
    env = cfg.get("owner_key_env")
    expected = os.getenv(env, "") if env else ""
    if len(expected) < 12 or not key:
        return False
    return hmac.compare_digest(key.encode(), expected.encode())


class Registry:
    def __init__(self, root=None):
        self.root = Path(root) if root else ROOT
        self._lock = threading.Lock()
        self._sig = None
        self._data, self._wa, self._meta = {}, {}, {}
        self.refresh()

    def _signature(self) -> tuple:
        sig = []
        if self.root.exists():
            for d in sorted(self.root.iterdir()):
                for name in ("config.json", "knowledge.md"):
                    p = d / name
                    if p.exists():
                        st = p.stat()  # size too: on Windows, quick writes can share one timestamp tick
                        sig.append((str(p), st.st_mtime_ns, st.st_size))
        return tuple(sig)

    def refresh(self, force=False):
        if not force and self._signature() == self._sig:
            return
        with self._lock:
            sig = self._signature()
            if not force and sig == self._sig:
                return
            try:
                data = load_all(self.root)
            except Exception as exc:  # e.g. half-edited JSON: keep serving the last good version
                log.error("institute files could not be loaded, keeping previous version: %s", exc)
                self._sig = sig  # retried automatically when a file changes again
                return
            self._wa = {}
            for i in data.values():
                wa = channels.wa_settings(i["config"])
                if wa["provider"] == "meta" and wa.get("phone_number_id"):
                    self._wa[wa["phone_number_id"]] = i
            self._meta = {m: i for i in data.values() for m in i["config"].get("meta_ids", [])}
            if self._sig is not None:
                log.info("institutes reloaded: %s", ", ".join(data))
            self._data, self._sig = data, sig

    def all(self) -> dict:
        self.refresh()
        return self._data

    def get(self, iid: str):
        self.refresh()
        return self._data.get(iid)

    def by_wa(self, phone_number_id):
        self.refresh()
        return self._wa.get(phone_number_id)

    def by_meta(self, meta_id):
        self.refresh()
        return self._meta.get(meta_id)

    # ---- owner editing -------------------------------------------------
    def save_knowledge(self, iid: str, text: str) -> int:
        """Validate, back up the current version, write atomically. Returns saved character count."""
        if not self.get(iid):
            raise KeyError(iid)
        text = text.replace("\r\n", "\n").strip() + "\n"
        if len(text) < 30:
            raise ValueError("That looks too short. Add your fees, batches and admission details.")
        if len(text) > MAX_KNOWLEDGE_CHARS:
            raise ValueError(f"Too long: {len(text)} characters (max {MAX_KNOWLEDGE_CHARS}). Shorten it, the bot reads all of this on every message.")
        d = self.root / iid
        kb, hist = d / "knowledge.md", d / "history"
        hist.mkdir(exist_ok=True)
        if kb.exists():
            have = _versions(hist)
            n = _num(have[-1]) + 1 if have else 1  # a counter, not a clock: clocks can tick too slowly to be unique
            shutil.copy2(kb, hist / f"knowledge-{n:019d}.md")
            for stale in _versions(hist)[:-KEEP_VERSIONS]:
                stale.unlink()
        tmp = d / "knowledge.md.tmp"
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, kb)  # atomic: the bot never reads a half-written file
        self.refresh(force=True)  # our own save must never be missed, whatever the file timestamps say
        return len(text)

    def undo_knowledge(self, iid: str) -> int:
        """Restore the most recent previous version (the replaced one becomes the new 'previous')."""
        versions = _versions(self.root / iid / "history") if self.get(iid) else []
        if not versions:
            raise ValueError("Nothing to undo yet.")
        return self.save_knowledge(iid, versions[-1].read_text(encoding="utf-8"))
