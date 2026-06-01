@echo off
chcp 65001 >nul
setlocal

set PROJECT_DIR=%~dp0..
set PYTHON=%PROJECT_DIR%\venv\Scripts\python.exe
set SRC=%PROJECT_DIR%\run.py
set BUILD_CFG=
if exist "%PROJECT_DIR%\config\build.json" set BUILD_CFG=%PROJECT_DIR%\config\build.json
if "%BUILD_CFG%"=="" if exist "%PROJECT_DIR%\config\build.template.json" set BUILD_CFG=%PROJECT_DIR%\config\build.template.json
set GEN_SCRIPT=%PROJECT_DIR%\scripts\_gen_version.py
set RUN_PYI_SCRIPT=%PROJECT_DIR%\scripts\_run_pyinstaller.py
set BUILD_DIR=%PROJECT_DIR%\build
set RUNTIME_INFO=%PROJECT_DIR%\src\_build_info.py

if not exist "%PYTHON%" (
    echo venv не найден. Запустите сначала scripts\setup.bat
    pause
    exit /b 1
)

if not exist "%BUILD_CFG%" (
    echo Не найден build-конфиг: config/build.json или config/build.template.json
    pause
    exit /b 1
)

if not exist "%GEN_SCRIPT%" (
    echo scripts/_gen_version.py не найден
    pause
    exit /b 1
)

if not exist "%RUN_PYI_SCRIPT%" (
    echo scripts/_run_pyinstaller.py не найден
    pause
    exit /b 1
)

echo === Сборка Jenkins Agent ===
echo.
echo Конфиг сборки: %BUILD_CFG%
echo.

:: ── Генерируем version script из build.json ──
mkdir "%BUILD_DIR%" 2>nul
if exist "%RUNTIME_INFO%" del /q "%RUNTIME_INFO%" >nul 2>&1

:: Запускаем Python-генератор - он создаёт build\_build_vars.bat
"%PYTHON%" "%GEN_SCRIPT%" "%BUILD_CFG%" "%BUILD_DIR%"
if %errorlevel% neq 0 (
    echo ОШИБКА: Не удалось сгенерировать version script
    pause
    exit /b 1
)

:: Подключаем сгенерированные переменные
call "%BUILD_DIR%\_build_vars.bat"

:: Значения по умолчанию если что-то не попало
if not defined OUTPUT_EXE set OUTPUT_EXE=jenkins-agent.exe
if not defined EXE_NAME set EXE_NAME=jenkins-agent
if not defined VER_SCRIPT set VER_SCRIPT=%BUILD_DIR%\_version.py

echo   Output exe:     %OUTPUT_EXE%
echo   PyInstaller:    %EXE_NAME%

:: Версия
if exist "%VER_SCRIPT%" echo   Версия:         из build/_version.py

:: Иконка
if defined ICON echo   Иконка:         %ICON%
if not defined ICON echo   Иконка:         не найдена

:: Режим окна
if /i "%NOCONSOLE%"=="true" echo   Режим:          GUI
if /i not "%NOCONSOLE%"=="true" echo   Режим:          Console

echo.

:: Устанавливаем PyInstaller если не стоит
"%PYTHON%" -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Установка PyInstaller...
    "%PYTHON%" -m pip install pyinstaller >nul 2>&1
)

:: ── Компиляция ──
echo Компиляция...
"%PYTHON%" "%RUN_PYI_SCRIPT%" "%BUILD_DIR%\_build_vars.json" "%PROJECT_DIR%" "%BUILD_DIR%" "%SRC%"

if %errorlevel% neq 0 (
    echo.
    echo ОШИБКА: Компиляция не удалась
    if exist "%RUNTIME_INFO%" del /q "%RUNTIME_INFO%" >nul 2>&1
    pause
    exit /b 1
)

:: ── Проверяем результат ──
if exist "%PROJECT_DIR%\%OUTPUT_EXE%" (
    echo.
    echo ================================
    echo  Сборка завершена
    echo ================================
    echo  Файл: %OUTPUT_EXE%
    for %%F in ("%PROJECT_DIR%\%OUTPUT_EXE%") do echo  Размер: %%~zF байт
    echo.
    echo  Следующие шаги:
    echo    1. Настроить config\config.json
    echo    2. scripts\Install-ScheduledTask.ps1
    echo    3. Запуск
    echo.
) else (
    echo.
    echo ОШИБКА: Файл %OUTPUT_EXE% не создан
    dir "%PROJECT_DIR%" 2>nul
    pause
    exit /b 1
)

:: ── Уборка ──
if exist "%PROJECT_DIR%\build" rmdir /s /q "%PROJECT_DIR%\build"
if exist "%RUNTIME_INFO%" del /q "%RUNTIME_INFO%" >nul 2>&1
