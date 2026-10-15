"""Move known legacy logs only after this installation's HMI is stopped."""
import argparse
import os
import re
import uuid
from pathlib import Path

from log_config import APP_BASE, LOG_MAX_BYTES


def active_writers(base):
    paths = {str(Path(base).resolve() / name) for name in ("hmi.py", "launch_hmi.py")}
    log_pattern = re.compile(r"(coolshift_hmi|hmi_startup)\.log(?:\.\d+)?$")
    found = set()
    for process in Path("/proc").iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            args = (process / "cmdline").read_bytes().split(b"\0")
            cwd = (process / "cwd").resolve()
            if any(str((cwd / os.fsdecode(arg)).resolve()) in paths
                   for arg in args[1:] if arg):
                found.add(int(process.name))
            for fd in (process / "fd").iterdir():
                try:
                    target = fd.resolve()
                    if target.parent == Path(base).resolve() and log_pattern.fullmatch(target.name):
                        found.add(int(process.name))
                except OSError:
                    continue
        except (OSError, PermissionError):
            continue
    return sorted(found)


def migrate(base=APP_BASE):
    base = Path(base).resolve()
    writers = active_writers(base)
    if writers:
        raise RuntimeError(f"Stop acuPilot HMI/log writers first: {writers}")
    destination = base / "Logs"
    destination.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(r"(coolshift_hmi|hmi_startup)\.log(?:\.\d+)?$")
    moved = []
    for source in sorted(base.iterdir()):
        if not pattern.fullmatch(source.name) or not source.is_file():
            continue
        target = destination / source.name
        if target.exists() or (source.name.startswith("hmi_startup")
                               and source.stat().st_size >= LOG_MAX_BYTES):
            archive = destination / "legacy"
            archive.mkdir(exist_ok=True)
            target = archive / f"{source.name}.{uuid.uuid4().hex}.log"
        size = source.stat().st_size
        # Same-filesystem hard link is atomic and refuses destination overwrite.
        os.link(source, target)
        if target.stat().st_size != size or source.stat().st_size != size:
            target.unlink()
            raise RuntimeError(f"Log changed during migration; source retained: {source}")
        source.unlink()
        moved.append((source, target, size))
        print(f"acuPilot migrated {source.name} -> {target} ({size} bytes)")
    if not moved:
        print("acuPilot: no legacy root logs to migrate")
    return moved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate stopped acuPilot HMI logs")
    parser.add_argument("--base", type=Path, default=APP_BASE)
    args = parser.parse_args()
    try:
        migrate(args.base)
    except (OSError, RuntimeError) as exc:
        parser.exit(1, f"acuPilot migration aborted: {exc}\n")
