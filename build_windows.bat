@echo off
rem Builds dist\UnoByStorm.exe (one file, no console window). Run this on Windows.
rem Put Monocraft.ttf in an "assets" folder first if you want the pixel font inside the exe.
setlocal
set DATA=
if exist assets set DATA=--add-data "assets;assets"
py -m pip install --upgrade pygame pyinstaller || goto :fail
py -m PyInstaller --noconfirm --clean --onefile --windowed --name UnoByStorm %DATA% main.py || goto :fail
echo.
echo Done: dist\UnoByStorm.exe
exit /b 0
:fail
echo Build failed - see the messages above.
exit /b 1
