@echo off
title Nereides - Test Scenario (cycles couleurs)
echo Lancement du scenario de test des couleurs.
echo Cycles : NORMAL (vert) -^> WARNING (jaune) -^> ALERT (rouge) -^> RECOVERY -^> ...
echo.
echo IMPORTANT : ferme la fenetre du bridge auto-lance avant (port 8765 occupe).
echo.

:: Tuer les bridges en cours d'execution
powershell -NoProfile -Command "Get-WmiObject Win32_Process -Filter \"name = 'pythonw.exe' OR name = 'python.exe'\" | Where-Object { $_.CommandLine -like '*serial_to_mqtt*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 2 /nobreak >nul

cd /d C:\Users\SE\Desktop\SE
"C:\Users\SE\AppData\Local\Programs\Python\Python312\python.exe" mini-pc/serial_to_mqtt.py --scenario
pause
