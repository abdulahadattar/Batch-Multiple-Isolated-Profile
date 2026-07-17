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
        "keyboard": "keyboard",
        "pywin32": "win32gui"
    }
    for module, package in required_packages.items():
        try:
            if module == "pywin32":
                import win32gui
            else:
                __import__(module)
        except ImportError:
            print(f"[*] Installing missing dependency: {package}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

ensure_dependencies()

import pyperclip
import pyvda
import keyboard
import win32gui
import win32process

# --- RESOURCE MANAGEMENT ---
_tracked_profiles = []

def cleanup_resources():
    """Terminates all remaining processes and deletes all folders on exit."""
    print("\n[*] Commencing structural resource cleanup...")
    for item in _tracked_profiles:
        try:
            item["process"].terminate()
            item["process"].wait(timeout=1)
        except Exception:
            pass
        try:
            shutil.rmtree(item["path"], ignore_errors=True)
        except Exception:
            pass
    print("[*] Cleanup finalized.")

atexit.register(cleanup_resources)

def check_and_clean_dead_profiles():
    """Checks for closed windows, cleans their folders, and frees up space instantly."""
    global _tracked_profiles
    still_active = []
    
    for item in _tracked_profiles:
        if item["process"].poll() is not None:
            print(f"[*] Profile window closed by user. Purging temporary session data...")
            try:
                shutil.rmtree(item["path"], ignore_errors=True)
            except Exception:
                still_active.append(item)
                continue
        else:
            still_active.append(item)
            
    _tracked_profiles = still_active

# --- DISPLAY METRICS & CONFIGURATION ---
GRID_SIZE = 4
COLUMNS = 4
SCALE_FACTOR = 1

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
    rect = RECT()
    ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)
    return rect.right - rect.left, rect.bottom - rect.top

SCREEN_WIDTH, PHYSICAL_HEIGHT = get_work_area()
PHYSICAL_WIDTH = SCREEN_WIDTH // COLUMNS

LOGICAL_WIDTH = int(PHYSICAL_WIDTH / SCALE_FACTOR)
LOGICAL_HEIGHT = int(PHYSICAL_HEIGHT / SCALE_FACTOR)

UA_ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"

# BARE MINIMUM 60 FPS OPTIMIZATION FLAGS
OPTIMIZATION_FLAGS = [
    "--fps-limit=60",                          
    "--disable-gpu-vsync",                      
    "--ignore-gpu-blocklist",                  
    "--use-angle=d3d11",                        
    "--disable-site-isolation-trials",
    "--disable-features=IsolateOrigins,site-per-process",
    "--mute-audio",
    "--disable-audio-output",                      # Strips out core backend audio device processing
    "--disable-logging",
    "--disable-dev-shm-usage",
    "--disk-cache-size=0",                         # Zero disk overhead
    "--media-cache-size=0",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling,BackgroundTasks", 
    "--enable-gpu",
    "--enable-webgl",
    "--enable-gpu-rasterization",
    "--enable-gpu-compositing",
    "--disable-software-rasterizer",               # Avoid heavy CPU fallback rendering loops
    "--enable-features=Touch,PointerEvent,MobileLayout",
    "--disable-extensions",
    "--disable-fullscreen",
    "--no-sandbox",                                    
    "--disable-component-update",     
    "--disable-background-networking",
    "--no-proxy-server",
    "--disable-breakpad",
    "--disable-ipc-flooding-protection",
    "--disable-threaded-scrolling",                # Keeps updates directly tied to render threads
    
    # --- Visual Degradation / Bare Minimum Assets ---
    "--disable-gl-extensions",                     # Disables costly unneeded GPU extensions
    "--disable-ext-canvas2d-dynamic-rendering",    # Disables internal 2D dynamic smoothing optimizations
    "--disable-canvas-aa",                         # Turns off anti-aliasing on standard 2D canvases
    "--disable-canvas-2d-image-chromium",          # Turns off special chromium overlay smoothing
    "--disable-composited-antialiasing",           # Completely kills rendering frame anti-aliasing
    "--disable-smooth-scrolling",                  # Kills smooth motion calculation logic
    
    # --- V8 Engine & WebGL Context Clamping ---
    '--js-flags="--max-old-space-size=256 --expose-gc"', # Strict RAM limit per instance
    '--blink-settings=imagesEnabled=true',         # Set to false only if slots function without visual images
]

# Shared Global State
seen_links = set()
profile_count = 0  
desktop_index = 0  
current_desktop = None
browser_path = None
manual_trigger = False

def find_chrome_executable():
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
            if os.path.exists(p): return p
    return None

def toggle_display_off():
    print("[*] Display off signal sent. Press any key to wake.")
    ctypes.windll.user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)

def trigger_manual_blank():
    global manual_trigger
    manual_trigger = True
    print("[*] Manual shortcut detected. Preparing empty grid profile...")

def update_console_status(current_number):
    title_text = f"[Grid Monitor Active] Total Profiles: {profile_count} | Next Position: {desktop_index + 1}"
    ctypes.windll.kernel32.SetConsoleTitleW(title_text)

def create_and_switch_desktop():
    try:
        new_desktop = pyvda.VirtualDesktop.create()
        new_desktop.go()
        print("[*] Grid capacity hit. Automatically shifted to a fresh Virtual Desktop.")
        return new_desktop
    except Exception as e:
        print(f"[!] Desktop shift error: {e}")
        return pyvda.VirtualDesktop.current()

def force_window_to_desktop_and_position(pid, target_desktop, target_x):
    time.sleep(0.4) 
    def enum_windows_callback(hwnd, extra):
        lp_pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lp_pid))
        
        if lp_pid.value == pid and win32gui.IsWindowVisible(hwnd):
            try:
                window_view = pyvda.AppView(hwnd)
                window_view.move(target_desktop)
                win32gui.MoveWindow(hwnd, target_x, 0, PHYSICAL_WIDTH, PHYSICAL_HEIGHT, True)
            except Exception:
                pass
        return True
    win32gui.EnumWindows(enum_windows_callback, None)

def deploy_profile(url):
    global profile_count, desktop_index, current_desktop
    
    if profile_count > 0 and desktop_index == 0:
        current_desktop = create_and_switch_desktop()
        time.sleep(1.2)
    elif current_desktop is None:
        current_desktop = pyvda.VirtualDesktop.current()

    try:
        current_desktop.go()
    except Exception:
        pass

    RUN_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{profile_count}"
    PROFILE_PATH = tempfile.mkdtemp(prefix=f"run_{RUN_ID}_")

    pref_dir = os.path.join(PROFILE_PATH, "Default")
    os.makedirs(pref_dir, exist_ok=True)
    
    pref_data = {
        "profile": {"exit_type": "Normal", "exited_cleanly": True},
        "profile": {"default_content_setting_values": {"fullscreen": 2}}
    }
    
    with open(os.path.join(pref_dir, "Preferences"), "w") as f:
        json.dump(pref_data, f)

    physical_x_pos = desktop_index * PHYSICAL_WIDTH
    logical_x_pos = int(physical_x_pos / SCALE_FACTOR)
    
    args = [
        browser_path,
        f"--user-data-dir={PROFILE_PATH}",
        f"--user-agent={UA_ANDROID}",
        f"--window-size={LOGICAL_WIDTH},{LOGICAL_HEIGHT}",
        f"--window-position={logical_x_pos},0",
        f"--force-device-scale-factor={SCALE_FACTOR}", 
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        *OPTIMIZATION_FLAGS,
        url 
    ]
    
    print(f"[*] Deploying Profile {profile_count+1} to Position {desktop_index+1}...")
    
    ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
    process = subprocess.Popen(args, creationflags=ABOVE_NORMAL_PRIORITY_CLASS)
    
    _tracked_profiles.append({"process": process, "path": PROFILE_PATH})

    force_window_to_desktop_and_position(process.pid, current_desktop, physical_x_pos)

    profile_count += 1
    desktop_index = (desktop_index + 1) % GRID_SIZE  
    update_console_status(profile_count)
    time.sleep(1.5)

def launch_grid():
    global browser_path, manual_trigger
    browser_path = find_chrome_executable()
    if not browser_path:
        print("[!] Error: Chrome executable missing.")
        return

    print(f"[*] Monitoring grid profiles ({SCREEN_WIDTH}x{PHYSICAL_HEIGHT}). Ready.")
    update_console_status(0)
    
    keyboard.add_hotkey('ctrl+alt+d', toggle_display_off)
    keyboard.add_hotkey('ctrl+alt+n', trigger_manual_blank)

    try:
        while True:
            check_and_clean_dead_profiles()

            if manual_trigger:
                manual_trigger = False
                deploy_profile("about:blank")
                continue

            try:
                current_link = pyperclip.paste().strip()
            except Exception:
                current_link = ""

            if current_link and current_link.startswith("http") and (current_link not in seen_links):
                seen_links.add(current_link)
                print(f"\n[*] Unique link caught: {current_link}")
                deploy_profile(current_link)

            time.sleep(0.3) 
            
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    launch_grid()
