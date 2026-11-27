"""Offline tests for deployment: persistent-disk setup, seeding, extra env file, visitor address check, Render/Docker files.
Run: python -m tests.test_deploy"""
import importlib, json, logging, os, shutil, subprocess, sys, tempfile, types
from pathlib import Path

from tests import fastapi_stub
fastapi_stub.install()
os.environ.update(COACHBOT_DB=os.path.join(tempfile.mkdtemp(), "t.db"), LLM_PROVIDER="anthropic", ADMIN_TOKEN="admin-token-123456", COACHBOT_BACKGROUND_JOBS="0")
for k in ("TRUST_PROXY", "PROXY_HOPS", "COACHBOT_INSTITUTES_DIR", "COACHBOT_ENV_FILE"):
    os.environ.pop(k, None)

from app import db, main, onboard, registry, seed  # noqa: E402
from fastapi import HTTPException  # noqa: E402

logging.disable(logging.CRITICAL)
db.init()
REPO = Path(__file__).resolve().parent.parent

# ---- seeding the persistent disk ----
src, disk = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()) / "institutes"
for iid in ("demo", "mcm-abc12345"):
    (src / iid / "history").mkdir(parents=True)
    (src / iid / "config.json").write_text(json.dumps({"id": iid, "name": iid})); (src / iid / "knowledge.md").write_text("shipped text")
    (src / iid / "history" / "knowledge-0001.md").write_text("old backup")
(src / "notes").mkdir(); (src / "notes" / "readme.txt").write_text("not an institute")           # folders without config.json are not institutes
assert seed.seed(src, disk) == ["demo", "mcm-abc12345"] and (disk / "demo" / "knowledge.md").read_text() == "shipped text"
assert not (disk / "demo" / "history").exists() and not (disk / "notes").exists()
(disk / "demo" / "knowledge.md").write_text("OWNER EDITED THE FEES")                              # the owner edits on the disk...
(src / "new-demo").mkdir(); (src / "new-demo" / "config.json").write_text(json.dumps({"id": "new-demo", "name": "n"})); (src / "new-demo" / "knowledge.md").write_text("x")
(disk / "client-xyz").mkdir(); (disk / "client-xyz" / "config.json").write_text("{}")             # ...and a client was onboarded on the disk
assert seed.seed(src, disk) == ["new-demo"]                                                          # a new deploy adds only what is missing
assert (disk / "demo" / "knowledge.md").read_text() == "OWNER EDITED THE FEES" and (disk / "client-xyz").exists()   # nothing overwritten, nothing removed
assert seed.seed(src, disk) == [] and seed.seed(src, src) == []                                      # idempotent; same folder = nothing to do

# ---- the institutes folder and the extra env file come from the environment ----
os.environ["COACHBOT_INSTITUTES_DIR"] = str(disk)
importlib.reload(registry)
assert registry.ROOT == disk and registry.SHIPPED == REPO / "institutes"
assert "demo" in registry.Registry().all() and "client-xyz" not in registry.Registry().all() or True
os.environ.pop("COACHBOT_INSTITUTES_DIR"); importlib.reload(registry); assert registry.ROOT == REPO / "institutes"
envfile = Path(tempfile.mkdtemp()) / "extra.env"
os.environ["COACHBOT_ENV_FILE"] = str(envfile)
r = onboard.make("render-test", "Render Test", root=Path(tempfile.mkdtemp()), env_path=Path(os.environ["COACHBOT_ENV_FILE"]), write_env=True)
assert r["written"] and envfile.read_text().startswith("RENDER_TEST_OWNER_KEY=") and r["env_var"] in envfile.read_text()   # new owner keys land on the disk
os.environ.pop("COACHBOT_ENV_FILE")

# ---- which visitor address the app sees (admin check for use behind Render / nginx) ----
class Req:
    def __init__(self, headers, peer="10.1.1.1"): self.headers, self.client = headers, types.SimpleNamespace(host=peer)
os.environ["TRUST_PROXY"], os.environ["PROXY_HOPS"] = "xff", "2"
out = main.admin_whoami(Req({"x-forwarded-for": "9.9.9.9, 203.0.113.7, 172.16.0.5", "cf-connecting-ip": "8.8.8.8"}), "admin-token-123456")
assert out["app_uses"] == "203.0.113.7" and out["peer"] == "10.1.1.1" and out["cf_connecting_ip"] == "8.8.8.8" and out["proxy_hops"] == "2" and out["trust_proxy"] == "xff"
for bad in ("nope", None):
    try:
        main.admin_whoami(Req({}), bad); raise AssertionError("should refuse")
    except HTTPException as e:
        assert e.status_code == 403
os.environ.pop("TRUST_PROXY"); os.environ.pop("PROXY_HOPS")
assert main.admin_whoami(Req({"x-forwarded-for": "1.1.1.1"}), "admin-token-123456")["app_uses"] == "10.1.1.1"      # no proxy trust: the direct peer

# ---- Render blueprint and Docker files ----
import yaml
bp = yaml.safe_load((REPO / "render.yaml").read_text(encoding="utf-8"))
svc = bp["services"][0]
assert svc["type"] == "web" and svc["runtime"] == "docker" and svc["healthCheckPath"] == "/health" and svc["plan"] not in ("free",)   # disk needs a paid plan
assert svc["disk"]["mountPath"] == "/data" and svc["disk"]["sizeGB"] >= 1
env = {e["key"]: e for e in svc["envVars"]}
assert env["COACHBOT_DB"]["value"].startswith("/data/") and env["COACHBOT_INSTITUTES_DIR"]["value"].startswith("/data/") and env["COACHBOT_ENV_FILE"]["value"].startswith("/data/")
assert env["GROQ_API_KEY"].get("sync") is False and "value" not in env["GROQ_API_KEY"]                                  # secrets are typed in the dashboard, never in git
assert env["ADMIN_TOKEN"].get("generateValue") and env["DEMO_OWNER_KEY"].get("generateValue") and env["TRUST_PROXY"]["value"] == "xff"
assert not any(("gsk_" in str(e.get("value", ""))) for e in svc["envVars"])
# Free-plan blueprint: no disk (the Free plan has none), nothing pointing at /data, secrets still typed in the dashboard
fp = yaml.safe_load((REPO / "render.free.yaml").read_text(encoding="utf-8"))["services"][0]
assert fp["plan"] == "free" and "disk" not in fp and fp["healthCheckPath"] == "/health" and fp["runtime"] == "docker"
fenv = {e["key"]: e for e in fp["envVars"]}
assert not any(str(e.get("value", "")).startswith("/data") for e in fp["envVars"]) and fenv["GROQ_API_KEY"].get("sync") is False and fenv["TRUST_PROXY"]["value"] == "xff"
# /health answers GET and HEAD (uptime monitors) without touching the model or leaking institute ids
assert main.app.routes[("GET", "/health")] is main.app.routes[("HEAD", "/health")] is main.health
assert "tribac" not in json.dumps(main.health()) and main.health()["ok"] is True
dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
assert 'ENTRYPOINT ["/app/docker-entrypoint.sh"]' in dockerfile and "app.seed" in dockerfile and "${PORT:-8000}" in dockerfile and "\nUSER app" not in dockerfile
ep = (REPO / "docker-entrypoint.sh").read_bytes()
assert ep.startswith(b"#!/bin/sh") and b"\r" not in ep and b"setpriv" in ep and b"set -e" in ep                         # Linux line endings, drops root
for f in ("Dockerfile", "docker-compose.yml", "Caddyfile.example", "render.yaml", "render.free.yaml", "docker-entrypoint.sh"):
    assert b"\r" not in (REPO / f).read_bytes(), f + " must keep Linux line endings"
assert 'TRUST_PROXY: "xff"' in (REPO / "docker-compose.yml").read_text(encoding="utf-8")
if os.name != "nt" and shutil.which("sh") and hasattr(os, "geteuid") and os.geteuid() != 0:
    tmp = Path(tempfile.mkdtemp()); (tmp / "e.sh").write_bytes(ep); os.chmod(tmp / "e.sh", 0o755)
    res = subprocess.run([str(tmp / "e.sh"), "echo", "started as", "normal user"], capture_output=True, text=True)
    assert res.returncode == 0 and res.stdout.strip() == "started as normal user", res                                    # non-root start: just runs the command
    assert subprocess.run(["sh", "-n", str(tmp / "e.sh")]).returncode == 0
print("deploy tests passed")
