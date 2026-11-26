"""Runs the owner page in a simulated browser (needs node; skipped if node is not installed). Run: python -m tests.test_owner_page"""
import pathlib
import subprocess

try:
    r = subprocess.run(["node", str(pathlib.Path(__file__).with_name("owner_sim.js"))], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    print(r.stdout.strip())
except FileNotFoundError:
    print("owner page test skipped: node is not installed")
