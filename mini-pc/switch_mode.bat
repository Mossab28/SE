@echo off
title Nereides - Switch Mode
echo.
echo  ===== Bridge Nereides - Switch Mode =====
echo.
echo  Mode actuel du startup Windows :
findstr "serial_to_mqtt.py" "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\nereides_startup.bat"
echo.
echo  [1] Mode REEL   (lit COM4, prod)
echo  [2] Mode FAKE   (simule des donnees au hasard)
echo  [3] Mode SCENARIO (cycle NORMAL/WARN/ALERT pour tester couleurs)
echo  [4] Mode RACE   (course 4 min, modele physique pour l'autonomie)
echo  [Q] Quitter
echo.
set /p choice="Choix : "

if /i "%choice%"=="1" set ARGS=
if /i "%choice%"=="2" set ARGS=--fake --http
if /i "%choice%"=="3" set ARGS=--scenario
if /i "%choice%"=="4" set ARGS=--race
if /i "%choice%"=="Q" exit /b

if not defined ARGS (
  echo Choix invalide.
  pause
  exit /b 1
)

:: Tuer les bridges en cours
echo Arret des bridges en cours...
powershell -NoProfile -Command "Get-WmiObject Win32_Process -Filter \"name = 'pythonw.exe' OR name = 'python.exe'\" | Where-Object { $_.CommandLine -like '*serial_to_mqtt*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 2 /nobreak >nul

:: Modifier le startup pour persister le choix
set STARTUP_BAT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\nereides_startup.bat
powershell -NoProfile -Command "(Get-Content '%STARTUP_BAT%') -replace 'serial_to_mqtt\.py[^\"]*\"', 'serial_to_mqtt.py %ARGS%\"' | Set-Content '%STARTUP_BAT%'"

:: Relancer le bridge avec le nouveau mode
echo Lancement du bridge avec : %ARGS%
start "Nereides Bridge" /B cmd /c ""C:\Users\SE\AppData\Local\Programs\Python\Python312\pythonw.exe" -u "C:\Users\SE\Desktop\SE\mini-pc\serial_to_mqtt.py" %ARGS% > "C:\Users\SE\Desktop\SE\mini-pc\logs\bridge.log" 2>&1"

timeout /t 2 /nobreak >nul
echo.
echo Logs (Ctrl+C pour quitter) :
echo.
powershell -NoProfile -Command "Get-Content 'C:\Users\SE\Desktop\SE\mini-pc\logs\bridge.log' -Wait -Tail 10"
