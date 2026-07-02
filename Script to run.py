import os
import sys
import subprocess

# --- DEPENDENCY RESOLUTION ---
def ensure_dependencies():
    """Dynamically installs required external modules if absent."""
    required_packages = {
        "pyperclip": "pyperclip",
        "pyvda": "pyvda",
        "keyboard": "keyboard"
    }
    for module, package in required_packages.items():
        try:
            __import__(module)
        except ImportError:
            print(f"[*] Installing missing dependency: {package}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

ensure_dependencies()

import datetime
import time
import urllib.request
import json
import winreg
import ctypes
import pyperclip
import pyvda
import keyboard

# --- CONFIGURATION ---
GRID_SIZE = 4
PHYSICAL_WIDTH = 393   # The actual space the window will occupy on screen
PHYSICAL_HEIGHT = 1040 # The actual height the window will occupy on screen
SCALE_FACTOR = 0.5     # Renders at 50% resolution to save GPU resources

# Calculates the required logical dimensions to offset the scale factor
LOGICAL_WIDTH = int(PHYSICAL_WIDTH / SCALE_FACTOR)
LOGICAL_HEIGHT = int(PHYSICAL_HEIGHT / SCALE_FACTOR)

UA_ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_DIR = os.path.join(SCRIPT_DIR, "manifests")
os.makedirs(MANIFEST_DIR, exist_ok=True)

# --- OPTIMIZATION FLAGS ---
OPTIMIZATION_FLAGS = [
    "--disable-frame-rate-limit",
    "--disable-gpu-vsync",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--enable-gpu",
    "--enable-webgl",
    "--enable-gpu-rasterization",
    "--enable-gpu-compositing",
    "--enable-features=Touch,PointerEvent,MobileLayout",
    "--disable-extensions",
]

def find_chrome_executable():
    """Queries Windows Registry and standard directories to locate chrome.exe."""
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe")
        path, _ = winreg.QueryValueEx(key, "")
        return path
    except Exception:
        standard_paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")
        ]
        for p in standard_paths:
            if os.path.exists(p):
                return p
    return None

def toggle_display_off():
    """Utilizes Win32 API to power down the monitor without suspending the system or GPU."""
    print("[*] Display off signal sent. Press any key or move the mouse to wake.")
    ctypes.windll.user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)

def save_run_manifest(run_id, url, profiles):
    path = os.path.join(MANIFEST_DIR, f"{run_id}.json")
    data = {
        "run_id": run_id,
        "url": url,
        "created_at": datetime.datetime.now().isoformat(),
        "profiles": profiles,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def get_ip():
    try:
        return urllib.request.urlopen('https://api.ipify.org', timeout=10).read().decode('utf8')
    except Exception as e:
        print(f"Error fetching IP: {e}")
        return None

def create_and_switch_desktop():
    try:
        new_desktop = pyvda.VirtualDesktop.create()
        new_desktop.go()
        return True
    except:
        return False

def launch_grid():
    browser_path = find_chrome_executable()
    if not browser_path:
        print("[!] Error: Chrome executable not found on this system.")
        return

    print("[*] Launching Chromium (High FPS, Low Resource & Background Persistence Mode)...")
    
    # URL Input Handling
    invitation_link = pyperclip.paste().strip()
    if not invitation_link or not invitation_link.startswith("http"):
        invitation_link = input("[*] No valid URL found in clipboard. Please enter the target URL: ").strip()
        
        if invitation_link and not invitation_link.startswith("http"):
            invitation_link = "https://" + invitation_link
            
        if not invitation_link:
            print("[!] Error: A valid URL is required to proceed. Terminating.")
            return

    print(f"[*] Validated Link: {invitation_link}")
    create_and_switch_desktop()

    used_ips = set()
    
    for i in range(GRID_SIZE):
        while True:
            current_ip = get_ip()
            if current_ip is None:
                time.sleep(5)
                continue
            if current_ip in used_ips:
                time.sleep(5)
            else:
                print(f"[✓] Unique IP acquired: {current_ip}")
                used_ips.add(current_ip)
                break
        
        RUN_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{i}"
        PROFILE_PATH = os.path.join(SCRIPT_DIR, "Profiles", f"run_{RUN_ID}")
        os.makedirs(PROFILE_PATH, exist_ok=True)

        # Positioning logic uses physical width to tile correctly
        x_pos = i * PHYSICAL_WIDTH
        
        args = [
            browser_path,
            f"--user-data-dir={PROFILE_PATH}",
            f"--user-agent={UA_ANDROID}",
            f"--window-size={LOGICAL_WIDTH},{LOGICAL_HEIGHT}",
            f"--window-position={x_pos},0",
            f"--force-device-scale-factor={SCALE_FACTOR}", 
            "--no-first-run",
            "--disable-background-networking",
            "--no-default-browser-check",
            "--disable-sync",
            *OPTIMIZATION_FLAGS,
            invitation_link 
        ]
        
        print(f"[*] Launching Profile {i+1}...")
        subprocess.Popen(args)
        time.sleep(3)

    base_run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    profile_dir = os.path.join(SCRIPT_DIR, "Profiles")
    
    try:
        profiles_list = [p for p in os.listdir(profile_dir) if p.startswith(base_run_id)]
    except FileNotFoundError:
        profiles_list = []
        
    save_run_manifest(base_run_id, invitation_link, profiles_list)
    
    print("[*] Run manifest saved.")
    print("[*] Script active. Press 'Ctrl+Alt+D' to turn off the display (saves power while preserving GPU execution).")
    
    keyboard.add_hotkey('ctrl+alt+d', toggle_display_off)
    keyboard.wait() 

if __name__ == "__main__":
    launch_grid()
