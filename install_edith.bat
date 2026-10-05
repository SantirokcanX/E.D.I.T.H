@echo off
chcp 65001 > nul
title Instalador de EDITH para Windows

echo ========================================================
echo   👓 INSTALADOR DE E.D.I.T.H. (Acceso Directo y Sistema)
echo ========================================================
echo.
echo Configurando accesos directos en tu laptop...

powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$deskPath = [Environment]::GetFolderPath('Desktop'); " ^
    "$startPath = [Environment]::GetFolderPath('StartMenu') + '\Programs'; " ^
    "$target = Join-Path (Get-Location) 'run_desktop.bat'; " ^
    "$workDir = (Get-Location).Path; " ^
    "$s1 = $ws.CreateShortcut($deskPath + '\EDITH.lnk'); " ^
    "$s1.TargetPath = $target; " ^
    "$s1.WorkingDirectory = $workDir; " ^
    "$s1.Description = 'EDITH - AI Companion, Laptop Control & Visual Intelligence'; " ^
    "$s1.Save(); " ^
    "$s2 = $ws.CreateShortcut($startPath + '\EDITH.lnk'); " ^
    "$s2.TargetPath = $target; " ^
    "$s2.WorkingDirectory = $workDir; " ^
    "$s2.Description = 'EDITH - AI Companion, Laptop Control & Visual Intelligence'; " ^
    "$s2.Save(); " ^
    "Write-Host 'Accesos directos creados exitosamente en el Escritorio y Menu Inicio.' -ForegroundColor Green"

echo.
echo ========================================================
echo   INSTALACION COMPLETADA
echo ========================================================
echo Ya puedes abrir EDITH directamente desde tu Escritorio o
echo buscandola en el Menu Inicio de Windows como 'EDITH'.
echo.
pause
