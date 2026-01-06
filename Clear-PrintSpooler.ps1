#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Clears the print spooler queue, restarts the service, and tests printer communication.

.DESCRIPTION
    This script:
    1. Stops the Print Spooler service
    2. Force deletes all pending print jobs from the spool folder
    3. Restarts the Print Spooler service
    4. Tests communication with available printers

.NOTES
    Must be run as Administrator
    Author: Claude Code
    Created: 2025-01-05
#>

param(
    [string]$PrinterName = "",  # Specific printer to test, or empty for all printers
    [switch]$SkipTest           # Skip the printer communication test
)

$ErrorActionPreference = "Stop"
$SpoolFolder = "$env:SystemRoot\System32\spool\PRINTERS"
$LogFile = Join-Path $PSScriptRoot "PrintSpooler_Log.txt"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "[$timestamp] [$Level] $Message"
    Write-Host $logEntry -ForegroundColor $(switch($Level) {
        "ERROR" { "Red" }
        "WARN"  { "Yellow" }
        "SUCCESS" { "Green" }
        default { "White" }
    })
    Add-Content -Path $LogFile -Value $logEntry
}

function Stop-PrintSpoolerService {
    Write-Log "Stopping Print Spooler service..."
    try {
        $service = Get-Service -Name "Spooler"
        if ($service.Status -eq "Running") {
            Stop-Service -Name "Spooler" -Force
            Start-Sleep -Seconds 2
            Write-Log "Print Spooler service stopped successfully." "SUCCESS"
        } else {
            Write-Log "Print Spooler service was already stopped." "WARN"
        }
    } catch {
        Write-Log "Failed to stop Print Spooler service: $_" "ERROR"
        throw
    }
}

function Clear-SpoolFolder {
    Write-Log "Clearing print spool folder: $SpoolFolder"
    try {
        if (Test-Path $SpoolFolder) {
            $files = Get-ChildItem -Path $SpoolFolder -File -ErrorAction SilentlyContinue
            $fileCount = ($files | Measure-Object).Count

            if ($fileCount -gt 0) {
                Write-Log "Found $fileCount file(s) in spool folder. Deleting..."
                $files | ForEach-Object {
                    Remove-Item -Path $_.FullName -Force -ErrorAction SilentlyContinue
                    Write-Log "Deleted: $($_.Name)"
                }
                Write-Log "Spool folder cleared successfully." "SUCCESS"
            } else {
                Write-Log "Spool folder was already empty." "WARN"
            }
        } else {
            Write-Log "Spool folder does not exist at expected location." "WARN"
        }
    } catch {
        Write-Log "Error clearing spool folder: $_" "ERROR"
        throw
    }
}

function Start-PrintSpoolerService {
    Write-Log "Starting Print Spooler service..."
    try {
        Start-Service -Name "Spooler"
        Start-Sleep -Seconds 2

        $service = Get-Service -Name "Spooler"
        if ($service.Status -eq "Running") {
            Write-Log "Print Spooler service started successfully." "SUCCESS"
        } else {
            Write-Log "Print Spooler service failed to start. Status: $($service.Status)" "ERROR"
            throw "Service did not start properly"
        }
    } catch {
        Write-Log "Failed to start Print Spooler service: $_" "ERROR"
        throw
    }
}

function Test-PrinterCommunication {
    param([string]$SpecificPrinter = "")

    Write-Log "Testing printer communication..."

    try {
        if ($SpecificPrinter) {
            $printers = Get-Printer -Name $SpecificPrinter -ErrorAction Stop
        } else {
            $printers = Get-Printer
        }

        if (($printers | Measure-Object).Count -eq 0) {
            Write-Log "No printers found on this system." "WARN"
            return $false
        }

        $allSuccess = $true
        foreach ($printer in $printers) {
            Write-Log "Testing: $($printer.Name) (Driver: $($printer.DriverName))"

            # Check printer status
            $printerStatus = $printer.PrinterStatus
            Write-Log "  Status: $printerStatus"

            # Try to get more detailed port info
            try {
                $port = Get-PrinterPort -Name $printer.PortName -ErrorAction SilentlyContinue
                if ($port) {
                    Write-Log "  Port: $($printer.PortName)"
                    if ($port.PrinterHostAddress) {
                        Write-Log "  IP Address: $($port.PrinterHostAddress)"

                        # Test network connectivity for network printers
                        $pingResult = Test-Connection -ComputerName $port.PrinterHostAddress -Count 2 -Quiet
                        if ($pingResult) {
                            Write-Log "  Network connectivity: OK" "SUCCESS"
                        } else {
                            Write-Log "  Network connectivity: FAILED (printer may be offline)" "ERROR"
                            $allSuccess = $false
                        }
                    }
                }
            } catch {
                Write-Log "  Could not retrieve port details" "WARN"
            }

            # Check if printer is ready by querying WMI
            try {
                $wmiPrinter = Get-CimInstance -ClassName Win32_Printer -Filter "Name='$($printer.Name.Replace("'","''"))'" -ErrorAction SilentlyContinue
                if ($wmiPrinter) {
                    $statusCodes = @{
                        1 = "Other"; 2 = "Unknown"; 3 = "Idle"; 4 = "Printing"
                        5 = "Warmup"; 6 = "Stopped Printing"; 7 = "Offline"
                    }
                    $extStatusCodes = @{
                        1 = "Other"; 2 = "Unknown"; 3 = "Idle"; 4 = "Printing"; 5 = "Warming Up"
                        6 = "Stopped Printing"; 7 = "Offline"; 8 = "Paused"; 9 = "Error"
                        10 = "Busy"; 11 = "Not Available"; 12 = "Waiting"; 13 = "Processing"
                        14 = "Initialization"; 15 = "Power Save"; 16 = "Pending Deletion"
                        17 = "I/O Active"; 18 = "Manual Feed"
                    }

                    $status = if ($statusCodes[$wmiPrinter.PrinterState]) { $statusCodes[$wmiPrinter.PrinterState] } else { "Unknown ($($wmiPrinter.PrinterState))" }
                    Write-Log "  WMI Printer State: $status"

                    if ($wmiPrinter.PrinterState -eq 3 -or $wmiPrinter.PrinterState -eq 4) {
                        Write-Log "  Printer appears ready." "SUCCESS"
                    } elseif ($wmiPrinter.PrinterState -eq 7) {
                        Write-Log "  Printer is OFFLINE" "ERROR"
                        $allSuccess = $false
                    }
                }
            } catch {
                Write-Log "  Could not query WMI printer status" "WARN"
            }

            Write-Log "---"
        }

        return $allSuccess

    } catch {
        Write-Log "Error testing printer communication: $_" "ERROR"
        return $false
    }
}

# Main execution
Write-Log "=========================================="
Write-Log "Print Spooler Cleanup Script Started"
Write-Log "=========================================="

try {
    # Step 1: Stop the service
    Stop-PrintSpoolerService

    # Step 2: Clear the spool folder
    Clear-SpoolFolder

    # Step 3: Start the service
    Start-PrintSpoolerService

    # Step 4: Test printer communication
    if (-not $SkipTest) {
        $testResult = Test-PrinterCommunication -SpecificPrinter $PrinterName
        if ($testResult) {
            Write-Log "All printer tests passed." "SUCCESS"
        } else {
            Write-Log "Some printer tests failed. Check individual results above." "WARN"
        }
    } else {
        Write-Log "Printer communication test skipped (per -SkipTest flag)." "WARN"
    }

    Write-Log "=========================================="
    Write-Log "Script completed successfully!"
    Write-Log "=========================================="

} catch {
    Write-Log "Script failed with error: $_" "ERROR"
    Write-Log "Attempting to restart Print Spooler service..." "WARN"
    try {
        Start-Service -Name "Spooler" -ErrorAction SilentlyContinue
    } catch {
        Write-Log "Could not restart service automatically. Run: Start-Service Spooler" "ERROR"
    }
    exit 1
}
