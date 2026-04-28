@echo off
chcp 65001 >nul
setlocal

set PROJECT_DIR=%~dp0..
set SCRIPT=%PROJECT_DIR%\scripts\run-tests.ps1

if not exist "%SCRIPT%" (
    echo Не найден %SCRIPT%
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
exit /b %errorlevel%
