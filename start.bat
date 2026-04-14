@echo off
cd /d "%~dp0"
title Transcribe

:: ── Найти uv ─────────────────────────────────────────────────────────────────
set "UV="
for /f "delims=" %%i in ('where uv 2^>nul') do (set "UV=%%i" & goto :uv_found)
if exist "%USERPROFILE%\.local\bin\uv.exe"    set "UV=%USERPROFILE%\.local\bin\uv.exe" & goto :uv_found
if exist "%APPDATA%\uv\bin\uv.exe"            set "UV=%APPDATA%\uv\bin\uv.exe"         & goto :uv_found

:: ── Установить uv (не требует Python) ────────────────────────────────────────
echo [→] Устанавливаю uv...
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

:: Перепроверить после установки
for /f "delims=" %%i in ('where uv 2^>nul') do (set "UV=%%i" & goto :uv_found)
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe" & goto :uv_found
if exist "%APPDATA%\uv\bin\uv.exe"         set "UV=%APPDATA%\uv\bin\uv.exe"         & goto :uv_found

echo [!] Не удалось найти uv после установки.
echo     Закрой это окно и запусти start.bat снова.
pause & exit /b 1

:uv_found
echo [✓] uv: %UV%

:: ── Запустить launch.py
::    uv сам скачает Python 3.11 если его нет на компьютере
:: ──────────────────────────────────────────────────────────────────────────────
set "UV_PATH=%UV%"
"%UV%" run --python 3.11 "%~dp0launch.py"
if %errorlevel% neq 0 pause
