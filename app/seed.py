"""Copy the institutes that ship with the code onto the persistent disk, once.

Used when COACHBOT_INSTITUTES_DIR points at a disk (for example /data/institutes on Render): the disk starts empty, so the
shipped demo institutes are copied in the first time. After that the disk copy is the real one: owners' edits and clients
you onboard live there and are never overwritten by a new deploy. Only institutes missing on the disk are added.
Runs automatically when the container starts; by hand: python -m app.seed"""
import shutil
from pathlib import Path

from . import registry


def seed(src=None, dst=None) -> list:
    src, dst = Path(src or registry.SHIPPED), Path(dst or registry.ROOT)
    if src.resolve() == dst.resolve():
        return []
    dst.mkdir(parents=True, exist_ok=True)
    added = []
    for d in sorted(src.iterdir()):
        if d.is_dir() and (d / "config.json").exists() and not (dst / d.name).exists():
            shutil.copytree(d, dst / d.name, ignore=shutil.ignore_patterns("history", "*.tmp"))
            added.append(d.name)
    return added


if __name__ == "__main__":
    done = seed()
    print(f"institutes folder: {registry.ROOT}" + (f"  added: {', '.join(done)}" if done else "  (nothing to add)"))
