@echo off
TITLE Custos App Builder
COLOR 0B
echo ===================================================
echo             CUSTOS AI BUILDER
echo ===================================================
echo.

IF NOT EXIST "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Please run setup.bat first!
    pause
    exit /b
)

echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

echo [INFO] Starting build process...
python build.py

echo.
echo [INFO] Process complete. Check the "dist/Custos" folder!
pause
