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
    echo [INFO] Python is missing. Downloading Python 3.10 automatically...
    curl -o python_installer.exe https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe
    echo [INFO] Installing Python - Please click 'Yes' if Windows asks for permission...
    python_installer.exe /passive InstallAllUsers=0 PrependPath=1 Include_test=0 Include_doc=0
    echo [INFO] Python installed successfully! 
    echo [INFO] IMPORTANT: Please CLOSE this window and double-click setup.bat again to start the app.
    pause
    exit /b
)

:: We bypass the virtual environment (venv) entirely because some Windows
:: installations have a broken venv module that fails to install pip.
:: Instead, we install dependencies directly to the user's main Python.

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
