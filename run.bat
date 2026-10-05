@echo off
chcp 65001 > nul
title EDITH — Enhanced Tactical AI & Reasoning

echo ========================================================
echo   👓 E.D.I.T.H. (Consola Interactiva)
echo ========================================================
echo.

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [ADVERTENCIA] No se detecto .venv. Intentando con Python global...
)

echo Iniciando E.D.I.T.H...
python main.py %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Ocurrio un error al ejecutar EDITH.
    pause
)
