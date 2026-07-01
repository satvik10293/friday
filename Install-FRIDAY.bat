@echo off
REM Install-FRIDAY.bat - FRIDAY V3 (RC1)
REM Double-click to install FRIDAY. Runs the PowerShell installer (no external tooling
REM required): copies files, provisions an isolated .venv, and creates shortcuts.
setlocal
set "HERE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%deploy\windows\install.ps1" %*
if errorlevel 1 (
  echo.
  echo Installation did not complete. See messages above.
  pause
)
endlocal
