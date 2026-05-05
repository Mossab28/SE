@echo off
title Nereides - Kiosk Launcher
echo Lancement de l'interface pilote en plein ecran...

set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not exist "%CHROME%" set "CHROME=C:\Program Files\Microsoft\Edge\Application\msedge.exe"

if not exist "%CHROME%" (
  echo Aucun navigateur Chrome/Edge trouve.
  pause
  exit /b 1
)

:: Attendre que le serveur HTTP soit pret
timeout /t 5 /nobreak >nul

start "" "%CHROME%" --kiosk --noerrdialogs --disable-infobars --disable-translate --no-first-run --fast --fast-start --disable-features=TranslateUI --disk-cache-dir=NUL --user-data-dir="%TEMP%\nereides-kiosk" "http://localhost:8080/index.html"
