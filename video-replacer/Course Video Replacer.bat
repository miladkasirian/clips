@echo off
rem  The app. Uses the voice environment if it is there, so a cloned voice works.
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.pyw"
) else (
  start "" pythonw "%~dp0app.pyw"
)
