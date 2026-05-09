import os
import sys
import subprocess
import shutil

def download_yolo_weights():
    weights_dir = os.path.join('data', 'weights')
    weights_path = os.path.join(weights_dir, 'yolov8n.pt')
    os.makedirs(weights_dir, exist_ok=True)
    if not os.path.exists(weights_path):
        print("[BUILD] Downloading YOLOv8 weights...")
        # Ultralytics auto-downloads if we import and initialize
        try:
            from ultralytics import YOLO
            YOLO('yolov8n.pt')
            # Move it to data/weights if it downloaded to root
            if os.path.exists('yolov8n.pt'):
                shutil.move('yolov8n.pt', weights_path)
        except Exception as e:
            print(f"[BUILD] Warning: Could not pre-download weights: {e}")

def build():
    print("=======================================")
    print(" Building Custos Windows Application ")
    print("=======================================")
    
    # 1. Install PyInstaller
    print("\n[1/3] Installing PyInstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # 2. Prepare files (Ensure YOLO weights exist)
    print("\n[2/3] Preparing assets...")
    download_yolo_weights()
    
    # 3. Run PyInstaller
    print("\n[3/3] Running PyInstaller (This may take 3-5 minutes)...")
    
    # --- PYINSTALLER CRASH WORKAROUND ---
    # PyTorch and Ultralytics are so large they crash the PyInstaller bytecode analyzer.
    # We fix this by excluding them from analysis and copying their raw folders directly!
    import torch
    import ultralytics
    import authlib
    import cryptography
    
    torch_path = os.path.dirname(torch.__file__)
    ultra_path = os.path.dirname(ultralytics.__file__)
    auth_path = os.path.dirname(authlib.__file__)
    crypto_path = os.path.dirname(cryptography.__file__)
    
    import PyInstaller.__main__
    
    args = [
        'run_server.py',
        '--name=Custos',
        '--onedir', 
        '--noconfirm',
        '--clean',
        
        # Bypass Compiler crash for large/complex modules
        '--exclude-module=torch',
        '--exclude-module=ultralytics',
        '--exclude-module=authlib',
        '--exclude-module=cryptography',
        f'--add-data={torch_path};torch',
        f'--add-data={ultra_path};ultralytics',
        f'--add-data={auth_path};authlib',
        f'--add-data={crypto_path};cryptography',
        
        # Add frontend HTML/JS/CSS
        '--add-data=frontend;frontend',
        
        # Add Configs and ENV
        '--add-data=config;config',
        '--add-data=.env;.', 
        
        # Add YOLO Weights
        '--add-data=data/weights;data/weights',
        
        # Hidden imports (Sometimes PyInstaller misses dynamic imports)
        '--hidden-import=engine.detector',
        '--hidden-import=engine.tracker',
        '--hidden-import=engine.zone_monitor',
        '--hidden-import=engine.risk_engine',
        '--hidden-import=web.alert_manager',
        '--hidden-import=updater',
        '--hidden-import=authlib.integrations.flask_client',
        '--hidden-import=flask_socketio',
        '--hidden-import=engine_io.async_drivers.threading',
        
        # Suppress terminal window (Optional: remove this if you want to see the command prompt console)
        # '--noconsole', 
    ]
    
    PyInstaller.__main__.run(args)
    
    print("\n=======================================")
    print(" BUILD COMPLETE! ")
    print(" Your application is located in the 'dist/Custos' folder.")
    print(" To run it, double click: dist/Custos/Custos.exe")
    print(" To distribute it to others, zip the entire 'dist/Custos' folder and send it to them.")
    print("=======================================")

if __name__ == '__main__':
    build()
