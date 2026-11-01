@echo off
chcp 65001 >nul
REM Сборка AvitoParser.exe. Нужен Python 3.10+ в PATH.
python -m pip install -r requirements.txt pyinstaller || goto :error
python -m PyInstaller --onefile --console --name AvitoParser --collect-all curl_cffi main.py || goto :error
copy /Y config.example.json dist\config.json >nul
echo.
echo Готово: dist\AvitoParser.exe и dist\config.json
pause
exit /b 0
:error
echo Сборка не удалась.
pause
exit /b 1
