@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM Сборка RielParser.exe (окно с интерфейсом) и AvitoParser.exe (консольная версия). Нужен Python 3.10+.
python -m pip install -r requirements.txt pyinstaller || goto :error
python -m PyInstaller --noconfirm --onefile --windowed --name RielParser --add-data "ui;ui" --collect-all curl_cffi --collect-all webview app.py || goto :error
python -m PyInstaller --noconfirm --onefile --console --name AvitoParser --collect-all curl_cffi main.py || goto :error
echo.
echo Готово: dist\RielParser.exe (приложение) и dist\AvitoParser.exe (консоль).
echo Настройки, база и лог создаются рядом с .exe.
pause
exit /b 0
:error
echo Сборка не удалась.
pause
exit /b 1
