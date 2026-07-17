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
import queue

# --- DEPENDENCY RESOLUTION ---
def ensure_dependencies():
    required_packages = {
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

import pyvda
import keyboard
import win32gui
import win32process
import win32clipboard
import win32con
from win11toast import toast

# --- CONSTANTS ---
WM_CLIPBOARDUPDATE = 0x031D
WM_TIMER = 0x0113
TIMER_ID = 1
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
DESKTOP_FILE_PATH = os.path.join(os.environ["USERPROFILE"], "Desktop", "profiles.txt")
GLOBAL_EXTENSION_DIR = r"C:\ChromeGrid\Extension"
GLOBAL_BASE_PROFILE = r"C:\ChromeGrid\BaseProfile"

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
GLOBAL_HWND = None
CLEANUP_QUEUE = queue.Queue()

def ensure_extension_built():
    """Generates the runtime presentation extension in a persistent layout once."""
    os.makedirs(GLOBAL_EXTENSION_DIR, exist_ok=True)
    manifest = {
        "manifest_version": 3,
        "name": "Runtime Presentation Adjustment",
        "version": "1.1",
        "content_scripts": [{
            "matches": ["<all_urls>"],
            "js": ["content.js"],
            "run_at": "document_start"
        }]
    }
    content_script = """
    (function() {
        const exclusionSelectors = [
            'div[class*="modal" i]', 'div[class*="popup" i]',
            'div[class*="mask" i]', 'div[class*="overlay" i]',
            'div[class*="award" i]', 'div[class*="gift" i]'
        ];
        const executeTargetedPurge = () => {
            exclusionSelectors.forEach(selector => {
                document.querySelectorAll(selector).forEach(node => {
                    const contentText = node.textContent.toLowerCase();
                    if (contentText.includes('rs30')) {
                        node.style.display = 'none';
                        node.remove();
                    }
                });
            });
        };
        const observerInstance = new MutationObserver(() => { executeTargetedPurge(); });
        observerInstance.observe(document.documentElement, { childList: true, subtree: true });
        window.addEventListener('DOMContentLoaded', executeTargetedPurge);
    })();
    """
    with open(os.path.join(GLOBAL_EXTENSION_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    with open(os.path.join(GLOBAL_EXTENSION_DIR, "content.js"), "w", encoding="utf-8") as f:
        f.write(content_script)

def ensure_base_profile_built():
    """Generates the baseline profile layout once to optimize disk operations."""
    pref_dir = os.path.join(GLOBAL_BASE_PROFILE, "Default")
    os.makedirs(pref_dir, exist_ok=True)
    pref_data = {
        "profile": {
            "exit_type": "Normal", 
            "exited_cleanly": True,
            "default_content_setting_values": {"fullscreen": 2, "popups": 2},
            "managed_default_content_settings": {"fullscreen": 2, "popups": 2}
        }
    }
    with open(os.path.join(pref_dir, "Preferences"), "w") as f:
        json.dump(pref_data, f)

def execute_profile_cleanup(path, process):
    """Gracefully terminates browser profiles and securely cleans up directories."""
    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except (subprocess.TimeoutExpired, Exception):
            if process.poll() is None:
                try:
                    subprocess.call(
                        ['taskkill', '/F', '/T', '/PID', str(process.pid)], 
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                except Exception:
                    pass

    if os.path.exists(path):
        for _ in range(30):  # Bounded loop prevents permanent freezes
            try:
                shutil.rmtree(path)
                break
            except (PermissionError, OSError):
                time.sleep(0.2)

def background_cleanup_worker():
    """Background worker processing file deletions cleanly out of the main thread loop."""
    while True:
        path, process = CLEANUP_QUEUE.get()
        try:
            execute_profile_cleanup(path, process)
        except Exception as e:
            print(f"[!] Error in background cleanup task: {e}")
        finally:
            CLEANUP_QUEUE.task_done()

def cleanup_resources():
    print("\n[*] Commencing structural resource cleanup...")
    global GLOBAL_HWND
    if GLOBAL_HWND:
        try:
            ctypes.windll.user32.RemoveClipboardFormatListener(GLOBAL_HWND)
            win32gui.DestroyWindow(GLOBAL_HWND)
        except Exception:
            pass

    for item in _tracked_profiles:
        if item["process"].poll() is None:
            try:
                item["process"].terminate()
            except Exception:
                pass
    
    time.sleep(0.5)
    for item in _tracked_profiles:
        if item["process"].poll() is None:
            try:
                subprocess.call(
                    ['taskkill', '/F', '/T', '/PID', str(item["process"].pid)], 
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass
        if os.path.exists(item["path"]):
            for _ in range(10):
                try:
                    shutil.rmtree(item["path"])
                    break
                except (PermissionError, OSError):
                    time.sleep(0.1)

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
            print(f"[*] Profile window closed by user. Pushing to async cleanup queue...")
            CLEANUP_QUEUE.put((item["path"], item["process"]))
        else:
            still_active.append(item)
    _tracked_profiles = still_active

# --- DISPLAY METRICS & CONFIGURATION ---
GRID_SIZE = 4
COLUMNS = 4
SCALE_FACTOR = 0.8

try:
    ctypes.windll.user32.SetProcessDPIAware()
except AttributeError:
    pass

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long), ("top", ctypes.c_long),
        ("right", ctypes.c_long), ("bottom", ctypes.c_long)
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
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36"
]

OPTIMIZATION_FLAGS = [
    "--fps-limit=60",
    "--disable-features=UserAgentClientHint,CalculateNativeWinOcclusion,IntensiveWakeUpThrottling,BackgroundTasks,OptimizationHints,Translate",
    "--mute-audio",
    "--disable-audio-output",
    "--disable-logging",
    "--disk-cache-size=0",
    "--media-cache-size=0",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--enable-features=Touch,PointerEvent,MobileLayout",
    "--disable-extensions-file-access-check",
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
    "--force-webrtc-ip-handling-policy=default_public_interface_only",
    "--disable-webrtc-hw-decoding",
    "--disable-canvas-2d-image-chromium",
    "--disable-smooth-scrolling",
    "--blink-settings=imagesEnabled=true",
    "--ignore-gpu-blocklist",
    "--enable-gpu-rasterization",
    "--enable-zero-copy"
]

seen_links = set()
seen_usernames = set()
profile_count = 0  
desktop_index = 0  
current_desktop = None
browser_path = None

def find_chrome_executable():
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe")
        path, _ = winreg.QueryValueEx(key, "")
        return path
    except Exception:
        standard_paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")
        ]
        for p in standard_paths:
            if os.path.exists(p): return p
    return None

def toggle_display_off():
    print("\n[*] Display off signal sent via hotkey. Press any physical key or mouse click to wake.")
    send_notification("Display Status", "Display turned off. Press any key to wake.")
    ctypes.windll.user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)

def handle_clipboard_input(clipboard_data, desktop_file_path):
    if clipboard_data and (clipboard_data not in seen_links) and (clipboard_data not in seen_usernames):
        if clipboard_data.startswith("http"):
            seen_links.add(clipboard_data)
            print(f"\n[*] Unique link caught: {clipboard_data}")
            send_notification("Link Caught", "Deploying new browser profile.")
            deploy_profile(clipboard_data)
        elif len(clipboard_data) <= 30 and clipboard_data.isalnum() and any(char.isdigit() for char in clipboard_data):
            seen_usernames.add(clipboard_data)
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                with open(desktop_file_path, "a", encoding="utf-8") as f:
                    f.write(f"[{timestamp}] {clipboard_data}\n")
                print(f"[*] Username logged to Desktop: {clipboard_data}")
                send_notification("Username Saved", f"{clipboard_data}\nSaved to profiles.txt")
            except Exception as e:
                print(f"[!] File write error: {e}")

def trigger_manual_blank():
    print("\n[*] Manual shortcut detected. Preparing empty grid profile...")
    send_notification("Profile Deployed", "Manual blank profile initialized.")
    deploy_profile("about:blank")

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
    PROFILE_PATH = os.path.join(tempfile.gettempdir(), f"run_{RUN_ID}")

    # Lightning-fast directory initialization using Windows Native Robocopy
    subprocess.call(
        ['robocopy', GLOBAL_BASE_PROFILE, PROFILE_PATH, '/MIR'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

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
        f"--load-extension={GLOBAL_EXTENSION_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        *OPTIMIZATION_FLAGS,
        url
    ]
    
    print(f"[*] Deploying Profile {profile_count+1} to Position {desktop_index+1}...")
    process = subprocess.Popen(args, creationflags=ABOVE_NORMAL_PRIORITY_CLASS)
    _tracked_profiles.append({"process": process, "path": PROFILE_PATH})

    force_window_to_desktop_and_position(process.pid, current_desktop, physical_x_pos)
    profile_count += 1
    desktop_index = (desktop_index + 1) % GRID_SIZE  
    update_console_status(profile_count)

def wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_CLIPBOARDUPDATE:
        try:
            if win32clipboard.OpenClipboard(hwnd):
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    if data:
                        handle_clipboard_input(data.strip(), DESKTOP_FILE_PATH)
                win32clipboard.CloseClipboard()
        except Exception as e:
            print(f"[!] Clipboard data extraction error: {e}")
        return 0
    elif msg == WM_TIMER:
        if wparam == TIMER_ID:
            check_and_clean_dead_profiles()
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

def launch_grid():
    global browser_path, GLOBAL_HWND
    browser_path = find_chrome_executable()
    if not browser_path:
        print("[!] Error: Chrome executable missing.")
        return

    print("[*] Setting up extension asset rules...")
    ensure_extension_built()
    
    print("[*] Creating baseline user profile template environment...")
    ensure_base_profile_built()

    # Launching async background queue manager
    threading.Thread(target=background_cleanup_worker, daemon=True).start()

    print(f"[*] Monitoring grid profiles ({SCREEN_WIDTH}x{PHYSICAL_HEIGHT}). Ready.")
    update_console_status(0)
    
    keyboard.add_hotkey('ctrl+alt+`', toggle_display_off)
    keyboard.add_hotkey('ctrl+alt+n', trigger_manual_blank)

    wc = win32gui.WNDCLASS()
    wc.lpfnWndProc = wnd_proc
    wc.lpszClassName = "ChromeGridListenerWindow"
    wc.hInstance = win32gui.GetModuleHandle(None)
    
    try:
        try:
            class_atom = win32gui.RegisterClass(wc)
        except win32gui.error:
            class_atom = win32gui.GetClassInfo(wc.hInstance, wc.lpszClassName)[0]

        GLOBAL_HWND = win32gui.CreateWindow(
            class_atom, "Grid Listener", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None
        )
        
        ctypes.windll.user32.AddClipboardFormatListener(GLOBAL_HWND)
        win32gui.SetTimer(GLOBAL_HWND, TIMER_ID, 1000, None)
        win32gui.PumpMessages()
    except Exception as e:
        print(f"[!] Core Win32 execution loop failure: {e}")

if __name__ == "__main__":
    launch_grid()
