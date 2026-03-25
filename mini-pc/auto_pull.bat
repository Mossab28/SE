@echo off
title Nereides - Auto Pull
cd /d C:\Users\SE\Desktop\SE

:loop
git pull origin main
timeout /t 10 /nobreak >nul
goto loop
