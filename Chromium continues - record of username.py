import os
import sys
import subprocess
import ctypes
import datetime
import time
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
import win32gui
import win32process
import win32clipboard
import win32con
from win11toast import toast

# --- CONSTANTS ---
WM_CLIPBOARDUPDATE = 0x031D
WM_TIMER = 0x0113
WM_HOTKEY = 0x0312
TIMER_ID = 1
HOTKEY_DISPLAY_OFF_ID = 101
HOTKEY_MANUAL_BLANK_ID = 102
DESKTOP_FILE_PATH = os.path.join(os.environ["USERPROFILE"], "Desktop", "profiles.txt")

# --- SYSTEM NOTIFICATIONS ---
def send_notification(title, message):
    def _show_toast():
        try:
            toast(title, message, duration="short", audio={"silent": True})
        except Exception:
            pass
    threading.Thread(target=_show_toast, daemon=True).start()

# --- RESOURCE MANAGEMENT ---
_tracked_profiles = []
_created_desktops = []
GLOBAL_HWND = None
CLEANUP_QUEUE = queue.Queue()

def execute_profile_cleanup(path, process):
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
        for _ in range(30):
            try:
                shutil.rmtree(path)
                break
            except (PermissionError, OSError):
                time.sleep(0.2)

def background_cleanup_worker():
    while True:
        path, process = CLEANUP_QUEUE.get()
        try:
            execute_profile_cleanup(path, process)
        except Exception:
            pass
        finally:
            CLEANUP_QUEUE.task_done()

def cleanup_resources(sleep_ref=time.sleep, rmtree_ref=shutil.rmtree, exists_ref=os.path.exists):
    print("\n[*] Commencing structural resource cleanup...")
    global GLOBAL_HWND
    if GLOBAL_HWND:
        try:
            ctypes.windll.user32.UnregisterHotKey(GLOBAL_HWND, HOTKEY_DISPLAY_OFF_ID)
            ctypes.windll.user32.UnregisterHotKey(GLOBAL_HWND, HOTKEY_MANUAL_BLANK_ID)
            ctypes.windll.user32.KillTimer(GLOBAL_HWND, TIMER_ID)
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
    
    try:
        sleep_ref(0.5)
    except TypeError:
        pass

    for item in _tracked_profiles:
        if item["process"].poll() is None:
            try:
                subprocess.call(
                    ['taskkill', '/F', '/T', '/PID', str(item["process"].pid)], 
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass
        if exists_ref(item["path"]):
            for _ in range(10):
                try:
                    rmtree_ref(item["path"])
                    break
                except (PermissionError, OSError):
                    try:
                        sleep_ref(0.1)
                    except TypeError:
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

# --- RECONFIGURED CLEAN HIGH-PERFORMANCE FLAGS (SAFE FOR CASINOS) ---
OPTIMIZATION_FLAGS = [                                                                     
    "--mute-audio",
    "--disable-audio-output",
    "--disable-logging",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling,BackgroundTasks,OptimizationHints,Translate",
    "--enable-features=Touch,PointerEvent,MobileLayout",
    
    # --- GPU Acceleration Restored for Smooth 60FPS Shared RAM Playback ---
    "--enable-gpu",
    "--enable-webgl",
    "--enable-gpu-rasterization",
    "--enable-gpu-compositing",
    "--use-angle=d3d11",
    "--fps-limit=60",
    "--disable-gpu-vsync",
    "--ignore-gpu-blocklist",
    
    # --- Asset Overhead Mitigations ---
    "--disable-smooth-scrolling",
    "--no-proxy-server",
    "--disable-breakpad",
    "--disable-ipc-flooding-protection",
    
    # --- Strict RAM Constraints ---
    '--js-flags="--max-old-space-size=512 --expose-gc"' 
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
    os.makedirs(PROFILE_PATH, exist_ok=True)

    physical_x_pos = desktop_index * PHYSICAL_WIDTH
    logical_x_pos = int(physical_x_pos / SCALE_FACTOR)
    
    args = [
        browser_path,
        f"--user-data-dir={PROFILE_PATH}",
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
    process = subprocess.Popen(args)
    _tracked_profiles.append({"process": process, "path": PROFILE_PATH})

    force_window_to_desktop_and_position(process.pid, current_desktop, physical_x_pos)
    profile_count += 1
    desktop_index = (desktop_index + 1) % GRID_SIZE  
    update_console_status(profile_count)

def wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_CLIPBOARDUPDATE:
        for _ in range(10):
            try:
                win32clipboard.OpenClipboard(hwnd)
                try:
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                        raw_data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                        if raw_data:
                            clean_text = raw_data.strip()
                            threading.Thread(
                                target=handle_clipboard_input, 
                                args=(clean_text, DESKTOP_FILE_PATH), 
                                daemon=True
                            ).start()
                finally:
                    win32clipboard.CloseClipboard()
                break  
            except Exception:
                time.sleep(0.01)  
        return 0
        
    elif msg == WM_TIMER:
        if wparam == TIMER_ID:
            check_and_clean_dead_profiles()
        return 0
        
    elif msg == WM_HOTKEY:
        if wparam == HOTKEY_DISPLAY_OFF_ID:
            toggle_display_off()
        elif wparam == HOTKEY_MANUAL_BLANK_ID:
            trigger_manual_blank()
        return 0
        
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

def launch_grid():
    global browser_path, GLOBAL_HWND
    browser_path = find_chrome_executable()
    if not browser_path:
        print("[!] Error: Chrome executable missing.")
        return

    threading.Thread(target=background_cleanup_worker, daemon=True).start()
    print(f"[*] Monitoring grid profiles ({SCREEN_WIDTH}x{PHYSICAL_HEIGHT}). Ready.")
    update_console_status(0)

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
        ctypes.windll.user32.SetTimer(GLOBAL_HWND, TIMER_ID, 1000, None)
        
        MOD_CONTROL = 0x0002
        MOD_ALT = 0x0001
        VK_OEM_3 = 0xC0  
        VK_N = 0x4E      
        
        ctypes.windll.user32.RegisterHotKey(GLOBAL_HWND, HOTKEY_DISPLAY_OFF_ID, MOD_CONTROL | MOD_ALT, VK_OEM_3)
        ctypes.windll.user32.RegisterHotKey(GLOBAL_HWND, HOTKEY_MANUAL_BLANK_ID, MOD_CONTROL | MOD_ALT, VK_N)
        
        win32gui.PumpMessages()
    except Exception as e:
        print(f"[!] Core Win32 execution loop failure: {e}")

if __name__ == "__main__":
    launch_grid()
