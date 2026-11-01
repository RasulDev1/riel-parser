@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM Пробный прогон: один проход, без отправки в Telegram, подробный лог в parser.log
python main.py --once --dry-run -v
pause
