@echo off
chcp 65001 > nul
title Instalador de EDITH para Windows

echo ========================================================
echo   E.D.I.T.H. - Accesos directos de la app de escritorio
echo ========================================================
echo.

REM 1) EDITH.exe: lanzador nativo sin consola (se compila con el C# que trae Windows)
if not exist "%~dp0EDITH.exe" (
    echo Creando EDITH.exe...
    call "%~dp0desktop\launcher\build_launcher.bat"
    if errorlevel 1 (
        echo No se pudo crear EDITH.exe.
        pause
        exit /b 1
    )
)

REM 2) Accesos directos en el Escritorio y en el menu Inicio
echo Creando accesos directos...
powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$root = '%~dp0'.TrimEnd('\'); " ^
    "$targets = @([Environment]::GetFolderPath('Desktop'), ([Environment]::GetFolderPath('StartMenu') + '\Programs')); " ^
    "foreach ($dir in $targets) { " ^
    "  $s = $ws.CreateShortcut($dir + '\EDITH.lnk'); " ^
    "  $s.TargetPath = Join-Path $root 'EDITH.exe'; " ^
    "  $s.WorkingDirectory = $root; " ^
    "  $s.IconLocation = (Join-Path $root 'desktop\assets\edith-app.ico') + ',0'; " ^
    "  $s.Description = 'EDITH - asistente de IA local'; " ^
    "  $s.Save() " ^
    "}; " ^
    "Write-Host 'Accesos directos listos en el Escritorio y el menu Inicio.' -ForegroundColor Green"

echo.
echo ========================================================
echo   LISTO
echo ========================================================
echo Abre EDITH desde el Escritorio o el menu Inicio.
echo - Cerrar la ventana la deja activa junto al reloj (icono de EDITH).
echo - Para cerrarla del todo: clic derecho en el icono ^> Salir.
echo - Atajo para mostrarla/ocultarla: Win + Shift + E
echo - Tus datos viven en %%LOCALAPPDATA%%\EDITH
echo.
pause
