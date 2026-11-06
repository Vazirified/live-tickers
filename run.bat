@echo off
setlocal
echo ====================================================
echo Starting Live MT5 Dashboard Server...
echo ====================================================

if not exist ".venv" (
    echo [ERROR] Virtual environment not found. Please run 'setup.bat' first.
    pause
    exit /b 1
)

:: Activate the virtual environment and start the server
call .venv\Scripts\activate.bat
python ticker-back.py

pause
