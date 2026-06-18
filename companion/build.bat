@echo off
echo Installing dependencies...
pip install pywebview pyinstaller
if errorlevel 1 (
    echo.
    echo ERROR: pip failed. Make sure Python is installed and in PATH.
    pause & exit /b 1
)

echo Building AdolarRadio.exe (single file)...
python -m PyInstaller adolar_radio.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: Build failed. See output above.
    pause & exit /b 1
)

echo.
echo Done! AdolarRadio.exe is in dist\
echo.
echo First launch: enter your Adolar server URL (e.g. http://192.168.1.X:15002)
echo Settings are saved to %%APPDATA%%\AdolarRadio\config.json
pause
