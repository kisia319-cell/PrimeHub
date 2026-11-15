@echo off
setlocal
cd /d "%~dp0"
py -m PyInstaller --noconfirm --clean --onefile --windowed --name PrimeHub --distpath "%~dp0" --workpath "%~dp0build" --specpath "%~dp0" "%~dp0primehub.py"
if errorlevel 1 exit /b 1
copy /y "%~dp0PrimeHub.exe" "%USERPROFILE%\Desktop\PrimeHub.exe" >nul
echo PrimeHub.exe rebuilt and copied to Desktop.
pause
