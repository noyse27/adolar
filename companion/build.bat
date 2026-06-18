@echo off
echo Installing dependencies...
pip install pywebview pyinstaller

echo Building AdolarRadio.exe (single file)...
pyinstaller adolar_radio.spec --clean --noconfirm

echo.
echo Done! AdolarRadio.exe is in dist\
echo.
echo First launch: enter your Adolar server URL (e.g. http://192.168.1.X:15002)
echo Settings are saved to %%APPDATA%%\AdolarRadio\config.json
pause
