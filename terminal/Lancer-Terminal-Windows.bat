@echo off
title Liq Terminal
cd /d "%~dp0"
if not exist "%~dp0run.py" (
  echo.
  echo  ============================================================
  echo   Le terminal a ete lance depuis l'interieur du fichier ZIP.
  echo   Windows n'a sorti que ce fichier, sans le reste du programme.
  echo.
  echo   A faire :
  echo    1. Ferme cette fenetre.
  echo    2. Clic droit sur le fichier ZIP telecharge
  echo       puis "Extraire tout..." ^(ou WinRAR : "Extraire ici"^).
  echo    3. Ouvre le dossier extrait, puis le dossier "terminal".
  echo    4. Double-clique sur Lancer-Terminal-Windows.bat
  echo  ============================================================
  echo.
  pause
  exit /b 1
)
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
echo Python n'est pas installe sur ce PC.
echo 1) Installe-le depuis la page qui va s'ouvrir (coche "Add Python to PATH" pendant l'installation).
echo 2) Puis double-clique de nouveau sur ce fichier.
start "" https://www.python.org/downloads/
:fin
echo.
echo Le terminal s'est arrete. Si un message d'erreur est affiche au-dessus, envoie-le en capture.
pause
