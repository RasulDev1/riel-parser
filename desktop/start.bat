@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM Двойной клик: запуск мониторинга. Библиотеки поставятся сами при первом запуске.
python main.py %*
pause
