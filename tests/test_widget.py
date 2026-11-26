"""Runs the widget in a simulated browser (needs node; skipped if node is not installed). Run: python -m tests.test_widget"""
import pathlib
import subprocess

try:
    r = subprocess.run(["node", str(pathlib.Path(__file__).with_name("widget_sim.js"))], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    print(r.stdout.strip())
except FileNotFoundError:
    print("widget test skipped: node is not installed")
