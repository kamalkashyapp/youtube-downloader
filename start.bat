@echo off
chcp 65001 >nul
title ⚡ YouTube & Shorts Downloader + REST API
cd /d "%~dp0"

echo ========================================================
echo   ⚡ YouTube Video & Shorts Downloader + REST API
echo ========================================================
echo.
echo Starting Server on http://localhost:5055 ...
echo Browser automatically open ho raha hai...
echo.

start "" "http://localhost:5055"
python app.py

if errorlevel 1 (
    echo.
    echo [ERROR] Python command se start nahi hua. Py command try kar rahe hain...
    py app.py
)

pause
