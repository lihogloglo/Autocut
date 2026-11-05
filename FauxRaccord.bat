@echo off
rem First install (and update after pulling new code): installs uv and the Python packages, puts an
rem FauxRaccord shortcut on the desktop and opens the window. Afterwards the shortcut is enough; everything
rem else (ffmpeg, transcription model, browser, Premiere panel) is installed from the window's
rem Installation page.
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

rem Desktop shortcut to the window itself, with the axe icon (rewritten each time: it follows the folder).
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\FauxRaccord.lnk');" ^
  "$s.TargetPath='%~dp0.venv\Scripts\fauxraccord-gui.exe'; $s.WorkingDirectory='%~dp0';" ^
  "$s.IconLocation='%~dp0src\fauxraccord\web\fauxraccord.ico'; $s.Save()"

start "" ".venv\Scripts\fauxraccord-gui.exe"
