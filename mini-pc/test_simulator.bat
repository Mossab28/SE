@echo off
title Nereides - Test Simulator (mode FAKE)
echo Lancement du bridge en mode simule (sans port serie).
echo Les donnees factices seront publiees sur:
echo   - MQTT VPS (dashboard online)
echo   - WebSocket local (interface pilote)
echo.
cd /d C:\Users\SE\Desktop\SE
"C:\Users\SE\AppData\Local\Programs\Python\Python312\python.exe" mini-pc/serial_to_mqtt.py --fake
pause
