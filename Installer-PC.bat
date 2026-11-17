@echo off
setlocal
cd /d "%~dp0"
title Installation Derush Auto
echo.
echo  ==== Installation de Derush Auto (PC) ====
echo.

set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY (
  echo  Python n'est pas installe. Installation automatique...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo  Python vient d'etre installe. Ferme cette fenetre et relance Installer-PC.bat.
  pause
  exit /b
)

set "DEST=%LOCALAPPDATA%\DerushAuto"
echo  [1/4] Copie du moteur...
if not exist "%DEST%" mkdir "%DEST%"
xcopy "moteur\*" "%DEST%\" /E /I /Y /Q >nul
copy /Y "version.json" "%DEST%\version.json" >nul

echo  [2/4] Installation des outils d'analyse (quelques minutes)...
%PY% -m pip install --user --upgrade -q -r "%DEST%\requirements.txt"
if errorlevel 1 (
  echo  Echec de l'installation des outils. Verifie ta connexion internet et relance.
  pause
  exit /b
)

echo  [3/4] Installation du panneau dans Premiere...
xcopy "extension\DerushAuto" "%APPDATA%\Adobe\CEP\extensions\DerushAuto\" /E /I /Y /Q >nul
for %%v in (9 10 11 12 13) do reg add "HKCU\Software\Adobe\CSXS.%%v" /v PlayerDebugMode /t REG_SZ /d 1 /f >nul

echo  [4/4] Demarrage automatique du moteur...
for /f "delims=" %%p in ('%PY% -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%p"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
(
  echo @echo off
  echo start "" "%PYW%" "%DEST%\moteur.py"
) > "%STARTUP%\Moteur Derush Auto.bat"
copy /Y "%STARTUP%\Moteur Derush Auto.bat" "%USERPROFILE%\Desktop\Moteur Derush Auto.bat" >nul
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*DerushAuto*moteur.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>nul
start "" "%PYW%" "%DEST%\moteur.py"

echo.
echo  ==== C'est installe ! ====
echo  1. Redemarre Premiere Pro.
echo  2. Menu Fenetre ^> Extensions ^> Derush Auto.
echo  Le moteur demarre tout seul a chaque allumage du PC
echo  et se met a jour automatiquement.
echo.
pause
