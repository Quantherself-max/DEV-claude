@echo off
title Liq Terminal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 run.py
  goto fin
)
where python >nul 2>nul
if %errorlevel%==0 (
  python run.py
  goto fin
)
echo.
echo Python nest pas installe sur ce PC.
echo 1) Installe-le depuis la page qui va souvrir (coche "Add Python to PATH" pendant linstallation).
echo 2) Puis double-clique de nouveau sur ce fichier.
start "" https://www.python.org/downloads/
:fin
echo.
pause
