@echo off
chcp 65001 >nul
title ⚡ YouTube & Shorts Downloader - LIVE Server
cd /d "%~dp0"

echo ========================================================
echo   ⚡ YouTube Video & Shorts Downloader - LIVE Server
echo ========================================================
echo.
echo 1. Local server start ho raha hai...
start "Downloader Local Server" /b py app.py

timeout /t 2 >nul

echo 2. Cloudflare Live Public Tunnel connect ho raha hai...
echo.
echo ========================================================
echo  Neeche diye gaye link ko aap kisi ko bhi bhej sakte hain!
echo  Mobile ya doosre computer par direct open hoga!
echo ========================================================
echo.

if exist "..\cloudflared.exe" (
    ..\cloudflared.exe tunnel --url http://localhost:5055
) else (
    cloudflared.exe tunnel --url http://localhost:5055
)
pause
