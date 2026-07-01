@echo off
REM Launch-FRIDAY.bat — FRIDAY V3 (RC1)
REM Double-click to start FRIDAY. Uses the provisioned .venv if present; otherwise the
REM bootstrap provisions it on first run. Pass-through args (e.g. --diagnostics) go to the
REM bootstrap/launcher.
setlocal
set "HERE=%~dp0"
if exist "%HERE%.venv\Scripts\python.exe" (
  "%HERE%.venv\Scripts\python.exe" "%HERE%deploy\bootstrap.py" %*
) else (
  where python >nul 2>nul && (
    python "%HERE%deploy\bootstrap.py" %*
  ) || (
    echo Python 3.10+ was not found on PATH. Install it from https://python.org and retry.
    pause
  )
)
endlocal
