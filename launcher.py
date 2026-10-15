#!/usr/bin/env python3
"""ORBITclip one-click launcher; Python standard library only.

Creates a private virtualenv, installs missing packages once, then starts the app.
Use '--diagnose' to print environment state without installing packages.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv

BASE = Path(__file__).resolve().parent
REQ = BASE / "requirements-client.txt"
APP = BASE / "orbitclip.py"
VENV = BASE / ".venv"
MARK = VENV / ".orbitclip_installed.sha256"
NEEDED = ("PySide6", "cryptography", "certifi", "pynput")


def interpreter() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(args: list[str], **kwargs) -> None:
    # Check return codes; give real messages on failure.
    subprocess.run(args, check=True, cwd=BASE, **kwargs)


def modules_available(python: Path) -> bool:
    code = "import importlib.metadata as m; " + "; ".join(f"m.version({p!r})" for p in NEEDED)
    return subprocess.run([str(python), "-c", code], cwd=BASE,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def main() -> int:
    print("ORBITclip — launcher")
    print("Python:", sys.version.split()[0], "|", sys.executable)
    if sys.version_info < (3, 10):
        print("ERROR: Python 3.10 or newer is required.")
        return 1
    if not APP.exists() or not REQ.exists():
        print("ERROR: orbitclip.py or requirements-client.txt missing.")
        return 1
    vpy = interpreter()
    if "--diagnose" in sys.argv:
        print("Client:", APP)
        print("Requirements:", REQ)
        print("Virtual environment:", VENV)
        print("Environment exists:", vpy.is_file())
        if vpy.is_file():
            print("Dependencies installed:", modules_available(vpy))
        return 0
    expected = hashlib.sha256(REQ.read_bytes()).hexdigest()
    try:
        if not vpy.is_file():
            print("[1/3] Creating a private Python environment...")
            venv.EnvBuilder(with_pip=True).create(str(VENV))
        if not vpy.is_file():
            print("ERROR: could not create .venv; check your Python installation.")
            return 1
        installed = MARK.read_text(encoding="ascii").strip() if MARK.is_file() else ""
        if expected != installed or not modules_available(vpy):
            print("[2/3] Installing ORBITclip dependencies (requires internet on first run)...")
            run([str(vpy), "-m", "pip", "install", "--disable-pip-version-check", "--prefer-binary", "-r", str(REQ)])
            if not modules_available(vpy):
                print("ERROR: dependency check failed after pip installation.")
                return 1
            MARK.write_text(expected, encoding="ascii")
        else:
            print("[2/3] Dependencies are already installed.")
        print("[3/3] Starting ORBITclip...")
        # Keep the launcher process and its window open if Python crashes.
        run([str(vpy), str(APP)])
        return 0
    except (OSError, subprocess.CalledProcessError) as exc:
        print("\nERROR:", exc)
        print("Check ~/.orbitclip_crash.log if the application itself failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
