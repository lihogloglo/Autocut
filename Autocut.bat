@echo off
rem Double-click launcher: installs everything on first run, then opens the Autocut window.
chcp 65001 >nul
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo Premiere utilisation : installation de uv...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

echo Verification des dependances (la premiere fois, quelques minutes)...
uv sync --quiet
if errorlevel 1 (
    echo.
    echo L'installation a echoue. Envoyez une capture de cette fenetre.
    pause
    exit /b 1
)

rem Desktop shortcut to the window itself: after the first run, this file is only needed to update.
if not exist "%USERPROFILE%\Desktop\Autocut.lnk" powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Autocut.lnk');" ^
  "$s.TargetPath='%~dp0.venv\Scripts\autocut-gui.exe'; $s.WorkingDirectory='%~dp0'; $s.Save()"

start "" ".venv\Scripts\autocut-gui.exe"
