@echo off
setlocal EnableDelayedExpansion
title VanishCam - Universal All-In-One Launcher

cd /d "%~dp0"
set "VENV_PY=%~dp0.venv-local\Scripts\python.exe"

if not exist "%VENV_PY%" (
  echo [ERROR] Python environment not found at:
  echo %VENV_PY%
  pause
  exit /b 1
)

:menu
cls
echo ===================================================================
echo             VANISHCAM - UNIVERSAL ALL-IN-ONE LAUNCHER
echo ===================================================================
echo.
echo   ALL MEMES ARE ACTIVE SIMULTANEOUSLY IN THE SAME SESSION:
echo     * Goku Instant Transmission : 2 fingers to forehead / temple
echo     * Naruto Substitution       : Join hands together (jutsu pose)
echo     * Normal Vanish             : Peace sign (V-sign)
echo.
echo   IN-APP CONTROLS:
echo     [1] Normal Vanish    [2] Naruto Jutsu    [3] Goku Teleport
echo     [R] Reappear         [C] Switch Camera   [SPACE] New Background
echo.
echo   -----------------------------------------------------------------
echo   [1] ALL-IN-ONE (Universal Mode) - Camera 0 (Default - Recommended)
echo   [2] ALL-IN-ONE (Universal Mode) - Camera 1
echo   -----------------------------------------------------------------
echo   [3] OBS Studio Mode (No Virtual Camera) - Camera 0
echo   [4] Visual Selection Menu (Single mode picker)
echo   [C] Custom Camera Index Prompt
echo   [Q] Quit
echo.
echo ===================================================================
echo Press 1-4, C, or Q (Auto-starts [1] Universal Mode in 5 seconds)...

choice /C 1234CQ /D 1 /T 5 /N /M "Select option: "
set choice_level=%errorlevel%

if "%choice_level%"=="6" exit /b 0

if "%choice_level%"=="5" (
  set /p cam_idx="Enter camera index (0, 1, 2, ...): "
  if "!cam_idx!"=="" set cam_idx=0
  echo Launching All-In-One Universal Mode on Camera !cam_idx!...
  "%VENV_PY%" "%~dp0local_app\vanish_cam.py" --mode all --camera !cam_idx!
  goto end
)

if "%choice_level%"=="4" (
  echo Launching Visual Selection Menu...
  "%VENV_PY%" "%~dp0local_app\vanish_cam.py" --menu --camera 0
  goto end
)

if "%choice_level%"=="3" (
  echo Starting All-In-One for OBS Window Capture on Camera 0...
  "%VENV_PY%" "%~dp0local_app\vanish_cam.py" --mode all --no-virtual-camera --camera 0
  goto end
)

if "%choice_level%"=="2" (
  echo Starting All-In-One Universal Mode on Camera 1...
  "%VENV_PY%" "%~dp0local_app\vanish_cam.py" --mode all --camera 1
  goto end
)

if "%choice_level%"=="1" (
  echo Starting All-In-One Universal Mode on Camera 0...
  "%VENV_PY%" "%~dp0local_app\vanish_cam.py" --mode all --camera 0
  goto end
)

:end
if %errorlevel% neq 0 (
  echo.
  echo Camera closed or exited.
  pause
)
