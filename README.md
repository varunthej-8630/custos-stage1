<div align="center">
  <h1>🛡️ CUSTOS</h1>
  <p><b>Advanced AI Surveillance System & Asset Interaction Anomaly Detection</b></p>
  <p>
    <img src="https://img.shields.io/badge/Python-3.8%2B-blue" alt="Python">
    <img src="https://img.shields.io/badge/YOLOv8-Computer_Vision-orange" alt="YOLO">
    <img src="https://img.shields.io/badge/Platform-Windows-lightgrey" alt="Windows">
  </p>
</div>

## 📖 Overview

**Custos** is a state-of-the-art, local-first AI surveillance application designed to turn standard webcams and USB cameras into intelligent risk-assessment monitors. 

Unlike traditional passive cameras, Custos actively analyzes human movement using **YOLOv8**, tracks behavior across defined zones, detects camera tampering, and assigns real-time "Risk Scores" to active threats. All of this happens completely on your local machine, ensuring absolute privacy with zero cloud computing costs.

## ✨ Key Features

- **🧠 Real-Time YOLOv8 Inference:** Identifies and tracks individuals locally at high frame rates.
- **🎯 Dynamic Zone Defense:** Draw custom "High Security" or "Watch" zones directly on the video feed.
- **🕵️ Behavior Analytics:** Detects suspicious behavior such as lingering, crouching, running, or repeated visits.
- **🚨 Automated Risk Scoring:** Automatically scales the threat level from 0 to 100 based on complex behavioral heuristics.
- **🔒 Google Authentication:** Secure dashboard access via local admin credentials or Google OAuth.
- **☁️ Over-The-Air (OTA) Updates:** Built-in auto-updater seamlessly fetches and installs new versions.
- **📦 Standalone Application:** Can be built into a standalone `.exe` Windows desktop application (no Python required).

---

## 🛠️ Technology Stack

- **Backend Logic:** Python, OpenCV, PyTorch, Ultralytics (YOLO)
- **Web Server:** Flask, Flask-SocketIO, Authlib (Google OAuth)
- **Frontend Dashboard:** HTML, CSS, Vanilla JavaScript
- **Packaging:** PyInstaller (`--onedir` optimization for instant boot times)

---

## 🚀 Quick Start (Development)

If you are a developer and want to run Custos from the source code:

1. **Clone the repository:**
   ```bash
   git clone https://github.com/varunthej-8630/custos-stage1.git
   cd custos-stage1
   ```
2. **Run the automated setup:**
   Double-click the `setup.bat` file in Windows. This will automatically:
   - Create a Python virtual environment.
   - Install all required dependencies from `requirements.txt`.
   - Start the server and launch the web dashboard on `http://localhost:5000`.

---

## 🔐 Setup Google Authentication

Custos includes secure login functionality. To enable Google Sign-In:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a project.
2. Generate an OAuth 2.0 Client ID (Web Application type).
3. Set your Authorized Redirect URI to: `http://localhost:5000/auth/callback`
4. Create a `.env` file in the root directory and add your keys:
   ```env
   GOOGLE_CLIENT_ID=your_google_client_id
   GOOGLE_CLIENT_SECRET=your_google_client_secret
   CUSTOS_USER=admin
   CUSTOS_PASS=your_custom_password
   ```

---

## 📦 Building for Distribution (.exe)

You can package Custos into a single, standalone Windows application so that other users do not need to install Python.

1. Double-click the **`build.bat`** file.
2. The script will automatically install PyInstaller, compile the source code, bundle the AI models, and generate the application.
3. Once complete, navigate to the **`dist/Custos`** folder. 
4. You can zip the `Custos` folder and send it to anyone. They only need to run `Custos.exe`!

---

## 🔄 Auto-Updater System

Custos is equipped with a self-updating mechanism. Upon startup, it checks a remote `version.json` payload. If an update is detected, it prompts the user, downloads the package in the background, applies the patch, and restarts the application automatically.

*(To configure the update URL, edit `UPDATE_URL` in `config/settings.py`)*

---

*Built with precision for uncompromised local security.*
