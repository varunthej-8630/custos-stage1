# Custos - AI Surveillance System

Custos is a state-of-the-art AI-powered surveillance system that turns standard camera feeds into intelligent risk-assessment monitors. Utilizing YOLOv8 object detection, dynamic zone tracking, and an automated risk scoring engine, Custos tracks individual movement, identifies suspicious patterns (like loitering or crouching), detects camera tampering, and sends real-time alerts. It is designed to act as a tireless, automated guard for your critical assets.

## Requirements

- **OS:** Windows 10/11
- **Python:** 3.8 to 3.11 (Python 3.12+ might have issues with some OpenCV/Torch dependencies)
- **Camera:** Built-in webcam or external USB camera

## Folder Structure

- `run_server.py`: Main entry point to launch the web dashboard and AI backend.
- `run_debug.py`: Standalone CLI script to test AI logic without the web UI.
- `config/`: System settings and environment variables.
- `engine/`: The core AI, tracking, and risk assessment logic.
- `web/`: The web server (Flask) and alert management.
- `frontend/`: Web dashboard HTML/CSS/JS.
- `data/`: Local data, including YOLO weights (`weights/`) and video evidence (`snapshots/`).
- `docs/`: Project documentation and logs.

## Setup and Installation (Windows)

1. **Install Python:** Ensure Python is installed and added to your system PATH.
2. **Setup File:** Double click the `setup.bat` file in the main folder.
   - This script will automatically create a virtual environment.
   - It will install all dependencies from `requirements.txt`.
   - It will start the web server and open the Custos dashboard in your browser.

*Alternatively, install manually:*
```cmd
pip install -r requirements.txt
python run_server.py
```

## Running on Startup (Windows Task Scheduler)

To make Custos start automatically when the computer turns on without requiring a user to log in:

1. Press `Win + R`, type `taskschd.msc`, and hit Enter.
2. Click **Create Task** on the right panel.
3. **General Tab:**
   - Name: `Custos AI Surveillance`
   - Select **"Run whether user is logged on or not"**
   - Check **"Run with highest privileges"**
4. **Triggers Tab:**
   - Click **New...**
   - Begin the task: **"At startup"**
   - Click OK.
5. **Actions Tab:**
   - Click **New...**
   - Action: **"Start a program"**
   - Program/script: `cmd.exe`
   - Add arguments: `/c "C:\Path\To\custos-AD-main\setup.bat"` (Replace with your actual folder path)
6. **Conditions Tab:**
   - Uncheck "Stop if the computer switches to battery power" (if applicable).
7. Click **OK**, and enter your Windows administrator password when prompted.

Custos will now run automatically in the background whenever the PC turns on.
