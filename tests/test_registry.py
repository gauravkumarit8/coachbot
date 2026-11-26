"""Offline tests: hot reload, safe editing, owner key. Run: python -m tests.test_registry"""
import json, logging, os, tempfile
from pathlib import Path

from app import brain, registry

logging.disable(logging.CRITICAL)
root = Path(tempfile.mkdtemp())


def make(iid, name, kb, **cfg):
    d = root / iid; d.mkdir(exist_ok=True)
    (d / "config.json").write_text(json.dumps({"id": iid, "name": name, **cfg}))
    (d / "knowledge.md").write_text(kb)


def bump(path):  # make sure the modified-time really changes, even on coarse filesystems
    st = os.stat(path); os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


make("alpha", "Alpha Academy", "Fee Rs 60,000 for JEE. " * 3, whatsapp={"phone_number_id": "111"}, meta_ids=["pg1"], owner_key_env="ALPHA_KEY")
make("beta", "Beta Classes", "Fee Rs 85,000 for JEE. " * 3)
reg = registry.Registry(root)

# 1. Loading and lookups
assert set(reg.all()) == {"alpha", "beta"} and reg.get("alpha")["config"]["name"] == "Alpha Academy"
assert reg.by_wa("111")["config"]["id"] == "alpha" and reg.by_meta("pg1")["config"]["id"] == "alpha"
assert reg.get("nope") is None and reg.by_wa("999") is None

# 2. Hot reload: edit a file by hand, no restart
kb = root / "alpha" / "knowledge.md"
kb.write_text("Fee Rs 70,000 for JEE (new price). " * 3); bump(kb)
assert "70,000" in reg.get("alpha")["knowledge"]

# 3. New institute folder appears; broken JSON keeps the last good copy; fixing it recovers
make("gamma", "Gamma Tutorials", "Fee Rs 40,000. " * 4)
assert "gamma" in reg.all()
cfg = root / "alpha" / "config.json"; good = cfg.read_text()
cfg.write_text("{ not json"); bump(cfg)
assert reg.get("alpha")["config"]["name"] == "Alpha Academy"  # still serving
cfg.write_text(good.replace("Alpha Academy", "Alpha Academy Patna")); bump(cfg)
assert reg.get("alpha")["config"]["name"] == "Alpha Academy Patna"

# 4. Saving: validation, CRLF normalisation, backups, size cap
for bad in ("short", "x" * (registry.MAX_KNOWLEDGE_CHARS + 1)):
    try: reg.save_knowledge("alpha", bad); raise AssertionError("should reject")
    except ValueError: pass
assert reg.save_knowledge("alpha", "Line one of the new details.\r\nFees are Rs 99,000.") > 30
assert "\r" not in kb.read_text() and "99,000" in reg.get("alpha")["knowledge"]
assert len(list((root / "alpha" / "history").glob("knowledge-*.md"))) == 1
try: reg.save_knowledge("../beta", "x" * 100); raise AssertionError("path traversal!")
except KeyError: pass

# 5. Undo restores the previous text; undo again toggles back
reg.save_knowledge("alpha", "Totally different second version of details here.")
reg.undo_knowledge("alpha"); assert "99,000" in reg.get("alpha")["knowledge"]
reg.undo_knowledge("alpha"); assert "second version" in reg.get("alpha")["knowledge"]
try: reg.undo_knowledge("beta"); raise AssertionError("nothing to undo")
except ValueError: pass

# 6. Old versions are pruned
for i in range(registry.KEEP_VERSIONS + 8): reg.save_knowledge("beta", f"Version number {i} of the beta details.")
assert len(list((root / "beta" / "history").glob("knowledge-*.md"))) == registry.KEEP_VERSIONS

# 7. Owner key: fails closed
c = reg.get("alpha")["config"]
os.environ.pop("ALPHA_KEY", None)
assert not registry.check_owner_key(c, "anything")           # env var not set
os.environ["ALPHA_KEY"] = "short"
assert not registry.check_owner_key(c, "short")               # too short to be allowed
os.environ["ALPHA_KEY"] = "a-long-secret-key-123"
assert registry.check_owner_key(c, "a-long-secret-key-123")
assert not registry.check_owner_key(c, "wrong") and not registry.check_owner_key(c, None)
assert not registry.check_owner_key(reg.get("beta")["config"], "a-long-secret-key-123")  # beta has no owner_key_env

# 7b. Regression found on Windows (file timestamps tick only every ~16 ms): quick saves and undos must still
#     show up and must never overwrite each other's backups, even if file times never change.
class CoarseClock(registry.Registry):
    def _signature(self): return ("never-changes",)
hist = root / "gamma" / "history"; hist.mkdir(exist_ok=True)
(hist / "knowledge-1731234567890123456.md").write_text("an old-style backup that is long enough to be valid")
creg = CoarseClock(root)
for n in ("one", "two", "three"):
    creg.save_knowledge("gamma", f"Version {n} of the gamma details, long enough to pass.")
assert "Version three" in creg.get("gamma")["knowledge"]
creg.undo_knowledge("gamma"); assert "Version two" in creg.get("gamma")["knowledge"]
creg.undo_knowledge("gamma"); assert "Version three" in creg.get("gamma")["knowledge"]
names = [p.name for p in hist.glob("knowledge-*.md")]
assert len(names) == len(set(names)) >= 5, names
assert registry._versions(hist)[0].name == "knowledge-1731234567890123456.md"

# 8. brain.load_institutes still works with a custom root
brain.ROOT = root
assert set(brain.load_institutes()) == {"alpha", "beta", "gamma"}
print("registry tests passed")
