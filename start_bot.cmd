@echo off
cd /d "%~dp0"
python -m uv run python bot_launcher.py
if errorlevel 1 pause
