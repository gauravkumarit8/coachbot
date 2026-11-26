"""Checks the institutes shipped in this project. Run: python -m tests.test_institutes"""
import re, subprocess
from app import brain, registry

inst = brain.load_institutes()
PRIVATE = re.compile(r"^[a-z0-9]+-[a-z0-9]{8}$")
demos = [i for i in inst if i != "demo"]
assert {i.split("-")[0] for i in demos} >= {"tribac", "mcm"} and "demo" in inst, list(inst)
assert all(PRIVATE.match(i) for i in demos), f"prospect demos need a random suffix in their id: {demos}"
for iid, i in inst.items():
    assert i["config"]["id"] == iid, f"{iid}: folder name and config id differ"
    assert len(i["knowledge"]) <= registry.MAX_KNOWLEDGE_CHARS, f"{iid}: knowledge too long"
assert not inst["demo"]["config"].get("unofficial_demo")
assert not any("REPLACE" in str(v) or "XXXX" in str(v) for v in inst["demo"]["config"].values()), "demo config still has placeholders"
assert "whatsapp" not in inst["demo"]["config"], "demo has no real WhatsApp settings: alerts would try to send through them"
for iid in demos:
    assert inst[iid]["config"].get("unofficial_demo") is True, f"{iid}: banner flag missing"  # demos built from a real institute's PUBLIC site
    k = inst[iid]["knowledge"]
    assert "UNOFFICIAL DEMO" in k, f"{iid}: must be labelled unofficial"
    fees = k.split("## Fees")[1].split("##")[0]
    assert "NOT provided" in fees and not re.search(r"\d{2},\d{3}", fees), f"{iid}: no invented fees"
    assert "Demo behaviour" in k, f"{iid}: demo must explain handoffs honestly"
    assert not {"owner_key_env", "owner_phone", "whatsapp", "meta_ids", "alerts"} & set(inst[iid]["config"]), f"{iid}: a prospect demo must never message anyone or have an owner page"
# the demo page script still parses
h = open("static/demo.html").read()
open("/tmp/demo_check.js", "w").write(re.search(r"<script>(.*)</script>", h, re.S).group(1))
try:
    assert subprocess.run(["node", "--check", "/tmp/demo_check.js"]).returncode == 0
except FileNotFoundError:
    pass  # node not installed: skip
print("institute checks passed")
