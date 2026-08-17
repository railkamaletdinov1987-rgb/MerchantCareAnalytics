@echo off
chcp 65001 >nul
title Merchant Care - Public

cd /d "%~dp0"

echo ========================================
echo   Merchant Care - запуск для гостей
echo ========================================
echo.

if not exist "config\credentials.json" (
    echo [ОШИБКА] Нет config\credentials.json
    pause
    exit /b 1
)

if not exist ".env" (
    echo [ОШИБКА] Нет .env
    pause
    exit /b 1
)

if not exist "cloudflared.exe" (
    echo [ОШИБКА] Нет cloudflared.exe в папке проекта
    echo Скачайте: https://github.com/cloudflare/cloudflared/releases/latest
    echo Файл: cloudflared-windows-amd64.exe
    echo Переименуйте в cloudflared.exe и положите сюда:
    echo %~dp0
    pause
    exit /b 1
)

set PYTHON=C:\Users\Fargo_Rail\AppData\Local\Programs\Python\Python312\python.exe

echo [1/3] Telegram-слушатель...
start "Merchant Care - Listener" cmd /k "cd /d "%~dp0" && %PYTHON% run_listener.py"

timeout /t 3 /nobreak >nul

echo [2/3] Dashboard...
start "Merchant Care - Dashboard" cmd /k "cd /d "%~dp0" && %PYTHON% -m dashboard.app"

timeout /t 4 /nobreak >nul

echo [3/3] Cloudflare Tunnel...
echo.
echo Ждите ссылку. Она также сохранится в файл:
echo   %~dp0public_link.txt
echo.
echo ----------------------------------------

del public_link.txt 2>nul
del tunnel_log.txt 2>nul

powershell -NoProfile -Command ^
  "$ErrorActionPreference='Continue';" ^
  "& '.\cloudflared.exe' tunnel --url http://localhost:8000 2>&1 | ForEach-Object {" ^
  "  $line = $_;" ^
  "  Write-Host $line;" ^
  "  if ($line -match 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com') {" ^
  "    $url = $Matches[0];" ^
  "    Set-Content -Path 'public_link.txt' -Value $url -Encoding UTF8;" ^
  "    Write-Host '';" ^
  "    Write-Host '========================================' -ForegroundColor Green;" ^
  "    Write-Host '  ССЫЛКА ДЛЯ ГОСТЕЙ:' -ForegroundColor Green;" ^
  "    Write-Host \"  $url\" -ForegroundColor Green;" ^
  "    Write-Host '  (сохранено в public_link.txt)' -ForegroundColor Green;" ^
  "    Write-Host '========================================' -ForegroundColor Green;" ^
  "    Write-Host '';" ^
  "  }" ^
  "}"

echo.
echo Туннель остановлен.
pause