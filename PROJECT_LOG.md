# PrinterStuff Project Log

## Project Overview
Scripts for managing print spooler and printer maintenance on Windows.

---

## Session: 2025-01-05

### Prompt Used
> create a script that force deletes everything from the print spooler queue and then restarts the printer service and then tests it to ensure it can communicate with the printer.

### Work Completed
1. Created `backups/` folder for any future file backups
2. Created `Clear-PrintSpooler.ps1` - PowerShell script that:
   - Stops the Print Spooler service
   - Force deletes all files from `C:\Windows\System32\spool\PRINTERS`
   - Restarts the Print Spooler service
   - Tests communication with all installed printers (ping test for network printers, WMI status check)
   - Logs all actions to `PrintSpooler_Log.txt`

### How to Use
```powershell
# Run as Administrator (required)
.\Clear-PrintSpooler.ps1

# Test specific printer only
.\Clear-PrintSpooler.ps1 -PrinterName "HP LaserJet"

# Skip communication test
.\Clear-PrintSpooler.ps1 -SkipTest
```

### Files Created
- `Clear-PrintSpooler.ps1` - Main script
- `PROJECT_LOG.md` - This log file
- `backups/` - Folder for file backups

### Status
**COMPLETE** - Script ready for use.

---
