import os
import sys
import subprocess
import ctypes
import datetime
import time
import json
import winreg
import tempfile
import atexit
import shutil

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

import pyperclip
import pyvda
import keyboard

# --- RESOURCE MANAGEMENT ---
_active_processes = []
_volatile_directories = []

def cleanup_resources():
    """Terminates child processes and removes temporary directories upon script exit."""
    print("\n[*] Commencing resource cleanup...")
    for proc in _active_processes:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            pass
            
    # Minor delay to ensure file locks are released by the OS
    time.sleep(1) 
    
    for directory in _volatile_directories:
        try:
            shutil.rmtree(directory, ignore_errors=True)
        except Exception:
            pass
    print("[*] Cleanup finalized.")

atexit.register(cleanup_resources)

# --- DISPLAY METRICS & CONFIGURATION ---
GRID_SIZE = 4
COLUMNS = 4
SCALE_FACTOR = 0.5

try:
    ctypes.windll.user32.SetProcessDPIAware()
except AttributeError:
    pass

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long)
    ]

def get_work_area():
    """Retrieves the screen dimensions excluding the Windows taskbar."""
    rect = RECT()
    ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    return width, height

SCREEN_WIDTH, PHYSICAL_HEIGHT = get_work_area()
PHYSICAL_WIDTH = SCREEN_WIDTH // COLUMNS

LOGICAL_WIDTH = int(PHYSICAL_WIDTH / SCALE_FACTOR)
LOGICAL_HEIGHT = int(PHYSICAL_HEIGHT / SCALE_FACTOR)

UA_ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"

# --- OPTIMIZATION FLAGS ---
OPTIMIZATION_FLAGS = [
    # --- SYNCHRONIZATION & PERFORMANCE ---
    "--fps-limit=60",                          
    "--disable-gpu-vsync",                     
    "--ignore-gpu-blocklist",                  # Forces GPU acceleration irrespective of hardware blocklists
    "--use-angle=d3d11",                       # Enforces Direct3D 11 rendering backend for WebGL stability
    
    # --- CPU & RAM OFF-LOADING ---
    "--disable-site-isolation-trials",
    "--disable-features=IsolateOrigins,site-per-process",
    "--mute-audio",
    "--disable-logging",
    "--disable-dev-shm-usage",
    "--disk-cache-size=1",                     # Minimizes disk I/O caching overhead
    
    # --- BACKGROUND PERSISTENCE & ANTI-OCCLUSION ---
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling", # Prevents OS-level window occlusion tracking and deep sleep
    
    # --- GRAPHICS PIPELINE ---
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

    print(f"[*] Display Work Area Detected: {SCREEN_WIDTH}x{PHYSICAL_HEIGHT}")
    print(f"[*] Calculated Physical Window Size: {PHYSICAL_WIDTH}x{PHYSICAL_HEIGHT}")
    print("[*] Launching Chromium (Optimized Persistence & Volatile Mode)...")
    
    invitation_link = pyperclip.paste().strip()
    if not invitation_link or not invitation_link.startswith("http"):
        print("[*] No valid URL found in clipboard. Initializing with blank pages.")
        invitation_link = "about:blank"
    else:
        print(f"[*] Validated Link: {invitation_link}")
        
    create_and_switch_desktop()

    for i in range(GRID_SIZE):
        RUN_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{i}"
        
        # Volatile Profile Generation
        PROFILE_PATH = tempfile.mkdtemp(prefix=f"run_{RUN_ID}_")
        _volatile_directories.append(PROFILE_PATH)

        x_index = i % COLUMNS
        logical_x_pos = int((x_index * PHYSICAL_WIDTH) / SCALE_FACTOR)
        
        args = [
            browser_path,
            f"--user-data-dir={PROFILE_PATH}",
            f"--user-agent={UA_ANDROID}",
            f"--window-size={LOGICAL_WIDTH},{LOGICAL_HEIGHT}",
            f"--window-position={logical_x_pos},0",
            f"--force-device-scale-factor={SCALE_FACTOR}", 
            "--no-first-run",
            "--disable-background-networking",
            "--no-default-browser-check",
            "--disable-sync",
            *OPTIMIZATION_FLAGS,
            invitation_link 
        ]
        
        print(f"[*] Launching Profile {i+1} at Logical X:{logical_x_pos} (Physical X:{x_index * PHYSICAL_WIDTH})...")
        process = subprocess.Popen(args)
        _active_processes.append(process)
        time.sleep(0.5)

    print("[*] Script active. Press 'Ctrl+Alt+D' to turn off the display.")
    print("[*] Press 'Ctrl+C' in the console to terminate processes and purge volatile data.")
    
    try:
        keyboard.add_hotkey('ctrl+alt+d', toggle_display_off)
        keyboard.wait() 
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    launch_grid()
