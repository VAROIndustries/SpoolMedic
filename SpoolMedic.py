#!/usr/bin/env python3
"""
SpoolMedic - Print Queue Fix System Tray Utility
Restarts the print spooler and clears stuck queues without a reboot.
"""

import sys
import os
import json
import threading
import ctypes
import subprocess
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable

import pystray
from PIL import Image, ImageDraw, ImageTk
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# ---------------------------------------------------------------------------
# Win32 imports (optional — graceful fallback if pywin32 not installed)
# ---------------------------------------------------------------------------
try:
    import win32print
    import win32serviceutil
    import win32service
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_NAME    = "SpoolMedic"
APP_VERSION = "1.0.0"
TASK_NAME   = "SpoolMedicStartup"

APPS_URL   = "https://varo.industries/apps#github"
GITHUB_URL = "https://github.com/VAROIndustries/SpoolMedic"

WINDIR        = Path(os.environ.get("WINDIR", r"C:\Windows"))
SPOOL_FOLDER  = WINDIR / "System32" / "spool" / "PRINTERS"
APPDATA_DIR   = Path(os.environ.get("APPDATA", ".")) / APP_NAME
CONFIG_FILE   = APPDATA_DIR / "config.json"
LOG_FILE      = APPDATA_DIR / "SpoolMedic.log"

DEFAULT_CONFIG: dict = {
    "selected_printers":    [],     # empty = all printers
    "run_at_startup":       False,
    "auto_fix_on_startup":  False,
    "show_notifications":   True,
    "flush_dns":            False,
    "clear_arp":            False,
}

# Colors
C_BLUE      = "#1565C0"
C_DARK_BLUE = "#0D47A1"
C_LIGHT_BG  = "#E3F2FD"
C_GREEN     = "#4CAF50"
C_RED       = "#F44336"
C_ORANGE    = "#FF9800"
C_GRAY      = "#9E9E9E"


# ===========================================================================
# Utilities
# ===========================================================================

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _python_exe() -> str:
    """Return the Python interpreter path (or the frozen exe path).

    Prefers SpoolMedic.exe (a copy of pythonw.exe in the script dir)
    so Windows sees a unique exe identity in the notification area.
    """
    if getattr(sys, "frozen", False):
        return sys.executable
    local_exe = Path(_script_path()).parent / "SpoolMedic.exe"
    if local_exe.exists():
        return str(local_exe)
    return sys.executable


def _script_path() -> str:
    return os.path.abspath(sys.argv[0])


def elevate_and_restart():
    """Relaunch the current process with administrator privileges."""
    exe  = _python_exe()
    args = f'"{_script_path()}"' if not getattr(sys, "frozen", False) else ""
    ret  = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
    if ret > 32:
        sys.exit(0)


# ===========================================================================
# Config
# ===========================================================================

def ensure_appdata():
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_appdata()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return {**DEFAULT_CONFIG, **data}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    ensure_appdata()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# ===========================================================================
# Logging
# ===========================================================================

def log(message: str, level: str = "INFO"):
    ensure_appdata()
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] [{level}] {message}"
    print(entry, file=sys.stderr)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


# ===========================================================================
# Printer enumeration
# ===========================================================================

def get_all_printers() -> List[str]:
    printers: List[str] = []

    if HAS_WIN32:
        try:
            for flag in (win32print.PRINTER_ENUM_LOCAL, win32print.PRINTER_ENUM_CONNECTIONS):
                for p in win32print.EnumPrinters(flag):
                    name = p[2]
                    if name not in printers:
                        printers.append(name)
            return printers
        except Exception as e:
            log(f"win32print enum failed: {e}", "WARN")

    # Fallback via PowerShell
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Printer | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=15,
        )
        printers = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    except Exception as e:
        log(f"PowerShell printer enum failed: {e}", "WARN")

    return printers


# ===========================================================================
# Fix operations
# ===========================================================================

def _stop_spooler() -> bool:
    log("Stopping Print Spooler service...")
    try:
        if HAS_WIN32:
            try:
                status = win32serviceutil.QueryServiceStatus("Spooler")[1]
                if status != win32service.SERVICE_STOPPED:
                    win32serviceutil.StopService("Spooler")
                    for _ in range(10):
                        time.sleep(1)
                        if win32serviceutil.QueryServiceStatus("Spooler")[1] == win32service.SERVICE_STOPPED:
                            break
                else:
                    log("Spooler was already stopped.", "WARN")
                    return True
            except Exception:
                raise
        else:
            subprocess.run(["net", "stop", "Spooler", "/y"],
                           capture_output=True, timeout=30)
            time.sleep(2)
        log("Print Spooler stopped.", "SUCCESS")
        return True
    except Exception as e:
        log(f"Error stopping Spooler: {e}", "ERROR")
        return False


def _clear_spool() -> int:
    """Delete all files in the spool folder. Returns number of files deleted."""
    log(f"Clearing spool folder: {SPOOL_FOLDER}")
    deleted = 0
    try:
        if not SPOOL_FOLDER.exists():
            log("Spool folder not found (unusual).", "WARN")
            return 0
        for f in SPOOL_FOLDER.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                    deleted += 1
                    log(f"  Deleted: {f.name}")
                except Exception as e:
                    log(f"  Could not delete {f.name}: {e}", "WARN")
        if deleted:
            log(f"Deleted {deleted} spool file(s).", "SUCCESS")
        else:
            log("Spool folder was already empty.", "WARN")
    except Exception as e:
        log(f"Error clearing spool: {e}", "ERROR")
    return deleted


def _flush_dns():
    log("Flushing DNS resolver cache...")
    try:
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=15)
        log("DNS cache flushed.", "SUCCESS")
    except Exception as e:
        log(f"DNS flush error: {e}", "WARN")


def _clear_arp():
    log("Clearing ARP cache...")
    try:
        subprocess.run(
            ["netsh", "interface", "ip", "delete", "arpcache"],
            capture_output=True, timeout=15,
        )
        log("ARP cache cleared.", "SUCCESS")
    except Exception as e:
        log(f"ARP clear error: {e}", "WARN")


def _start_spooler() -> bool:
    log("Starting Print Spooler service...")
    try:
        if HAS_WIN32:
            win32serviceutil.StartService("Spooler")
            for _ in range(10):
                time.sleep(1)
                if win32serviceutil.QueryServiceStatus("Spooler")[1] == win32service.SERVICE_RUNNING:
                    break
        else:
            subprocess.run(["net", "start", "Spooler"],
                           capture_output=True, timeout=30)
            time.sleep(2)
        log("Print Spooler started.", "SUCCESS")
        return True
    except Exception as e:
        log(f"Error starting Spooler: {e}", "ERROR")
        return False


def _test_printers(printer_names: List[str]):
    """Ping network printers and report WMI status."""
    if not printer_names:
        printer_names = get_all_printers()
    if not printer_names:
        log("No printers found to test.", "WARN")
        return

    log("--- Printer status check ---")
    for name in printer_names:
        # WMI status
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Printer -Filter 'Name=\"{name.replace(chr(39), chr(39)*2)}\"').PrinterStatus"],
                capture_output=True, text=True, timeout=10,
            )
            status_val = r.stdout.strip()
            status_map = {
                "1": "Other", "2": "Unknown", "3": "Idle", "4": "Printing",
                "5": "Warmup", "6": "Stopped", "7": "Offline",
            }
            status_str = status_map.get(status_val, status_val or "N/A")
            level = "SUCCESS" if status_val in ("3", "4") else ("ERROR" if status_val == "7" else "WARN")
            log(f"  {name}: {status_str}", level)
        except Exception:
            log(f"  {name}: status check failed", "WARN")

        # Ping network printers
        try:
            if HAS_WIN32:
                hp = win32print.OpenPrinter(name)
                try:
                    info = win32print.GetPrinter(hp, 2)
                    port = info.get("pPortName", "")
                finally:
                    win32print.ClosePrinter(hp)
            else:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"(Get-Printer -Name '{name}').PortName"],
                    capture_output=True, text=True, timeout=10,
                )
                port = r.stdout.strip()

            # Resolve port to IP address
            ip_r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-PrinterPort -Name '{port}' -ErrorAction SilentlyContinue).PrinterHostAddress"],
                capture_output=True, text=True, timeout=10,
            )
            ip = ip_r.stdout.strip()
            if ip:
                ping = subprocess.run(
                    ["ping", "-n", "2", "-w", "1000", ip],
                    capture_output=True, timeout=10,
                )
                ok = ping.returncode == 0
                log(f"  {name} @ {ip}: ping {'OK' if ok else 'FAILED'}", "SUCCESS" if ok else "ERROR")
        except Exception:
            pass  # Not a network printer or can't get IP — skip silently


def run_fix(
    selected_printers: List[str],
    flush_dns: bool = False,
    clear_arp: bool = False,
    notify_fn: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """
    Full printer fix sequence:
      1. Stop Print Spooler
      2. Clear spool folder
      3. Optional: flush DNS / clear ARP
      4. Start Print Spooler
      5. Test selected printers
    Returns True on overall success.
    """
    log("=" * 52)
    log(f"{APP_NAME} fix started")
    targets = selected_printers or ["(all)"]
    log(f"Target printers: {', '.join(targets)}")
    log("=" * 52)

    ok = True
    ok &= _stop_spooler()
    deleted = _clear_spool()

    if flush_dns:
        _flush_dns()
    if clear_arp:
        _clear_arp()

    ok &= _start_spooler()

    _test_printers(selected_printers)

    log("=" * 52)
    if ok:
        msg = f"Done — cleared {deleted} stuck job(s)."
        log(f"{APP_NAME} fix completed successfully. {msg}", "SUCCESS")
        if notify_fn:
            notify_fn("Fix Complete", msg)
    else:
        log(f"{APP_NAME} fix completed with errors — see log.", "WARN")
        if notify_fn:
            notify_fn("Fix Completed (errors)", "Some steps failed — check View Log.")
    log("=" * 52)
    return ok


# ===========================================================================
# --fix-now mode: runs fix then exits (used when spawned elevated)
# ===========================================================================

def run_fix_headless():
    """Called when launched with --fix-now flag (elevated subprocess)."""
    cfg = load_config()
    log("SpoolMedic running in headless fix mode (elevated subprocess)")
    run_fix(
        selected_printers=cfg.get("selected_printers", []),
        flush_dns=cfg.get("flush_dns", False),
        clear_arp=cfg.get("clear_arp", False),
    )


# ===========================================================================
# Task Scheduler startup management
# ===========================================================================

def _app_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{_python_exe()}" "{_script_path()}"'


def task_exists() -> bool:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"if (Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue) {{ 'YES' }} else {{ 'NO' }}"],
        capture_output=True, text=True, timeout=15,
    )
    return "YES" in r.stdout


def create_startup_task(elevated: bool = True) -> bool:
    """Create (or replace) a Task Scheduler logon task via PowerShell.

    Uses Register-ScheduledTask for full control over settings:
    - Runs whether on battery or plugged in
    - Won't stop when switching to battery
    - 30-second startup delay to let the desktop settle
    - Start-in directory set to the script's folder
    """
    import tempfile

    run_level = "Highest" if elevated else "Limited"
    exe = _python_exe()
    script = _script_path()
    script_dir = str(Path(script).parent)

    ps_code = (
        f"$action = New-ScheduledTaskAction "
        f"-Execute '{exe}' "
        f"""-Argument '""{script}""' """
        f"-WorkingDirectory '{script_dir}'\n"
        f"$trigger = New-ScheduledTaskTrigger -AtLogOn\n"
        f"$trigger.Delay = 'PT30S'\n"
        f"$settings = New-ScheduledTaskSettingsSet "
        f"-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        f"-StartWhenAvailable "
        f"-ExecutionTimeLimit (New-TimeSpan -Hours 0)\n"
        f"$principal = New-ScheduledTaskPrincipal "
        f"-UserId $env:USERNAME "
        f"-LogonType Interactive -RunLevel {run_level}\n"
        f"Register-ScheduledTask -Force "
        f"-TaskName '{TASK_NAME}' "
        f"-Action $action -Trigger $trigger "
        f"-Settings $settings -Principal $principal\n"
    )

    # Write to a temp .ps1 to avoid shell-escaping issues
    tmp = Path(tempfile.gettempdir()) / f"spoolmedic_task_{os.getpid()}.ps1"
    try:
        tmp.write_text(ps_code, encoding="utf-8")
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(tmp)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            log("Startup task created.", "SUCCESS")
            return True
        log(f"Failed to create startup task: {r.stderr.strip()}", "ERROR")
        return False
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def remove_startup_task() -> bool:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue"],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode == 0:
        log("Startup task removed.", "SUCCESS")
    return True  # Not existing is also fine


# ===========================================================================
# Icon creation
# ===========================================================================

def make_icon_image(size: int = 64, busy: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    s   = size / 64  # scale factor

    def r(x1, y1, x2, y2):
        return [int(x1*s), int(y1*s), int(x2*s), int(y2*s)]

    def e(x1, y1, x2, y2):
        return [int(x1*s), int(y1*s), int(x2*s), int(y2*s)]

    body_fill = C_ORANGE if busy else C_BLUE

    # Printer body
    d.rectangle(r(6, 20, 58, 46), fill=body_fill, outline=C_DARK_BLUE, width=max(1, int(2*s)))
    # Paper output tray
    d.rectangle(r(16, 37, 48, 53), fill=C_LIGHT_BG, outline=C_DARK_BLUE, width=max(1, int(1*s)))
    # Paper input (top)
    d.rectangle(r(20, 11, 44, 22), fill=C_LIGHT_BG, outline=C_DARK_BLUE, width=max(1, int(1*s)))
    # Feed rollers (small circles on body)
    for cx in (14, 24, 34):
        d.ellipse(e(cx-3, 27, cx+3, 33), fill=C_DARK_BLUE)
    # Status LED
    led_color = C_ORANGE if busy else C_GREEN
    d.ellipse(e(46, 24, 55, 33), fill=led_color, outline=C_DARK_BLUE, width=max(1, int(1*s)))

    # Medical cross (red) — overlaid on output tray area
    cx_c, cy_c = int(32*s), int(45*s)
    arm   = max(5, int(7*s))
    thick = max(2, int(3*s))
    # Vertical bar
    d.rectangle([cx_c - thick//2, cy_c - arm, cx_c + thick//2, cy_c + arm], fill=C_RED)
    # Horizontal bar
    d.rectangle([cx_c - arm, cy_c - thick//2, cx_c + arm, cy_c + thick//2], fill=C_RED)

    return img


# ===========================================================================
# Settings Window
# ===========================================================================

class SettingsWindow:
    def __init__(self, root: tk.Tk, config: dict, on_save: Callable):
        self.config   = dict(config)
        self.on_save  = on_save
        self._printers: List[str] = []

        self.win = tk.Toplevel(root)
        self.win.title(f"{APP_NAME} Settings")
        self.win.geometry("480x540")
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.lift()
        self.win.focus_force()
        self._center(480, 540)
        self._build()

    def _center(self, w: int, h: int):
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _build(self):
        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        # ---- Tab 1: Printers ----
        pf = ttk.Frame(nb, padding=10)
        nb.add(pf, text="  Printers  ")

        ttk.Label(
            pf,
            text=(
                "Check the printers to include in fix and status tests.\n"
                "If all are checked (or none), the fix targets all printers."
            ),
            justify="left",
            wraplength=440,
        ).pack(anchor="w", pady=(0, 8))

        lf = ttk.LabelFrame(pf, text="Installed Printers", padding=6)
        lf.pack(fill="both", expand=True)

        sb  = ttk.Scrollbar(lf, orient="vertical")
        self.lb = tk.Listbox(
            lf,
            selectmode="multiple",
            yscrollcommand=sb.set,
            height=10,
            font=("Segoe UI", 10),
            activestyle="none",
            selectbackground=C_BLUE,
            selectforeground="white",
        )
        sb.config(command=self.lb.yview)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btn_row = ttk.Frame(pf)
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="Refresh",    command=self._refresh).pack(side="left")
        ttk.Button(btn_row, text="Select All", command=self._select_all).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Clear",      command=self._clear_sel).pack(side="left")

        self._refresh()

        # ---- Tab 2: Options ----
        of = ttk.Frame(nb, padding=14)
        nb.add(of, text="  Options  ")

        self.v_startup  = tk.BooleanVar(value=self.config.get("run_at_startup",      False))
        self.v_autofix  = tk.BooleanVar(value=self.config.get("auto_fix_on_startup", False))
        self.v_notify   = tk.BooleanVar(value=self.config.get("show_notifications",  True))
        self.v_dns      = tk.BooleanVar(value=self.config.get("flush_dns",           False))
        self.v_arp      = tk.BooleanVar(value=self.config.get("clear_arp",           False))

        section = lambda title: ttk.Label(of, text=title, font=("Segoe UI", 9, "bold"))

        section("Startup").pack(anchor="w", pady=(0, 4))
        ttk.Checkbutton(
            of,
            text="Run SpoolMedic automatically at Windows logon",
            variable=self.v_startup,
        ).pack(anchor="w", padx=16)
        ttk.Checkbutton(
            of,
            text="Automatically run fix when app starts",
            variable=self.v_autofix,
        ).pack(anchor="w", padx=32)

        ttk.Separator(of, orient="horizontal").pack(fill="x", pady=10)

        section("Fix Options").pack(anchor="w", pady=(0, 4))
        ttk.Checkbutton(
            of,
            text="Flush DNS cache  (helps with network printers losing their IP)",
            variable=self.v_dns,
        ).pack(anchor="w", padx=16)
        ttk.Checkbutton(
            of,
            text="Clear ARP cache  (forces fresh ARP resolution for printer IPs)",
            variable=self.v_arp,
        ).pack(anchor="w", padx=16)

        ttk.Separator(of, orient="horizontal").pack(fill="x", pady=10)

        section("Notifications").pack(anchor="w", pady=(0, 4))
        ttk.Checkbutton(
            of,
            text="Show balloon notification after fix completes",
            variable=self.v_notify,
        ).pack(anchor="w", padx=16)

        ttk.Separator(of, orient="horizontal").pack(fill="x", pady=10)

        # Admin status row
        if is_admin():
            status_text = "Running as Administrator"
            fg = "green"
        else:
            status_text = "Not running as Administrator — fix will request elevation each time"
            fg = "#c0392b"
        ttk.Label(of, text=status_text, foreground=fg, wraplength=420, justify="left").pack(anchor="w")
        if not is_admin():
            ttk.Button(of, text="Relaunch as Administrator",
                       command=elevate_and_restart).pack(anchor="w", pady=(6, 0))

        # ---- Bottom buttons ----
        bf = ttk.Frame(self.win)
        bf.pack(fill="x", padx=10, pady=10)
        ttk.Button(bf, text="Save",   command=self._save,         width=10).pack(side="right", padx=(4, 0))
        ttk.Button(bf, text="Cancel", command=self.win.destroy,   width=10).pack(side="right")

    def _refresh(self):
        self.lb.delete(0, "end")
        printers = get_all_printers()
        self._printers = printers
        selected = set(self.config.get("selected_printers", []))

        for i, p in enumerate(printers):
            self.lb.insert("end", p)
            if not selected or p in selected:
                self.lb.selection_set(i)

    def _select_all(self): self.lb.selection_set(0, "end")
    def _clear_sel(self):  self.lb.selection_clear(0, "end")

    def _save(self):
        sel = self.lb.curselection()
        if len(sel) == len(self._printers):
            chosen = []  # treat "all" as empty (= all)
        else:
            chosen = [self._printers[i] for i in sel]

        self.config.update({
            "selected_printers":    chosen,
            "run_at_startup":       self.v_startup.get(),
            "auto_fix_on_startup":  self.v_autofix.get(),
            "show_notifications":   self.v_notify.get(),
            "flush_dns":            self.v_dns.get(),
            "clear_arp":            self.v_arp.get(),
        })
        save_config(self.config)

        # Handle startup task
        want_startup = self.v_startup.get()
        if is_admin():
            if want_startup:
                create_startup_task(elevated=True)
            else:
                remove_startup_task()
        elif want_startup and not task_exists():
            messagebox.showwarning(
                "Admin Required",
                "Creating a startup task requires administrator rights.\n"
                "Please relaunch SpoolMedic as administrator, then re-save settings.",
                parent=self.win,
            )

        if self.on_save:
            self.on_save(self.config)
        self.win.destroy()


# ===========================================================================
# Log Viewer Window
# ===========================================================================

class LogWindow:
    def __init__(self, root: tk.Tk):
        self.win = tk.Toplevel(root)
        self.win.title(f"{APP_NAME} — Log")
        self.win.geometry("720x500")
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry(f"720x500+{(sw-720)//2}+{(sh-500)//2}")
        self.win.lift()
        self.win.focus_force()
        self._build()
        self._load()

    def _build(self):
        tf = ttk.Frame(self.win)
        tf.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        self.text = scrolledtext.ScrolledText(
            tf, font=("Consolas", 9), state="disabled", wrap="word",
        )
        self.text.pack(fill="both", expand=True)
        self.text.tag_config("ERROR",   foreground=C_RED)
        self.text.tag_config("SUCCESS", foreground="#2e7d32")
        self.text.tag_config("WARN",    foreground=C_ORANGE)

        bf = ttk.Frame(self.win)
        bf.pack(fill="x", padx=10, pady=10)
        ttk.Button(bf, text="Refresh",   command=self._load).pack(side="left")
        ttk.Button(bf, text="Clear Log", command=self._clear).pack(side="left", padx=6)
        ttk.Button(bf, text="Close",     command=self.win.destroy).pack(side="right")

    def _load(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        if LOG_FILE.exists():
            try:
                lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
                for line in lines:
                    tag = (
                        "ERROR"   if "[ERROR]"   in line else
                        "SUCCESS" if "[SUCCESS]" in line else
                        "WARN"    if "[WARN]"    in line else
                        None
                    )
                    self.text.insert("end", line + "\n", tag or "")
                self.text.see("end")
            except Exception as e:
                self.text.insert("end", f"Could not read log: {e}")
        else:
            self.text.insert("end", "No log yet — run a fix to generate entries.")
        self.text.config(state="disabled")

    def _clear(self):
        if messagebox.askyesno("Clear Log", "Clear the entire log file?", parent=self.win):
            try:
                LOG_FILE.write_text("", encoding="utf-8")
                self._load()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=self.win)


# ===========================================================================
# About Window
# ===========================================================================

class AboutWindow:
    def __init__(self, root: tk.Tk, icon_image: Optional[Image.Image] = None):
        self.win = tk.Toplevel(root)
        self.win.title(f"About {APP_NAME}")
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self.win.grab_set()
        self.win.lift()
        self.win.focus_force()
        self._logo = None  # keep a reference so the image isn't garbage-collected
        self._build(icon_image)
        self._center()

    def _center(self):
        self.win.update_idletasks()
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    def _build(self, icon_image: Optional[Image.Image]):
        pad = tk.Frame(self.win, padx=28, pady=20)
        pad.pack()

        if icon_image is not None:
            try:
                self._logo = ImageTk.PhotoImage(icon_image.resize((64, 64)))
                tk.Label(pad, image=self._logo).pack(pady=(0, 8))
            except Exception:
                self._logo = None

        tk.Label(pad, text=APP_NAME, font=("Segoe UI", 16, "bold"),
                 fg=C_DARK_BLUE).pack()
        tk.Label(pad, text=f"Version {APP_VERSION}", fg="#555").pack(pady=(2, 0))
        tk.Label(pad, text="Fixes stuck print queues without a reboot.",
                 fg="#333").pack(pady=(6, 12))

        def _link(text: str, url: str):
            lbl = tk.Label(pad, text=text, fg="#1a6ec8", cursor="hand2",
                           font=("Segoe UI", 9, "underline"))
            lbl.pack()
            lbl.bind("<Button-1>", lambda e: webbrowser.open(url))
            return lbl

        _link("varo.industries/apps", APPS_URL)
        _link("github.com/VAROIndustries/SpoolMedic", GITHUB_URL)

        tk.Label(pad, text="© 2026 VARØ Industries", fg="#888").pack(pady=(12, 10))
        tk.Button(pad, text="Close", width=10, command=self.win.destroy).pack()


# ===========================================================================
# Main Application
# ===========================================================================

class SpoolMedicApp:
    def __init__(self):
        self.config       = load_config()
        self.icon:  Optional[pystray.Icon] = None
        self.root:  Optional[tk.Tk]        = None
        self._fixing      = False
        self._normal_icon = make_icon_image(64, busy=False)
        self._busy_icon   = make_icon_image(64, busy=True)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def notify(self, title: str, message: str):
        if self.config.get("show_notifications", True) and self.icon:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Fix
    # ------------------------------------------------------------------

    def _elevate_fix(self):
        """Spawn an elevated subprocess to run the fix, then show notification."""
        exe   = _python_exe()
        args  = f'"{_script_path()}" --fix-now'
        ret   = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
        if ret <= 32:
            self.notify("SpoolMedic", "Could not get administrator rights.")

    def trigger_fix(self, _icon=None, _item=None):
        """Called from tray menu or double-click."""
        if self._fixing:
            self.notify(APP_NAME, "Fix is already in progress...")
            return

        if not is_admin():
            self._elevate_fix()
            return

        def _run():
            self._fixing = True
            if self.icon:
                self.icon.icon = self._busy_icon
                self.icon.title = f"{APP_NAME} — fixing..."
            try:
                run_fix(
                    selected_printers=self.config.get("selected_printers", []),
                    flush_dns=self.config.get("flush_dns", False),
                    clear_arp=self.config.get("clear_arp", False),
                    notify_fn=self.notify,
                )
            finally:
                self._fixing = False
                if self.icon:
                    self.icon.icon  = self._normal_icon
                    self.icon.title = APP_NAME

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # UI helpers (must be marshalled to main thread via root.after)
    # ------------------------------------------------------------------

    def open_settings(self, _icon=None, _item=None):
        if self.root:
            self.root.after(0, lambda: SettingsWindow(self.root, self.config, self._on_config_saved))

    def open_log(self, _icon=None, _item=None):
        if self.root:
            self.root.after(0, lambda: LogWindow(self.root))

    def open_about(self, _icon=None, _item=None):
        if self.root:
            self.root.after(0, lambda: AboutWindow(self.root, self._normal_icon))

    def _on_config_saved(self, new_cfg: dict):
        self.config = new_cfg

    def exit_app(self, _icon=None, _item=None):
        log("SpoolMedic exiting.")
        if self.icon:
            self.icon.stop()
        if self.root:
            self.root.after(0, self.root.destroy)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self):
        log(f"{APP_NAME} v{APP_VERSION} starting — admin={is_admin()}, win32={HAS_WIN32}")

        # Hidden Tk root (required for dialogs and to keep process alive)
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        # Keep root alive even when all Toplevels are closed
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)

        # Build tray menu
        admin_label = "✔ Running as Administrator" if is_admin() else "⚠ Not Administrator (fix will request UAC)"
        menu = pystray.Menu(
            pystray.MenuItem(f"{APP_NAME} v{APP_VERSION}", None, enabled=False),
            pystray.MenuItem(admin_label,                  None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Fix Print Queue Now", self.trigger_fix, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings…", self.open_settings),
            pystray.MenuItem("View Log…", self.open_log),
            pystray.MenuItem("About…",    self.open_about),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self.exit_app),
        )

        self.icon = pystray.Icon(
            name  = APP_NAME,
            icon  = self._normal_icon,
            title = APP_NAME,
            menu  = menu,
        )

        # Run pystray in background thread; tkinter runs on main thread
        t = threading.Thread(target=self.icon.run, daemon=True)
        t.start()

        # Auto-fix on startup (after short delay to let tray settle)
        if self.config.get("auto_fix_on_startup", False):
            threading.Timer(4.0, self.trigger_fix).start()

        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.exit_app()


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    if "--fix-now" in sys.argv:
        # Headless elevated mode: run fix and exit
        run_fix_headless()
        sys.exit(0)

    app = SpoolMedicApp()
    app.run()
