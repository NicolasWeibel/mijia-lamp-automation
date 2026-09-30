@echo off
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%runtime\python.exe"
set "PYW=%ROOT%runtime\pythonw.exe"
if not exist "%PY%" set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PYW%" set "PYW=%ROOT%.venv\Scripts\pythonw.exe"
if not exist "%PY%" (
  echo MijiaLamp Portable no esta preparado. Ejecuta setup-portable.ps1.
  exit /b 2
)
if not exist "%PYW%" (
  echo MijiaLamp Portable no esta preparado. Ejecuta setup-portable.ps1.
  exit /b 2
)
"%PY%" "%ROOT%lampctl.py" --mode portable runtime-status >nul 2>&1
if %errorlevel% equ 0 (
  echo MijiaLamp Portable ya esta ejecutandose.
  exit /b 0
)
start "" "%PYW%" "%ROOT%portable.py"
