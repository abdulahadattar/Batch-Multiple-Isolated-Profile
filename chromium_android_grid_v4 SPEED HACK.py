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
    required_packages = {
        "pyperclip": "pyperclip",
        "pyvda": "pyvda",
        "keyboard": "keyboard"
    }
    for module, package in required_packages.items():
        try:
            __import__(module)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

ensure_dependencies()

import pyperclip
import pyvda
import keyboard

# --- RESOURCE MANAGEMENT ---
_active_processes = []
_volatile_directories = []

def cleanup_resources():
    for proc in _active_processes:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            pass
            
    time.sleep(1) 
    
    for directory in _volatile_directories:
        try:
            shutil.rmtree(directory, ignore_errors=True)
        except Exception:
            pass

atexit.register(cleanup_resources)

# --- DISPLAY METRICS & CONFIGURATION ---
GRID_SIZE = 4       
COLUMNS = 4
SCALE_FACTOR = 0.3  
TARGET_ENGINE_FPS = 400 # Target cycles per second for the internal game engine

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

# --- ASYNCHRONOUS FRAME PUMPER INJECTION ---
def build_frame_pumper(base_dir, target_fps):
    """Generates an extension to decouple engine ticks from browser VSync."""
    ext_dir = os.path.join(base_dir, "frame_pumper_extension")
    os.makedirs(ext_dir, exist_ok=True)

    manifest = {
        "manifest_version": 3,
        "name": "Asynchronous Engine Pumper",
        "version": "2.0",
        "content_scripts": [{
            "matches": ["<all_urls>"],
            "js": ["content.js"],
            "run_at": "document_start",
            "all_frames": True
        }]
    }
    
    with open(os.path.join(ext_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f)

    content_js = f"""
    const script = document.createElement('script');
    script.textContent = `
        const TARGET_FPS = {target_fps};
        const INTERVAL_MS = 1000 / TARGET_FPS;
        const BASE_FRAME_MS = 1000 / 60; 
        
        let frameQueue = [];
        let rAF_ID = 1;
        let simulatedTime = performance.now();

        // Intercept native VSync requests
        const _originalRAF = window.requestAnimationFrame;
        const _originalCAF = window.cancelAnimationFrame;

        window.requestAnimationFrame = function(callback) {{
            const id = rAF_ID++;
            frameQueue.push({{ id, callback }});
            return id;
        }};

        window.cancelAnimationFrame = function(id) {{
            frameQueue = frameQueue.filter(task => task.id !== id);
        }};

        // Execute engine loop independently at target frequency
        setInterval(() => {{
            simulatedTime += BASE_FRAME_MS; 
            const currentTasks = frameQueue;
            frameQueue = []; // Clear queue to permit recursive calls
            
            for (let i = 0; i < currentTasks.length; i++) {{
                try {{
                    currentTasks[i].callback(simulatedTime);
                }} catch (error) {{}}
            }}
        }}, INTERVAL_MS);

        // Compress setTimeout/setInterval overhead
        const _setTimeout = window.setTimeout;
        const _setInterval = window.setInterval;
        const SPEED_FACTOR = TARGET_FPS / 60;
        
        window.setTimeout = (cb, ms, ...args) => _setTimeout(cb, ms / SPEED_FACTOR, ...args);
        window.setInterval = (cb, ms, ...args) => _setInterval(cb, ms / SPEED_FACTOR, ...args);
    `;
    document.documentElement.appendChild(script);
    script.remove();
    """
    
    with open(os.path.join(ext_dir, "content.js"), "w") as f:
        f.write(content_js)

    return ext_dir

# --- OPTIMIZATION FLAGS ---
OPTIMIZATION_FLAGS = [
    "--disable-frame-rate-limit",              # CRITICAL: Removes the hard 60FPS lock 
    "--disable-gpu-vsync",                     # CRITICAL: Decouples rendering from monitor refresh rate
    "--ignore-gpu-blocklist",                  
    "--use-angle=d3d11",                       
    "--disable-site-isolation-trials",
    "--disable-features=IsolateOrigins,site-per-process",
    "--mute-audio",
    "--disable-logging",
    "--disable-dev-shm-usage",
    "--disk-cache-size=1",                     
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling", 
    "--enable-gpu",
    "--enable-webgl",
    "--enable-gpu-rasterization",
    "--enable-gpu-compositing",
    "--enable-features=Touch,PointerEvent,MobileLayout",
]

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
            if os.path.exists(p):
                return p
    return None

def toggle_display_off():
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
        return

    invitation_link = pyperclip.paste().strip()
    if not invitation_link or not invitation_link.startswith("http"):
        invitation_link = "about:blank"
        
    create_and_switch_desktop()

    master_temp_dir = tempfile.mkdtemp(prefix="master_run_")
    _volatile_directories.append(master_temp_dir)
    pumper_extension_path = build_frame_pumper(master_temp_dir, TARGET_ENGINE_FPS)

    for i in range(GRID_SIZE):
        RUN_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{i}"
        
        PROFILE_PATH = tempfile.mkdtemp(prefix=f"run_{RUN_ID}_")
        _volatile_directories.append(PROFILE_PATH)

        x_index = i % COLUMNS
        y_index = i // COLUMNS
        
        logical_y_pos = int((y_index * (PHYSICAL_HEIGHT // (GRID_SIZE // COLUMNS or 1))) / SCALE_FACTOR)
        logical_x_pos = int((x_index * PHYSICAL_WIDTH) / SCALE_FACTOR)
        
        args = [
            browser_path,
            f"--user-data-dir={PROFILE_PATH}",
            f"--user-agent={UA_ANDROID}",
            f"--window-size={LOGICAL_WIDTH},{LOGICAL_HEIGHT}",
            f"--window-position={logical_x_pos},{logical_y_pos}",
            f"--force-device-scale-factor={SCALE_FACTOR}", 
            f"--load-extension={pumper_extension_path}",
            "--no-first-run",
            "--disable-background-networking",
            "--no-default-browser-check",
            "--disable-sync",
            *OPTIMIZATION_FLAGS,
            invitation_link 
        ]
        
        process = subprocess.Popen(args)
        _active_processes.append(process)
        time.sleep(0.5)

    try:
        keyboard.add_hotkey('ctrl+alt+d', toggle_display_off)
        keyboard.wait() 
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    launch_grid()
