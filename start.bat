@echo off
setlocal
cd /d "%~dp0"

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8770"

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY (
  where python >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  where py >nul 2>&1
  if not errorlevel 1 set "PY=py"
)
if not defined PY (
  echo [SUNLOOM] Python not found.
  echo Install Python 3.10+ first, then run: install\install.ps1
  pause
  exit /b 1
)

"%PY%" -c "import sys" >nul 2>&1
if errorlevel 1 (
  echo [SUNLOOM] Python found but cannot run: %PY%
  pause
  exit /b 1
)

"%PY%" -c "import uvicorn, fastapi, PIL" >nul 2>&1
if errorlevel 1 (
  echo [SUNLOOM] Python packages are missing for: %PY%
  echo.
  choice /c YN /m "Install requirements now"
  if errorlevel 2 (
    echo Install cancelled. Run: "%PY%" -m pip install -r requirements.txt
    pause
    exit /b 1
  )
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [SUNLOOM] pip install failed. Check the error above.
    pause
    exit /b 1
  )
)

if not exist "station\data\config.json" (
  echo [SUNLOOM] station\data\config.json is missing.
  echo Run install\install.ps1 once to bind ComfyUI and your model.
  echo Starting anyway - the UI will open, generation will fail until you bind.
  echo.
)

echo [SUNLOOM] starting on http://127.0.0.1:%PORT%/
start "" "http://127.0.0.1:%PORT%/"
cd station
"%PY%" -m uvicorn server:app --host 127.0.0.1 --port %PORT%
echo.
echo [SUNLOOM] server stopped. press any key to close.
pause >nul
