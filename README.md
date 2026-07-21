# SpoolMedic

**🌐 Tool page: [varo.industries/tools/spoolmedic](https://varo.industries/tools/spoolmedic)** — features, screenshots, install, and FAQ.


**Fix stuck print queues without rebooting.**

SpoolMedic is a lightweight Windows system tray utility that resets the Windows Print Spooler service and clears stuck print jobs on demand — everything your printer needs that normally requires a full reboot, in a single click.

---

## Features

- **System tray icon** — sits quietly in the notification area until you need it
- **One-click fix** — double-click the tray icon or use the right-click menu
- **Full spooler reset** — stops the service, wipes the spool folder, restarts clean
- **Optional extras** — flush DNS cache and/or clear ARP cache (great for network printers)
- **Printer selection** — target specific printers for status testing, or hit all of them
- **Run at startup** — installs a Task Scheduler entry so it's always available after login
- **Auto-fix on startup** — optionally run the fix automatically every time you log in
- **Built-in log viewer** — color-coded log of every fix run, right inside the app
- **UAC-aware** — if not running as admin, Fix spawns a brief elevated subprocess (UAC prompt only when you actually fix, not on every startup)

---

## Requirements

- Windows 10 / 11
- Python 3.10+ ([download](https://python.org/downloads/))
- The Python packages listed in `requirements.txt`

---

## Setup

### 1. Install dependencies

Double-click **`install.bat`**, or run manually:

```bat
pip install pystray Pillow pywin32
```

### 2. Launch SpoolMedic

Double-click **`launch.bat`** — a printer icon will appear in your system tray.

To run elevated immediately (no UAC prompts when fixing):

```
Right-click launch.bat → Run as administrator
```

### 3. Enable startup (optional but recommended)

1. Right-click the tray icon → **Settings**
2. Go to the **Options** tab
3. Check **"Run SpoolMedic automatically at Windows logon"**
4. Click **Save**

> This creates a Task Scheduler entry that runs SpoolMedic elevated at every login — no UAC prompt on startup.

---

## Usage

| Action | How |
|--------|-----|
| Fix stuck print queue | Double-click tray icon, or right-click → **Fix Print Queue Now** |
| Configure printers / options | Right-click → **Settings…** |
| View fix history | Right-click → **View Log…** |
| Exit | Right-click → **Exit** |

---

## What the Fix Does

In order:

1. **Stop** the Windows Print Spooler service (`Spooler`)
2. **Delete** all files in `%WINDIR%\System32\spool\PRINTERS` (pending/stuck jobs)
3. *(Optional)* **Flush DNS** resolver cache — `ipconfig /flushdns`
4. *(Optional)* **Clear ARP** cache — `netsh interface ip delete arpcache`
5. **Start** the Print Spooler service
6. **Test** selected printers (WMI status + network ping for IP printers)

This is the exact sequence Windows performs for printers during a reboot.

---

## Files

| File | Description |
|------|-------------|
| `SpoolMedic.py` | Main application |
| `requirements.txt` | Python dependencies |
| `install.bat` | Installs dependencies |
| `launch.bat` | Launches the tray app |
| `Clear-PrintSpooler.ps1` | Original PowerShell script (kept for reference) |

---

## Logs

Logs are written to:

```
%APPDATA%\SpoolMedic\SpoolMedic.log
```

Open them from the tray icon → **View Log…**
---

## More from VARØ Industries

Free web apps, tools, and open-source projects → [varo.industries/apps](https://varo.industries/apps#github)

