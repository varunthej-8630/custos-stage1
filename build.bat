@echo off
TITLE Custos App Builder
COLOR 0B
echo ===================================================
echo             CUSTOS AI BUILDER
echo ===================================================
echo.

IF NOT EXIST "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Creating one...
    python -m venv venv
)

echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

echo [INFO] Installing required dependencies...
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt

echo [INFO] Starting PyInstaller build process...
python build.py

echo.
echo [INFO] Process complete. Check the "dist/Custos" folder!
pause
