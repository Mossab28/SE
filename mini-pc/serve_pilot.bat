@echo off
title Nereides - Pilot HTTP Server
echo Serveur HTTP local pour l'interface pilote sur http://localhost:8080
cd /d C:\Users\SE\Desktop\SE\pilot-ui
"C:\Users\SE\AppData\Local\Programs\Python\Python312\python.exe" -m http.server 8080
pause
