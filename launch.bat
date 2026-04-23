@echo off
:: SpoolMedic launcher
:: Double-click this to start SpoolMedic in the system tray.
:: To run elevated (no UAC prompts on Fix): right-click > Run as administrator

set PYEXE=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\pythonw.exe
if not exist "%PYEXE%" set PYEXE=pythonw

start "" "%PYEXE%" "%~dp0SpoolMedic.py"
