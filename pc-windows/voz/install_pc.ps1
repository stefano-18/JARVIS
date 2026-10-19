#Requires -Version 5.1
<#
.SYNOPSIS
  Instalador 1-Clic — PC Fijo (HUD Electron + agente de voz)

.DESCRIPTION
  - npm install (Electron HUD)
  - Entorno Python del agente (openwakeword, PyAudio, websockets)
  - Accesos directos en el escritorio para HUD y agente de control
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptRoot

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "    OK: $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "    AVISO: $Message" -ForegroundColor Yellow
}

function Write-Err([string]$Message) {
    Write-Host "    ERROR: $Message" -ForegroundColor Red
}

function Get-PythonCommand {
    $candidates = @("py -3.12", "py -3.11", "py -3.10", "python3", "python")
    foreach ($cmd in $candidates) {
        try {
            $parts = $cmd -split " ", 2
            if ($parts.Count -eq 2) {
                $ver = & $parts[0] $parts[1] -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
                $exe = & $parts[0] $parts[1] -c "import sys; print(sys.executable)" 2>$null
            } else {
                $ver = & $parts[0] -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
                $exe = & $parts[0] -c "import sys; print(sys.executable)" 2>$null
            }
            if ($LASTEXITCODE -ne 0 -or -not $ver) { continue }
            $majorMinor = $ver.Trim() -split "\."
            $major = [int]$majorMinor[0]
            $minor = [int]$majorMinor[1]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                return @{ Launch = $cmd; Executable = $exe.Trim() }
            }
        } catch {
            continue
        }
    }
    return $null
}

function New-DesktopShortcut {
    param(
        [string]$Name,
        [string]$TargetPath,
        [string]$Arguments = "",
        [string]$WorkingDirectory = $ScriptRoot
    )
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnkPath = Join-Path $desktop "$Name.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($lnkPath)
    $shortcut.TargetPath = $TargetPath
    if ($Arguments) { $shortcut.Arguments = $Arguments }
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.WindowStyle = 1
    $shortcut.Description = "JARVIS — $Name"
    $shortcut.Save()
    Write-Ok "Acceso directo: $lnkPath"
}

Write-Host @"

  ╔══════════════════════════════════════╗
  ║   JARVIS — Instalador PC Fijo (Día 5) ║
  ╚══════════════════════════════════════╝

"@ -ForegroundColor White

Write-Step "Node.js y npm"
try {
    $nodeVer = node --version
    $npmVer = npm --version
    Write-Ok "Node $nodeVer / npm $npmVer"
} catch {
    Write-Err "Node.js no está instalado. Instala LTS desde https://nodejs.org/"
    exit 1
}

Write-Step "Paquetes Electron (npm install)"
npm install
if ($LASTEXITCODE -ne 0) {
    Write-Err "npm install falló"
    exit 1
}
Write-Ok "Dependencias Node instaladas"

Write-Step "Python 3.10+ para agente de voz"
$py = Get-PythonCommand
if (-not $py) {
    Write-Err "Python 3.10+ requerido para el agente de voz."
    exit 1
}
Write-Ok "Python: $($py.Executable)"

Write-Step "Entorno virtual agente (.venv-agent)"
$agentVenv = Join-Path $ScriptRoot ".venv-agent"
$agentPython = Join-Path $agentVenv "Scripts\python.exe"
if (-not (Test-Path $agentPython)) {
    $launchParts = $py.Launch -split " ", 2
    if ($launchParts.Count -eq 2) {
        & $launchParts[0] $launchParts[1] -m venv $agentVenv
    } else {
        & $launchParts[0] -m venv $agentVenv
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Err "No se pudo crear .venv-agent"
        exit 1
    }
}
Write-Ok ".venv-agent listo"

Write-Step "Dependencias Python del agente"
& $agentPython -m pip install --upgrade pip
& $agentPython -m pip install openwakeword PyAudio websockets numpy
if ($LASTEXITCODE -ne 0) {
    Write-Warn "pip falló parcialmente. En Windows, PyAudio a veces requiere:"
    Write-Host "  pip install pipwin && pipwin install pyaudio" -ForegroundColor Gray
} else {
    Write-Ok "openwakeword, PyAudio, websockets, numpy"
}

Write-Step "Configuración del agente (.env.agent)"
$envAgent = Join-Path $ScriptRoot ".env.agent"
if (-not (Test-Path $envAgent)) {
    @"
# IP de la laptop donde corre el WebSocket (core.websocket_server)
JARVIS_WS_URL=ws://192.168.1.100:8765
JARVIS_WAKE_THRESHOLD=0.55
JARVIS_RECORD_SECONDS=6
"@ | Set-Content -Path $envAgent -Encoding UTF8
    Write-Warn "Edita .env.agent con la IP real de tu laptop."
} else {
    Write-Ok ".env.agent ya existe"
}

Write-Step "Accesos directos en el escritorio"
$npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npmCmd) { $npmCmd = "npm.cmd" }

New-DesktopShortcut -Name "JARVIS HUD" -TargetPath $npmCmd -Arguments "start" -WorkingDirectory $ScriptRoot

$pcControl = Join-Path $ScriptRoot "agent\pc_control.py"
New-DesktopShortcut -Name "JARVIS Agente Voz" -TargetPath $agentPython -Arguments "`"$pcControl`"" -WorkingDirectory $ScriptRoot

$wakeWord = Join-Path $ScriptRoot "agent\wake_word.py"
if (Test-Path $wakeWord) {
    New-DesktopShortcut -Name "JARVIS Wake Word" -TargetPath $agentPython -Arguments "`"$wakeWord`"" -WorkingDirectory $ScriptRoot
}

Write-Host @"

  ╔════════════════════════════════════════════════════════════╗
  ║  INSTALACIÓN COMPLETADA — PC Fijo                          ║
  ╠════════════════════════════════════════════════════════════╣
  ║  1. Edita .env.agent → JARVIS_WS_URL=ws://IP_LAPTOP:8765   ║
  ║  2. Escritorio: "JARVIS HUD" + "JARVIS Agente Voz"         ║
  ║  3. Comandos locales: apaga/reinicia/bloquea el PC         ║
  ║  4. BIOS: Wake-on-LAN activado en el adaptador de red      ║
  ╚════════════════════════════════════════════════════════════╝

"@ -ForegroundColor Green

Write-Host "Prueba rápida de texto (sin mic):" -ForegroundColor Gray
Write-Host "  .\.venv-agent\Scripts\python.exe .\agent\pc_control.py --text `"bloquea la pantalla`"" -ForegroundColor Gray
