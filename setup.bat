@echo off
setlocal
echo ====================================================
echo Live MT5 Dashboard - Setup Script
echo ====================================================

:: 1. Check if Python is installed
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Please install Python from python.org
    pause
    exit /b 1
)

:: 2. Create Virtual Environment
if not exist ".venv" (
    echo [INFO] Creating virtual environment...
    python -m venv .venv
) else (
    echo [INFO] Virtual environment already exists.
)

:: 3. Install Dependencies
echo [INFO] Installing required packages...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo [SUCCESS] Setup complete!
echo Use 'run.bat' to start the server.
echo.
pause
