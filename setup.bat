@echo off
TITLE Custos AI Setup and Runner
COLOR 0A

echo ===================================================
echo             CUSTOS AI SURVEILLANCE
echo ===================================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not in your PATH.
    echo Please install Python 3.8 - 3.11 from python.org
    pause
    exit /b
)

:: Check if venv exists, if not create it
IF NOT EXIST "venv\Scripts\activate.bat" (
    echo [INFO] Creating Python virtual environment...
    python -m venv venv
)

:: Activate venv
call venv\Scripts\activate.bat

:: Upgrade pip and install requirements
echo [INFO] Checking dependencies...
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt

:: Start the application
echo [INFO] Starting Custos Web Server...
echo [INFO] Keep this window open to run the AI engine.

:: Wait 2 seconds then open browser
timeout /t 2 /nobreak >nul
start http://localhost:5000

:: Run the server
python run_server.py

pause
