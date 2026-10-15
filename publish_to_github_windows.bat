@echo off
cd /d "%~dp0"
py -3 publish_first_time.py
if errorlevel 1 pause
