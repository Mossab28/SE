@echo off
title Nereides - Test Course (modele physique)
echo Lancement d'une course simulee de 4 min (modele physique coherent).
echo   - Profil vitesse : accel / croisiere / virages / sprint / arrivee
echo   - SOC, puissance, tension, temperatures coherents pour tester l'autonomie
echo.

powershell -NoProfile -Command "Get-WmiObject Win32_Process -Filter \"name = 'pythonw.exe' OR name = 'python.exe'\" | Where-Object { $_.CommandLine -like '*serial_to_mqtt*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 2 /nobreak >nul

cd /d C:\Users\SE\Desktop\SE
"C:\Users\SE\AppData\Local\Programs\Python\Python312\python.exe" mini-pc/serial_to_mqtt.py --race
pause
