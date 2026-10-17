<#
.SYNOPSIS
    Construye EDITH para distribuirla (Fase 15.3): dist\EDITH\EDITH.exe + _internal\ y edith-whatsapp.exe.

.DESCRIPTION
    1. Entorno limpio build\.venv con requirements.txt + PyInstaller (se reutiliza si ya existe).
    2. PyInstaller con build\edith.spec -> dist\EDITH\EDITH.exe (modo carpeta, sin consola).
    3. Bridge de WhatsApp (opcional): esbuild (un solo .cjs) + Node SEA -> dist\EDITH\edith-whatsapp.exe.
       Quien instale EDITH no necesita Node; solo hace falta aquí, para construirlo.
    4. Autocomprobación: EDITH.exe --self-test y edith-whatsapp.exe --check con una carpeta de datos
       temporal (nunca la real de %LOCALAPPDATA%\EDITH).
    La versión sale del archivo VERSION de la raíz. La 15.4 añadirá el instalador (Inno Setup).

.PARAMETER Python
    Python 3.13 con el que crear build\.venv. Por defecto: py -3.13, o el Python base del .venv del proyecto.

.PARAMETER Clean
    Borra build\.venv, build\work y dist\EDITH antes de empezar (construcción desde cero).

.PARAMETER NoWhatsApp
    No construye edith-whatsapp.exe.

.PARAMETER SkipSelfTest
    No ejecuta las autocomprobaciones del final.

.PARAMETER NoInstaller
    No compila dist\EDITH-Setup-<versión>.exe (paso 5, necesita Inno Setup 6).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File build\build_setup.ps1
#>
param(
    [string]$Python = "",
    [switch]$Clean,
    [switch]$NoWhatsApp,
    [switch]$SkipSelfTest,
    [switch]$NoInstaller
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root "build\.venv"
$Work = Join-Path $Root "build\work"
$Dist = Join-Path $Root "dist"
$AppDir = Join-Path $Dist "EDITH"
$BridgeSrc = Join-Path $Root "bridges\whatsapp"
$Version = (Get-Content (Join-Path $Root "VERSION") -Raw).Trim()
$Started = Get-Date

function Write-Step([string]$Text) { Write-Host ""; Write-Host "==> $Text" -ForegroundColor Cyan }

# Ejecuta un programa externo y se detiene si falla. Con EAP=Continue: en PowerShell 5.1 los avisos
# que un programa escribe en stderr (pip, npm, postject) no deben cortar la construcción.
function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Exe @Arguments } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0) { throw "Falló ($LASTEXITCODE): $Exe $($Arguments -join ' ')" }
}

function Find-Python {
    if ($Python) { return $Python }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $exe = & $py.Source -3.13 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
    }
    $cfg = Join-Path $Root ".venv\pyvenv.cfg"
    if (Test-Path $cfg) {
        $line = Get-Content $cfg | Where-Object { $_ -match "^executable\s*=" } | Select-Object -First 1
        if ($line) { return ($line -split "=", 2)[1].Trim() }
    }
    return "python"
}

function Get-FolderSizeMB([string]$Path) {
    [math]::Round(((Get-ChildItem $Path -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
}

Write-Host "EDITH $Version · construcción en $Root" -ForegroundColor Green

if ($Clean) {
    Write-Step "Limpiando construcciones anteriores"
    foreach ($p in @($Venv, $Work, $AppDir)) { if (Test-Path $p) { Remove-Item -Recurse -Force $p } }
}

# Las herramientas de construcción importan partes de EDITH: que nunca toquen la carpeta de datos real
$BuildHome = Join-Path $env:TEMP ("edith_build_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$SavedEnv = @{}
function Set-TempEnv([hashtable]$Values) {
    foreach ($k in $Values.Keys) {
        $SavedEnv[$k] = [Environment]::GetEnvironmentVariable($k, "Process")
        [Environment]::SetEnvironmentVariable($k, $Values[$k], "Process")
    }
}
function Restore-Env { foreach ($k in $SavedEnv.Keys) { [Environment]::SetEnvironmentVariable($k, $SavedEnv[$k], "Process") } }

try {
    Set-TempEnv @{
        EDITH_HOME = (Join-Path $BuildHome "home"); OBSIDIAN_VAULT_PATH = (Join-Path $BuildHome "vault")
        HEARTBEAT_ENABLED = "false"; WHATSAPP_ENABLED = "false"; MORNING_BRIEFING_TIME = " "; OLLAMA_WARMUP = "false"
        EDITH_HOTKEY = "off"; PYTHONUTF8 = "1"
    }

    # ------------------------------------------------------------------ 1. entorno limpio
    Write-Step "1/5 Entorno de Python limpio (build\.venv)"
    $VenvPython = Join-Path $Venv "Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        $base = Find-Python
        Write-Host "Creando el entorno con $base"
        Invoke-Native $base @("-m", "venv", $Venv)
        Invoke-Native $VenvPython @("-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip")
    }
    Invoke-Native $VenvPython @("-m", "pip", "install", "--disable-pip-version-check", "-q",
        "-r", (Join-Path $Root "requirements.txt"), "-r", (Join-Path $Root "build\requirements-build.txt"))
    $pyVersion = & $VenvPython -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    Write-Host "Python $pyVersion listo"

    # ------------------------------------------------------------------ 2. PyInstaller
    Write-Step "2/5 EDITH.exe con PyInstaller (modo carpeta)"
    Invoke-Native $VenvPython @("-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
        "--distpath", $Dist, "--workpath", (Join-Path $Work "pyinstaller"), (Join-Path $Root "build\edith.spec"))
    $exe = Join-Path $AppDir "EDITH.exe"
    if (-not (Test-Path $exe)) { throw "PyInstaller no generó $exe" }
    Write-Host "EDITH.exe $((Get-Item $exe).VersionInfo.ProductVersion) · $(Get-FolderSizeMB $AppDir) MB"

    # ------------------------------------------------------------------ 3. bridge de WhatsApp
    $bridgeExe = Join-Path $AppDir "edith-whatsapp.exe"
    if ($NoWhatsApp) {
        Write-Step "3/5 Bridge de WhatsApp: omitido (-NoWhatsApp)"
    } else {
        Write-Step "3/5 edith-whatsapp.exe (esbuild + Node SEA)"
        $node = (Get-Command node -ErrorAction SilentlyContinue).Source
        $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
        if (-not $node -or -not $npm) { throw "Para construir el bridge hace falta Node 20+ (o usa -NoWhatsApp)." }
        $nodeMajor = [int]((& $node -p "process.versions.node").Split(".")[0])
        if ($nodeMajor -lt 20) { throw "Node $nodeMajor es muy antiguo para Node SEA: instala Node 20 o superior." }
        if (-not (Test-Path (Join-Path $BridgeSrc "node_modules\esbuild")) -or
            -not (Test-Path (Join-Path $BridgeSrc "node_modules\postject"))) {
            Push-Location $BridgeSrc
            try { Invoke-Native $npm @("ci", "--no-audit", "--no-fund") } finally { Pop-Location }
        }
        $waWork = Join-Path $Work "whatsapp"
        New-Item -ItemType Directory -Force $waWork | Out-Null
        # Un solo archivo CommonJS (Node SEA no carga módulos ESM ni node_modules). Las librerías de
        # imagen opcionales de Baileys quedan fuera: sin ellas solo se pierden miniaturas.
        Invoke-Native (Join-Path $BridgeSrc "node_modules\.bin\esbuild.cmd") @(
            (Join-Path $BridgeSrc "bridge.mjs"), "--bundle", "--platform=node", "--format=cjs", "--target=node20",
            "--supported:dynamic-import=false", "--log-level=error", "--outfile=$(Join-Path $waWork 'bridge.cjs')",
            "--external:sharp", "--external:jimp", "--external:link-preview-js", "--external:audio-decode")
        $seaConfig = @{ main = "bridge.cjs"; output = "sea-prep.blob"; disableExperimentalSEAWarning = $true
                        useCodeCache = $false; useSnapshot = $false } | ConvertTo-Json
        [IO.File]::WriteAllText((Join-Path $waWork "sea-config.json"), $seaConfig)
        Push-Location $waWork
        try {
            Invoke-Native $node @("--experimental-sea-config", "sea-config.json")
            Copy-Item $node (Join-Path $waWork "edith-whatsapp.exe") -Force
            Invoke-Native (Join-Path $BridgeSrc "node_modules\.bin\postject.cmd") @("edith-whatsapp.exe", "NODE_SEA_BLOB",
                "sea-prep.blob", "--sentinel-fuse", "NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2")
        } finally { Pop-Location }
        Copy-Item (Join-Path $waWork "edith-whatsapp.exe") $bridgeExe -Force
        Write-Host "edith-whatsapp.exe (Node $(& $node -p 'process.versions.node')) · $([math]::Round((Get-Item $bridgeExe).Length / 1MB, 1)) MB"
    }

    # ------------------------------------------------------------------ 4. autocomprobación
    if ($SkipSelfTest) {
        Write-Step "4/5 Autocomprobación: omitida (-SkipSelfTest)"
    } else {
        Write-Step "4/5 Autocomprobación con datos temporales"
        $report = Join-Path $BuildHome "self-test.txt"
        $proc = Start-Process -FilePath $exe -ArgumentList "--self-test=`"$report`"" -Wait -PassThru -WindowStyle Hidden
        if (Test-Path $report) { Get-Content $report -Encoding UTF8 | ForEach-Object { Write-Host "    $_" } }
        if ($proc.ExitCode -ne 0) { throw "La autocomprobación de EDITH.exe falló (código $($proc.ExitCode))." }
        if (Test-Path $bridgeExe) {
            Invoke-Native $bridgeExe @("--check")
        }
    }

    # ------------------------------------------------------------------ 5. instalador (Fase 15.4)
    $setupExe = Join-Path $Dist "EDITH-Setup-$Version.exe"
    if ($NoInstaller) {
        Write-Step "5/5 Instalador: omitido (-NoInstaller)"
    } else {
        $iscc = @((Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
                  (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
                  (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")) | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $iscc) {
            Write-Step "5/5 Instalador: falta Inno Setup 6 (winget install JRSoftware.InnoSetup) — omitido"
        } else {
            Write-Step "5/5 EDITH-Setup.exe con Inno Setup"
            Invoke-Native $iscc @("/Q", "/DAppVersion=$Version", (Join-Path $Root "build\installer\edith.iss"))
            if (-not (Test-Path $setupExe)) { throw "Inno Setup no generó $setupExe" }
            Write-Host "EDITH-Setup-$Version.exe · $([math]::Round((Get-Item $setupExe).Length / 1MB, 1)) MB"
        }
    }

    $elapsed = [math]::Round(((Get-Date) - $Started).TotalMinutes, 1)
    Write-Host ""
    Write-Host "Listo en $elapsed min: $AppDir ($(Get-FolderSizeMB $AppDir) MB)" -ForegroundColor Green
    Write-Host "Prueba rápida: $exe   (o con --tray para arrancar en la bandeja)"
}
finally {
    Restore-Env
    if (Test-Path $BuildHome) { Remove-Item -Recurse -Force $BuildHome -ErrorAction SilentlyContinue }
}
