@echo off
chcp 65001 >nul
:: Запуск Jenkins Agent из виртуального окружения (без консоли)

set PROJECT_DIR=%~dp0..

if not exist "%PROJECT_DIR%\venv\Scripts\pythonw.exe" (
    echo venv не найден. Запустите сначала setup.bat
    pause
    exit /b 1
)

:: pythonw.exe = без консольного окна
start "" "%PROJECT_DIR%\venv\Scripts\pythonw.exe" -m src.main %*
