import os
import sys
import time
import requests
import zipfile
import threading
from urllib.request import urlretrieve
import urllib.error
from config import settings as config

def check_and_apply_updates():
    """
    Checks the remote UPDATE_URL for a newer version of the application.
    If found, prompts the user to update. If they accept, downloads, extracts,
    and applies the update automatically using a batch script, then restarts.
    """
    print(f"[UPDATER] Checking for updates at {config.UPDATE_URL}...")
    try:
        response = requests.get(config.UPDATE_URL, timeout=5)
        if response.status_code == 200:
            data = response.json()
            remote_version = data.get("version")
            download_url = data.get("download_url")
            
            # Simple string comparison for versions (e.g., "1.0.1" > "1.0.0")
            # In a real app, you might want to use pkg_resources.parse_version
            if remote_version and remote_version > config.APP_VERSION:
                print(f"[UPDATER] Update available! {config.APP_VERSION} -> {remote_version}")
                _prompt_user_for_update(remote_version, download_url)
            else:
                print("[UPDATER] You are on the latest version.")
        else:
            print(f"[UPDATER] Failed to check for updates. Status code: {response.status_code}")
    except requests.RequestException as e:
        print(f"[UPDATER] Could not connect to update server (offline or unavailable).")
    except Exception as e:
        print(f"[UPDATER] Error checking for updates: {e}")

def _prompt_user_for_update(remote_version, download_url):
    import tkinter as tk
    from tkinter import messagebox
    
    root = tk.Tk()
    root.withdraw() # Hide the main window
    root.attributes("-topmost", True) # Ensure popup is in front
    
    msg = f"A new version of Custos ({remote_version}) is available!\n\nWould you like to download and install it now?"
    result = messagebox.askyesno("Custos Update Available", msg, parent=root)
    
    if result:
        root.destroy()
        _perform_update(download_url)
    else:
        root.destroy()
        print("[UPDATER] User declined the update.")

def _perform_update(download_url):
    import tkinter as tk
    from tkinter import ttk
    
    root = tk.Tk()
    root.title("Custos Updater")
    root.geometry("350x120")
    root.attributes("-topmost", True)
    
    # Center the window
    root.eval('tk::PlaceWindow . center')
    
    label = tk.Label(root, text="Downloading update, please wait...", font=("Arial", 10))
    label.pack(pady=15)
    
    progress = ttk.Progressbar(root, orient='horizontal', length=280, mode='determinate')
    progress.pack()
    
    def download_thread():
        zip_path = "update_temp.zip"
        try:
            def report_hook(count, block_size, total_size):
                if total_size > 0:
                    percent = int(count * block_size * 100 / total_size)
                    # Don't let it exceed 100% due to block sizes
                    progress['value'] = min(percent, 100)
                    root.update_idletasks()

            urlretrieve(download_url, zip_path, reporthook=report_hook)
            label.config(text="Extracting new files...")
            root.update_idletasks()
            
            # Extract zip
            extract_dir = "update_extracted"
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
                
            label.config(text="Applying changes & restarting...")
            root.update_idletasks()
            
            # Create a batch file to replace files and restart
            # This batch file will wait 2 seconds, copy files, clean up, and restart the app.
            bat_path = "apply_update.bat"
            with open(bat_path, "w") as f:
                f.write('@echo off\n')
                f.write('echo Applying Custos Update...\n')
                f.write('timeout /t 2 /nobreak > NUL\n') # wait for python to completely close
                f.write('xcopy /s /y /q "update_extracted\\*" .\\\n') # copy new files over old files
                f.write('rmdir /s /q "update_extracted"\n') # remove temp folder
                f.write('del "update_temp.zip"\n') # remove zip
                
                # Command to restart. For source it's python run_server.py.
                # If we build an .exe later, this string will need to point to the .exe
                if getattr(sys, 'frozen', False):
                    # We are running as an .exe
                    exe_name = os.path.basename(sys.executable)
                    f.write(f'start "" "{exe_name}"\n')
                else:
                    # We are running from source
                    f.write('start "" "setup.bat"\n') 
                    
                f.write('del "%~f0"\n') # self-delete the batch script
            
            # Launch the batch script independently and exit the current Python process
            import subprocess
            subprocess.Popen(bat_path, shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
            os._exit(0)
            
        except urllib.error.URLError as e:
            label.config(text=f"Network error: Could not download update.", fg="red")
        except Exception as e:
            label.config(text=f"Update failed: {str(e)[:40]}", fg="red")
            
        # If it failed, wait a few seconds so user can read error, then destroy window and continue app
        time.sleep(4)
        root.destroy()

    threading.Thread(target=download_thread, daemon=True).start()
    root.mainloop()

if __name__ == "__main__":
    check_and_apply_updates()
