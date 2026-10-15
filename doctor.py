"""Start with: py doctor.py (Windows) or python3 doctor.py (Mac/Linux)."""
import importlib
import platform
import sys
import traceback
from pathlib import Path

log=Path.home()/'.orbitclip_crash.log'
print('ORBITclip client diagnostics')
print('Platform:',platform.platform())
print('Python:',sys.version)
print('Executable:',sys.executable)
print('Crash log:',log)
for name in ('PySide6','cryptography','certifi','pynput'):
    try:
        m=importlib.import_module(name)
        print(name,'OK',getattr(m,'__version__','installed'))
    except Exception as exc:
        print(name,'ERROR:',repr(exc))
        traceback.print_exc()
try:
    from PySide6.QtWidgets import QApplication
    app=QApplication([])
    print('Qt GUI startup: OK; platform =',app.platformName())
except Exception as exc:
    print('Qt GUI startup FAILED:',repr(exc))
    traceback.print_exc()
if log.exists():
    print('\nLast crash log lines:')
    print('\n'.join(log.read_text(encoding='utf-8',errors='replace').splitlines()[-30:]))
