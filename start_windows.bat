@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 launcher.py
    goto :done
)
where python >nul 2>nul
if not errorlevel 1 (
    python launcher.py
    goto :done
)
echo Python was not found. Install Python 3.10+ from python.org and check Add to PATH.
set "result=1"
goto :finish
:done
set "result=%errorlevel%"
:finish
if not "%result%"=="0" (
    echo.
    echo ORBITclip could not start. See the error above.
    pause
)
exit /b %result%
