@echo off
chcp 65001 >nul
setlocal

set PROJECT_DIR=%~dp0..

echo === Настройка окружения Python ===
echo.

:: Проверка Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ОШИБКА: Python не найден. Установите Python 3.8+
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo Python: %PYVER%
echo.

:: Создание venv
if exist "%PROJECT_DIR%\venv" (
    echo venv уже существует — обновляю зависимости...
) else (
    echo Создаю виртуальное окружение: venv\
    python -m venv "%PROJECT_DIR%\venv"
    if %errorlevel% neq 0 (
        echo ОШИБКА: Не удалось создать venv
        pause
        exit /b 1
    )
    echo venv создан
)
echo.

:: Активация и установка
echo Устанавливаю зависимости...
"%PROJECT_DIR%\venv\Scripts\pip.exe" install -r "%PROJECT_DIR%\requirements.txt"
if %errorlevel% neq 0 (
    echo ОШИБКА: Не удалось установить зависимости
    pause
    exit /b 1
)

echo.
echo ================================
echo  Готово!
echo ================================
echo.
echo Запуск из окружения:   scripts\run-dev.bat
echo Сборка в .exe:         scripts\build.bat
echo.
pause
