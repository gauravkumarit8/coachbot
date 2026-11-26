"""Runs every offline test file and prints one line each. Usage: python -m tests.run_all   (no API key or internet needed)"""
import pathlib
import subprocess
import sys

names = sorted(p.stem for p in pathlib.Path(__file__).parent.glob("test_*.py"))
failed = []
for n in names:
    r = subprocess.run([sys.executable, "-m", f"tests.{n}"], capture_output=True, text=True)
    last = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
    print(("PASS " if r.returncode == 0 else "FAIL ") + f"{n:28} {last}")
    if r.returncode:
        failed.append(n)
        print((r.stdout[-800:] + r.stderr[-1500:]).strip())
print(f"\n{len(names) - len(failed)}/{len(names)} test files passed")
sys.exit(1 if failed else 0)
