@echo off
rem Double-click launcher: installs everything on first run, then opens the B-roll sourcing window.
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

start "" ".venv\Scripts\autocut-sources-gui.exe"
