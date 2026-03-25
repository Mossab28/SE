@echo off
title Nereides - Bridge GPS
echo Demarrage du bridge GPS...
cd /d C:\Users\SE\Desktop\SE
"C:\Users\SE\AppData\Local\Programs\Python\Python312\python.exe" mini-pc/serial_to_mqtt.py
pause
