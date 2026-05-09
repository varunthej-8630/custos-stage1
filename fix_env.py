import os
import shutil
import subprocess
import sys

def fix_everything():
    print("=======================================")
    print(" FIXING VIRTUAL ENVIRONMENT & COMPILER ")
    print("=======================================")
    
    print("\n[1/4] Deleting corrupted venv...")
    if os.path.exists("venv"):
        try:
            shutil.rmtree("venv")
            print("  -> Deleted.")
        except Exception as e:
            print(f"  -> Failed to delete venv: {e}")
            return
            
    print("\n[2/4] Creating fresh venv...")
    subprocess.check_call([sys.executable, "-m", "venv", "venv"])
    
    pip_exe = os.path.join("venv", "Scripts", "pip.exe")
    python_exe = os.path.join("venv", "Scripts", "python.exe")
    
    if not os.path.exists(pip_exe):
        print("  -> ensurepip failed. Manually downloading get-pip.py...")
        import urllib.request
        urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", "get-pip.py")
        subprocess.check_call([python_exe, "get-pip.py"])
        os.remove("get-pip.py")
    else:
        print("  -> venv created successfully with pip.")
        
    print("\n[3/4] Installing all packages into venv...")
    subprocess.check_call([python_exe, "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([pip_exe, "install", "-r", "requirements.txt"])
    
    print("\n[4/4] Upgrading PyInstaller compiler to latest version...")
    # Sometimes the dis.py tuple index out of range is a bug in pyinstaller parsing python 3.10 bytecode.
    # We ensure we have the absolute latest pyinstaller.
    subprocess.check_call([pip_exe, "install", "--upgrade", "pyinstaller"])
    
    print("\n=======================================")
    print(" ENVIRONMENT FULLY FIXED! ")
    print("=======================================")

if __name__ == "__main__":
    fix_everything()
