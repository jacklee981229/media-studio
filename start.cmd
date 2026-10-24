@echo off
rem Double-click to open Media Studio. It runs in the background and stops by itself 10 minutes after its window closes.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" main.py
