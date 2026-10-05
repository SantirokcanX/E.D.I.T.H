@echo off
chcp 65001 > nul
title EDITH Desktop Application

echo ========================================================
echo   👓 E.D.I.T.H. (Aplicacion Nativa de Escritorio)
echo ========================================================
echo.

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [ADVERTENCIA] No se detecto .venv. Intentando con Python global...
)

echo Iniciando ventana de escritorio nativa...
python desktop/desktop_app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Ocurrio un error al ejecutar la aplicacion de escritorio de EDITH.
    pause
)
