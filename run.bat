@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -ExecutionPolicy Bypass -File "%~dp0run.ps1"

