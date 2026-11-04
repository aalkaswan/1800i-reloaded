@echo off
setlocal

echo ===============================================================================
echo                PrimeFilm 1800u / 1800i Studio Desktop UI
echo ===============================================================================
echo.

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python 3 was not found in your Windows PATH!
    echo Please install Python 3.9+ from https://www.python.org/ or the Microsoft Store.
    echo (Make sure to check "Add Python to PATH" during installation)
    echo.
    pause
    exit /b 1
)

echo [*] Checking required dependencies...
python -c "import usb.core, libusb_package" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [*] Installing required USB runtime libraries (pyusb, libusb-package, pillow)...
    python -m pip install pyusb libusb-package pillow
)

echo [*] Starting PrimeFilm Studio...
python "%~dp0scripts\primefilm_studio_app.py" %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo [!] Studio application exited with error code %ERRORLEVEL%.
    pause
)

endlocal
