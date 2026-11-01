@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM Запуск приложения с интерфейсом. При первом запуске библиотеки установятся сами.
python app.py
if errorlevel 1 pause
