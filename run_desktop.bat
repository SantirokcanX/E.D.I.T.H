@echo off
chcp 65001 > nul
title EDITH Desktop Application

echo ========================================================
echo   E.D.I.T.H. - modo depuracion (con consola)
echo ========================================================
echo.

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [ADVERTENCIA] No se detecto .venv. Intentando con Python global...
)

tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe" >NUL
if "%ERRORLEVEL%"=="1" (
    echo [INFO] Iniciando motor local de Ollama en segundo plano...
    start "" /B ollama serve >NUL 2>&1
)

echo Iniciando EDITH con consola visible para ver los mensajes. Uso normal: EDITH.exe
python desktop/desktop_app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Ocurrio un error al ejecutar la aplicacion de escritorio de EDITH.
    pause
)
