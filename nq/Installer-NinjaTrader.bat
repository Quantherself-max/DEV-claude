@echo off
rem Copie l'indicateur NQTickLogger dans le dossier des indicateurs de NinjaTrader 8.
rem Il reste ensuite a le compiler dans NinjaTrader (voir le README, "Brancher NinjaTrader").
chcp 65001 >nul
setlocal
set "SRC=%~dp0ninjatrader\NQTickLogger.cs"
set "DST=%USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\Indicators"
if not exist "%DST%" set "DST=%USERPROFILE%\OneDrive\Documents\NinjaTrader 8\bin\Custom\Indicators"
if not exist "%SRC%" (
  echo Fichier introuvable : %SRC%
  echo Extrais d'abord tout le ZIP, puis relance ce fichier depuis le dossier extrait.
  pause
  exit /b 1
)
if not exist "%DST%" (
  echo Dossier de NinjaTrader 8 introuvable :
  echo   %USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\Indicators
  echo NinjaTrader 8 est-il installe et a-t-il ete ouvert au moins une fois ?
  echo Sinon, copie a la main ninjatrader\NQTickLogger.cs dans le dossier Indicators de NinjaTrader 8.
  pause
  exit /b 1
)
copy /Y "%SRC%" "%DST%\NQTickLogger.cs" >nul
if errorlevel 1 (
  echo La copie a echoue. Ferme NinjaTrader et reessaie, ou copie le fichier a la main.
  pause
  exit /b 1
)
echo.
echo  OK : NQTickLogger.cs copie dans
echo    %DST%
echo.
echo  Etape suivante, dans NinjaTrader :
echo    New ^> NinjaScript Editor, puis touche F5 (compiler).
echo    Ensuite, sur un graphique NQ : clic droit ^> Indicators ^> NQTickLogger ^> Add ^> OK.
echo.
pause
