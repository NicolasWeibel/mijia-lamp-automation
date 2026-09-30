@echo off
set "PY=%~dp0runtime\python.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (echo Ejecuta setup-portable.ps1 primero.& exit /b 2)
"%PY%" "%~dp0sleepnow.py" --mode portable
