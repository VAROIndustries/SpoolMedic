# PrinterStuff

A Windows utility to clear and reset a stuck Windows print spooler and print queue.

## Usage

Double-click `Run-PrintSpoolerFix.bat` (run as Administrator for best results).

This will execute `Clear-PrintSpooler.ps1` which:
1. Stops the Print Spooler service
2. Clears all stuck print jobs from the queue
3. Restarts the Print Spooler service
4. Logs diagnostics and results

## When to Use

- Print jobs are stuck and won't clear
- Printer shows as offline despite being connected
- Print queue is frozen and unresponsive

## Tech

PowerShell script (`.ps1`) with batch file launcher (`.bat`) — requires Administrator privileges
