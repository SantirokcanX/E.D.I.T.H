@echo off
REM Compila EDITH.exe (lanzador sin consola) en la carpeta raíz del proyecto.
REM Usa el compilador C# incluido en Windows (.NET Framework 4): no hay que instalar nada.
REM La version (AssemblyVersion) sale del archivo VERSION de la raiz del proyecto.
setlocal
set "ROOT=%~dp0..\.."
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    echo No se encontro el compilador C# de .NET Framework 4.
    exit /b 1
)
set "VER="
if exist "%ROOT%\VERSION" set /p VER=<"%ROOT%\VERSION"
if not defined VER set "VER=0.0.0"
set "VERSION_CS=%TEMP%\EDITH_launcher_version.cs"
> "%VERSION_CS%" echo [assembly: System.Reflection.AssemblyVersion("%VER%.0")]
>> "%VERSION_CS%" echo [assembly: System.Reflection.AssemblyFileVersion("%VER%.0")]
>> "%VERSION_CS%" echo [assembly: System.Reflection.AssemblyInformationalVersion("%VER%")]
"%CSC%" /nologo /target:winexe /optimize+ /win32icon:"%ROOT%\desktop\assets\edith-app.ico" /reference:System.Windows.Forms.dll /out:"%ROOT%\EDITH.exe" "%~dp0EDITH.cs" "%VERSION_CS%"
set "RC=%ERRORLEVEL%"
del "%VERSION_CS%" > nul 2>&1
if not "%RC%"=="0" exit /b 1
echo EDITH.exe %VER% creado en %ROOT%
