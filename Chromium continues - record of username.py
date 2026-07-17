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
import threading
import random

# --- DEPENDENCY RESOLUTION ---
def ensure_dependencies():
    required_packages = {
        "pyperclip": "pyperclip",
        "pyvda": "pyvda",
        "keyboard": "keyboard",
        "pywin32": "win32gui",
        "win11toast": "win11toast"
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
from win11toast import toast

# --- SYSTEM NOTIFICATIONS ---
def send_notification(title, message):
    """Non-blocking function to display toast notifications."""
    def _show_toast():
        try:
            toast(title, message, duration="short", audio={"silent": True})
        except Exception as e:
            print(f"[!] Notification Error: {e}")
            
    threading.Thread(target=_show_toast, daemon=True).start()

# --- RESOURCE MANAGEMENT ---
_tracked_profiles = []
_created_desktops = []

def cleanup_resources():
    print("\n[*] Commencing structural resource cleanup...")
    for item in _tracked_profiles:
        try:
            subprocess.call(
                ['taskkill', '/F', '/T', '/PID', str(item["process"].pid)], 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass
        try:
            shutil.rmtree(item["path"], ignore_errors=True)
        except Exception:
            pass
            
    for desktop in _created_desktops:
        try:
            desktop.remove()
        except Exception:
            pass
            
    print("[*] Cleanup finalized.")

atexit.register(cleanup_resources)

def check_and_clean_dead_profiles():
    global _tracked_profiles
    still_active = []
    
    for item in _tracked_profiles:
        if item["process"].poll() is not None:
            print(f"[*] Profile window closed by user. Purging temporary session data...")
            try:
                subprocess.call(
                    ['taskkill', '/F', '/T', '/PID', str(item["process"].pid)], 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                pass
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

# --- DEVICE FINGERPRINT POOL ---
DEVICE_FINGERPRINTS = [
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 6a) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Pixel 6 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-F946B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-F731B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-A346B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; OnePlus 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; OnePlus 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; IN2023) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Xiaomi 14 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Xiaomi 13 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; 2201123G) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Redmi Note 12 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Redmi Note 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; POCO F5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; POCO X4 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; POCO M3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; XT2401-2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; XT2301-4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; motorola edge 30 pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; V2250) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; RMX3709) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36"
]

# --- HARDWARE OPTIMIZATION & RENDERING LIMITATIONS ---
OPTIMIZATION_FLAGS = [
    "--fps-limit=60",
    "--disable-gpu-vsync",
    "--ignore-gpu-blocklist",
    "--use-angle=vulkan",
    "--disable-site-isolation-trials",
    "--disable-features=IsolateOrigins,site-per-process,UserAgentClientHint,CalculateNativeWinOcclusion,IntensiveWakeUpThrottling,BackgroundTasks",
    "--mute-audio",
    "--disable-audio-output",
    "--disable-logging",
    "--disable-dev-shm-usage",
    "--disk-cache-size=0",
    "--media-cache-size=0",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--enable-gpu",
    "--enable-webgl",
    "--enable-gpu-rasterization",
    "--enable-gpu-compositing",
    "--disable-software-rasterizer",
    "--enable-features=Touch,PointerEvent,MobileLayout",
    "--disable-extensions",
    "--disable-fullscreen",
    "--disable-blink-features=Fullscreen",
    "--no-sandbox",
    "--disable-component-update",
    "--disable-background-networking",
    "--no-proxy-server",
    "--disable-breakpad",
    "--disable-ipc-flooding-protection",
    "--disable-crash-reporter",
    "--disable-in-process-stack-traces",
    "--crash-dumps-dir=NUL",
    "--force-webrtc-ip-handling-policy=default_public_interface_only",
    "--disable-webrtc-hw-decoding",
    "--disable-canvas-2d-image-chromium",
    "--disable-smooth-scrolling",
    "--blink-settings=imagesEnabled=true"
]

seen_links = set()
seen_usernames = set()

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
    print("\n[*] Display off signal sent via hotkey. Press any physical key or mouse click to wake.")
    send_notification("Display Status", "Display turned off. Press any key to wake.")
    ctypes.windll.user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)

def trigger_manual_blank():
    global manual_trigger
    manual_trigger = True
    print("\n[*] Manual shortcut detected. Preparing empty grid profile...")
    send_notification("Profile Deployed", "Manual blank profile initialized.")

def update_console_status(current_number):
    title_text = f"[Grid Monitor Active] Total Profiles: {profile_count} | Next Position: {desktop_index + 1}"
    ctypes.windll.kernel32.SetConsoleTitleW(title_text)

def create_and_switch_desktop():
    try:
        new_desktop = pyvda.VirtualDesktop.create()
        new_desktop.go()
        _created_desktops.append(new_desktop)
        print("[*] Automatically shifted to a fresh Virtual Desktop.")
        send_notification("Desktop Shift", "Moved to a new Virtual Desktop.")
        return new_desktop
    except Exception as e:
        print(f"[!] Desktop shift error: {e}")
        return pyvda.VirtualDesktop.current()

def force_window_to_desktop_and_position(pid, target_desktop, target_x):
    timeout = 3.0  
    start_time = time.time()
    window_found = False
    
    while time.time() - start_time < timeout:
        def enum_windows_callback(hwnd, extra):
            nonlocal window_found
            lp_pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lp_pid))
            
            if lp_pid.value == pid and win32gui.IsWindowVisible(hwnd):
                try:
                    window_view = pyvda.AppView(hwnd)
                    window_view.move(target_desktop)
                    win32gui.MoveWindow(hwnd, target_x, 0, PHYSICAL_WIDTH, PHYSICAL_HEIGHT, True)
                    window_found = True
                except Exception:
                    pass
            return True
            
        win32gui.EnumWindows(enum_windows_callback, None)
        if window_found:
            break
        time.sleep(0.1)

def deploy_profile(url):
    global profile_count, desktop_index, current_desktop
    
    if current_desktop is None or (profile_count > 0 and desktop_index == 0):
        current_desktop = create_and_switch_desktop()
        time.sleep(1.2)

    try:
        current_desktop.go()
    except Exception:
        pass

    RUN_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{profile_count}"
    PROFILE_PATH = tempfile.mkdtemp(prefix=f"run_{RUN_ID}_")

    pref_dir = os.path.join(PROFILE_PATH, "Default")
    os.makedirs(pref_dir, exist_ok=True)
    
    pref_data = {
        "profile": {
            "exit_type": "Normal", 
            "exited_cleanly": True,
            "default_content_setting_values": {
                "fullscreen": 2,
                "popups": 2
            },
            "managed_default_content_settings": {
                "fullscreen": 2,
                "popups": 2
            }
        }
    }
    
    with open(os.path.join(pref_dir, "Preferences"), "w") as f:
        json.dump(pref_data, f)

    physical_x_pos = desktop_index * PHYSICAL_WIDTH
    logical_x_pos = int(physical_x_pos / SCALE_FACTOR)
    
    current_ua = random.choice(DEVICE_FINGERPRINTS)
    
    args = [
        browser_path,
        f"--user-data-dir={PROFILE_PATH}",
        f"--user-agent={current_ua}",
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
    
    NORMAL_PRIORITY_CLASS = 0x00000020
    process = subprocess.Popen(args, creationflags=NORMAL_PRIORITY_CLASS)
    
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

    desktop_file_path = os.path.join(os.environ["USERPROFILE"], "Desktop", "profiles.txt")

    print(f"[*] Monitoring grid profiles ({SCREEN_WIDTH}x{PHYSICAL_HEIGHT}). Ready.")
    update_console_status(0)
    
    keyboard.add_hotkey('ctrl+alt+`', toggle_display_off)
    keyboard.add_hotkey('ctrl+alt+n', trigger_manual_blank)

    try:
        while True:
            check_and_clean_dead_profiles()

            if manual_trigger:
                manual_trigger = False
                deploy_profile("about:blank")
                continue

            try:
                clipboard_data = pyperclip.paste().strip()
            except Exception:
                clipboard_data = ""

            if clipboard_data and (clipboard_data not in seen_links) and (clipboard_data not in seen_usernames):
                
                if clipboard_data.startswith("http"):
                    seen_links.add(clipboard_data)
                    print(f"\n[*] Unique link caught: {clipboard_data}")
                    send_notification("Link Caught", "Deploying new browser profile.")
                    deploy_profile(clipboard_data)
                
                elif len(clipboard_data) <= 50 and clipboard_data.isalnum() and any(char.isdigit() for char in clipboard_data):
                    seen_usernames.add(clipboard_data)
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    try:
                        with open(desktop_file_path, "a", encoding="utf-8") as f:
                            f.write(f"[{timestamp}] {clipboard_data}\n")
                        print(f"[*] Username logged to Desktop: {clipboard_data}")
                        send_notification("Username Saved", f"{clipboard_data}\nSaved to profiles.txt")
                    except Exception as e:
                        print(f"[!] File write error: {e}")

            time.sleep(0.3) 
            
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    launch_grid()
