#!/usr/bin/env python3
"""ORBITclip shared per-user runtime. Standard library only."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import venv

BASE = Path(__file__).resolve().parent
REQ = BASE / "requirements-client.txt"
APP = BASE / "orbitclip.py"

def runtime_dir():
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "ORBITclip" / "venv"

VENV = runtime_dir()

def interpreter():
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

def run(args):
    subprocess.run(args, check=True, cwd=BASE)

def environment_compatible():
    cfg = VENV / "pyvenv.cfg"
    exe = interpreter()
    if not exe.is_file() or not cfg.is_file():
        return False
    # venv cannot survive incompatible interpreter ABI changes; fail safely.
    settings = cfg.read_text(encoding="utf-8", errors="replace")
    expected = f"version = {sys.version_info.major}.{sys.version_info.minor}."
    return expected in settings.lower()

def requirements_satisfied(python):
    """Check all requirement specifiers, not only module importability."""
    check = r"""
import json, pathlib, sys
from importlib import metadata
from pip._vendor.packaging.requirements import Requirement
req = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines()
missing = []
for raw in req:
    line = raw.strip()
    if not line or line.startswith('#'):
        continue
    requirement = Requirement(line)
    if requirement.marker and not requirement.marker.evaluate():
        continue
    try:
        version = metadata.version(requirement.name)
        if requirement.specifier and version not in requirement.specifier:
            missing.append(requirement.name)
    except metadata.PackageNotFoundError:
        missing.append(requirement.name)
print(json.dumps(missing))
sys.exit(bool(missing))
"""
    result = subprocess.run([str(python), "-c", check, str(REQ)], cwd=BASE,
                            capture_output=True, text=True)
    return result.returncode == 0

def main():
    print("ORBITclip — shared runtime launcher")
    print("Runtime:", VENV)
    if sys.version_info < (3, 10):
        print("Python 3.10+ required")
        return 1
    if not APP.is_file() or not REQ.is_file():
        print("Missing application or requirements")
        return 1
    exe = interpreter()
    if "--diagnose" in sys.argv:
        print("Environment compatible:", environment_compatible())
        print("Dependencies compatible:", requirements_satisfied(exe) if environment_compatible() else False)
        print("Old version-local .venv:", (BASE / ".venv").exists())
        return 0
    try:
        if exe.exists() and not environment_compatible():
            raise RuntimeError("Shared runtime was created with another Python version. "
                               "Repair it explicitly, rather than overwriting installed packages.")
        if not exe.exists():
            VENV.parent.mkdir(parents=True, exist_ok=True)
            print("[1/3] Creating shared runtime (once)...")
            venv.EnvBuilder(with_pip=True).create(str(VENV))
        if not requirements_satisfied(exe):
            print("[2/3] Synchronizing missing/outdated packages...")
            # pip already leaves satisfied packages untouched; no broad --upgrade.
            run([str(exe), "-m", "pip", "install", "--disable-pip-version-check",
                 "--prefer-binary", "-r", str(REQ)])
            if not requirements_satisfied(exe):
                raise RuntimeError("Dependency validation failed after installation")
        else:
            print("[2/3] All required packages already installed.")
        print("[3/3] Starting ORBITclip...")
        run([str(exe), str(APP)])
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print("ERROR:", exc)
        return 1

if __name__ == "__main__":
    sys.exit(main())
