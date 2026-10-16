@echo off
REM Compila EDITH.exe (lanzador sin consola) en la carpeta raíz del proyecto.
REM Usa el compilador C# incluido en Windows (.NET Framework 4): no hay que instalar nada.
setlocal
set "ROOT=%~dp0..\.."
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    echo No se encontro el compilador C# de .NET Framework 4.
    exit /b 1
)
"%CSC%" /nologo /target:winexe /optimize+ /win32icon:"%ROOT%\desktop\assets\edith-app.ico" /reference:System.Windows.Forms.dll /out:"%ROOT%\EDITH.exe" "%~dp0EDITH.cs"
if errorlevel 1 exit /b 1
echo EDITH.exe creado en %ROOT%
