@echo off
chcp 65001 >nul
title Merchant Care Analytics

cd /d "%~dp0"

echo ========================================
echo   Merchant Care Analytics
echo ========================================
echo.

if not exist "config\credentials.json" (
    echo [ОШИБКА] Не найден config\credentials.json
    pause
    exit /b 1
)

if not exist ".env" (
    echo [ОШИБКА] Не найден файл .env
    pause
    exit /b 1
)

echo [1/2] Запуск Telegram-слушателя...
start "Merchant Care - Listener" cmd /k "cd /d "%~dp0" && C:\Users\Fargo_Rail\AppData\Local\Programs\Python\Python312\python.exe run_listener.py"

timeout /t 3 /nobreak >nul

echo [2/2] Запуск Dashboard...
start "Merchant Care - Dashboard" cmd /k "cd /d "%~dp0" && C:\Users\Fargo_Rail\AppData\Local\Programs\Python\Python312\python.exe -m dashboard.app"

echo.
echo ----------------------------------------
echo  Слушатель и дашборд запущены.
echo.
echo  Дашборд:  http://127.0.0.1:8000
echo.
echo  Чтобы остановить — закройте оба окна cmd.
echo ----------------------------------------
echo.
pause