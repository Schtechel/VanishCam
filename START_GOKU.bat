@echo off
setlocal
cd /d "%~dp0"
set "VENV_PY=%~dp0.venv-local\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo Error: Python virtual environment not found at %VENV_PY%.
  pause
  exit /b 1
)
echo [VanishCam] Starting Goku Instant Transmission Mode...
"%VENV_PY%" "%~dp0local_app\vanish_cam.py" --mode goku %*
if errorlevel 1 pause
