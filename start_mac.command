#!/bin/bash
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3.10+ was not found. Please install Python first."
    read -r -p "Press Enter to close..." _
    exit 1
fi
python3 launcher.py
status=$?
if [ "$status" -ne 0 ]; then
    echo ""
    echo "ORBITclip did not start. See the error above."
    read -r -p "Press Enter to close..." _
fi
exit "$status"
