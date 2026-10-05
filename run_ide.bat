@echo off
chcp 65001 > nul
title EDITH Studio — Web IDE

echo ========================================================
echo   👓 E.D.I.T.H. STUDIO (IDE Web & Co-Working)
echo ========================================================
echo.

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [ADVERTENCIA] No se detecto .venv. Intentando con Python global...
)

echo Abriendo navegador en http://localhost:8000...
start http://localhost:8000

echo Iniciando servidor de EDITH Studio...
python main.py --ide --port 8000

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Ocurrio un error al ejecutar EDITH Studio.
    pause
)
