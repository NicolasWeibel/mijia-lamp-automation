@echo off
set "PY=%~dp0runtime\python.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"
"%PY%" "%~dp0lampctl.py" manual-on
pause
