@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 "%~dp0apply_patch.py" %*
) else (
    python "%~dp0apply_patch.py" %*
)
echo.
pause
