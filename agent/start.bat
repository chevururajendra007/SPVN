@echo off
REM Ask SPV - one-click start for Windows. Run from PowerShell with:  .\start.bat
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating Python environment...
  python -m venv .venv 2>nul || py -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo Python not found. Install Python 3.11+ from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)

echo [2/3] Installing packages (first run takes a few minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
if not exist ".env" copy ".env.example" ".env" >nul

echo [3/3] Starting Ask SPV... open http://localhost:8000  (Ctrl+C to stop)
".venv\Scripts\python.exe" -m uvicorn main:app --port 8000
