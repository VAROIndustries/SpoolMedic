@echo off
setlocal

echo ============================================
echo  SpoolMedic - Installing dependencies
echo ============================================
echo.

:: Find Python — prefer known path, fall back to PATH
set PYEXE=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PYEXE%" set PYEXE=python

echo Using Python: %PYEXE%
echo.

"%PYEXE%" -m pip install --upgrade pip --quiet
"%PYEXE%" -m pip install pystray Pillow pywin32

echo.
echo ============================================
echo  Installation complete!
echo.
echo  To launch SpoolMedic now, run launch.bat
echo  or double-click SpoolMedic.py
echo ============================================
echo.
pause
