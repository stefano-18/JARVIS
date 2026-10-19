# install_agent.ps1 — Instalacion SIN admin del agent_pc (solo Windows, solo maquina propia).
# Uso:
#   powershell -ExecutionPolicy Bypass -File install_agent.ps1 -SharedSecret "pega-aqui-el-secreto-del-hub" [-HubHost "IP-del-hub"] [-DeviceId "pc-amigo-01"] [-Roots "%USERPROFILE%\JARVIS"]
#
# Hace (sin elevar, sin schtasks, sin consola en arranque):
#   1. Crea .venv en esta carpeta (si no existe).
#   2. Instala dependencias (websockets + pytest) en el venv.
#   3. Escribe .env en UTF-8 SIN BOM (preserva lo existente; solo actualiza SECRET/HUB_HOST/DEVICE_ID/ROOTS).
#      El secreto DEBE coincidir con el del hub. Aqui NO se genera ninguno.
#   4. Registra arranque automatico con un lanzador VBS idempotente en Startup
#      (pythonw + agent.py oculto; doble guarda: chequeo WMI + agent.lock con PID de agent.py).
#
# Requisitos: Python 3.10+ en PATH (python o py). No toca el agente que ya corra en otra carpeta.
param(
  [Parameter(Mandatory = $true)][string]$SharedSecret,
  [string]$HubHost = "",
  [string]$DeviceId = "",
  [string]$Roots = "%USERPROFILE%\JARVIS"
)

$ErrorActionPreference = "Stop"
$InstallDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Output ("InstallDir: {0}" -f $InstallDir)

# 0. Python disponible (sin admin, solo PATH de usuario).
$py = $null
foreach ($c in @("python", "py -3", "py")) {
  try {
    $parts = $c -split " "
    $exe = $parts[0]; $args = @()
    if ($parts.Count -gt 1) { $args = $parts[1..($parts.Count - 1)] }
    $v = & $exe @args --version 2>&1
    if ($LASTEXITCODE -eq 0) { $py = $c; Write-Output ("Python: {0} -> {1}" -f $c, $v); break }
  } catch { }
}
if (-not $py) { throw "No se encontro Python 3.10+ en PATH (python o py). Instalalo para tu usuario y reintenta." }

function Invoke-Py([string[]]$PyArgs) {
  $parts = $py -split " "
  $exe = $parts[0]; $pre = @()
  if ($parts.Count -gt 1) { $pre = $parts[1..($parts.Count - 1)] }
  & $exe @pre @PyArgs
  if ($LASTEXITCODE -ne 0) { throw ("Fallo: {0} {1} {2}" -f $exe, ($pre -join " "), ($PyArgs -join " ")) }
}

# 1. venv en la carpeta de instalacion.
$venvPy = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) {
  Write-Output "Creando .venv..."
  Invoke-Py @("-m", "venv", (Join-Path $InstallDir ".venv"))
} else {
  Write-Output ".venv ya existe, se reutiliza."
}
& $venvPy --version

# 2. Dependencias (solo usuario, sin admin).
#   websockets = canal al hub (obligatorio). pytest = para ejecutar tests.
#   psutil/mss/Pillow/pywin32 = funciones opcionales (system.info, captura,
#   ventanas); sin ellas el agente arranca igual pero esas acciones devuelven error honesto.
Write-Output "Instalando dependencias..."
& $venvPy -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade fallo" }
& $venvPy -m pip install websockets pytest psutil mss Pillow pywin32
if ($LASTEXITCODE -ne 0) { throw "pip install fallo (websockets pytest psutil mss Pillow pywin32)" }

# 3. .env en UTF-8 SIN BOM. No se imprime el secreto.
$envPath = Join-Path $InstallDir ".env"
$examplePath = Join-Path $InstallDir ".env.example"
$lines = @()
if (Test-Path -LiteralPath $envPath) {
  $lines = Get-Content -LiteralPath $envPath -Encoding UTF8
  Copy-Item -LiteralPath $envPath -Destination ($envPath + ".bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")) -Force
  Write-Output ".env existente: copia de seguridad creada, se actualizan solo las claves indicadas."
} elseif (Test-Path -LiteralPath $examplePath) {
  $lines = Get-Content -LiteralPath $examplePath -Encoding UTF8
} else {
  $lines = @("HUB_HOST=", "HUB_PORT=18765", "DEVICE_ID=", "SECRET=", "ROOTS=%USERPROFILE%\JARVIS", "APPS=notepad=notepad.exe;calc=calc.exe", "COMMANDS=hostname,whoami")
}
$updates = @{ "SECRET" = $SharedSecret }
if ($HubHost -ne "") { $updates["HUB_HOST"] = $HubHost }
if ($DeviceId -ne "") { $updates["DEVICE_ID"] = $DeviceId }
if ($Roots -ne "") { $updates["ROOTS"] = $Roots }
$seen = @{}
$newLines = @()
foreach ($ln in $lines) {
  $t = $ln.Trim()
  if ($t -eq "" -or $t.StartsWith("#") -or ($t -notmatch "=")) { $newLines += $ln; continue }
  $k = ($t -split "=", 2)[0].Trim()
  if ($updates.ContainsKey($k)) { $newLines += ($k + "=" + $updates[$k]); $seen[$k] = $true } else { $newLines += $ln; $seen[$k] = $true }
}
foreach ($k in $updates.Keys) {
  if (-not $seen.ContainsKey($k)) { $newLines += ($k + "=" + $updates[$k]) }
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($envPath, $newLines, $utf8NoBom)
Write-Output ".env escrito en UTF-8 sin BOM (secreto actualizado, no se muestra)."

# 3b. Carpeta ROOTS (expandiendo variables) para que files.* tenga donde operar.
try {
  $rootsExpanded = [System.Environment]::ExpandEnvironmentVariables($Roots)
  if ($rootsExpanded -and $rootsExpanded -notmatch "=") {
    foreach ($r in $rootsExpanded -split ";") {
      $r = $r.Trim()
      if ($r -ne "" -and -not (Test-Path -LiteralPath $r)) {
        New-Item -ItemType Directory -Path $r -Force | Out-Null
        Write-Output ("Carpeta ROOTS creada: {0}" -f $r)
      }
    }
  }
} catch { Write-Output ("Aviso: no se pudo crear ROOTS ({0})" -f $_.Exception.Message) }

# 4. Lanzador VBS idempotente en Startup (usuario actual, sin admin ni schtasks).
$pythonw = Join-Path $InstallDir ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = Join-Path $InstallDir ".venv\Scripts\python.exe" }
$agentPy = Join-Path $InstallDir "agent.py"
$startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$vbsPath = Join-Path $startup "JarvisRemoteAgent.vbs"
$vbs = "' JarvisRemoteAgent — lanzador al inicio (generado por install_agent.ps1, no editar a mano)." + [Environment]::NewLine +
  "' Idempotente: solo lanza si este agent.py no corre ya (chequeo WMI por CommandLine)." + [Environment]::NewLine +
  "' Segunda guarda: agent.py gestiona agent.lock con PID y se niega a duplicarse." + [Environment]::NewLine +
  "' Sin consola: usa pythonw. Sin schtasks ni elevacion." + [Environment]::NewLine +
  "Option Explicit" + [Environment]::NewLine +
  "Dim wmi, procs, p, running" + [Environment]::NewLine +
  "running = False" + [Environment]::NewLine +
  "Set wmi = GetObject(""winmgmts:\\.\root\cimv2"")" + [Environment]::NewLine +
  "Set procs = wmi.ExecQuery(""SELECT CommandLine FROM Win32_Process WHERE Name='python.exe' OR Name='pythonw.exe'"")" + [Environment]::NewLine +
  "For Each p In procs" + [Environment]::NewLine +
  "  If Not IsNull(p.CommandLine) Then" + [Environment]::NewLine +
  "    If InStr(p.CommandLine, ""agent.py"") > 0 Then" + [Environment]::NewLine +
  "      If InStr(p.CommandLine, """ + $InstallDir.Replace("""", """""") + """) > 0 Then running = True" + [Environment]::NewLine +
  "    End If" + [Environment]::NewLine +
  "  End If" + [Environment]::NewLine +
  "Next" + [Environment]::NewLine +
  "If Not running Then" + [Environment]::NewLine +
  "  Dim sh" + [Environment]::NewLine +
  "  Set sh = CreateObject(""WScript.Shell"")" + [Environment]::NewLine +
  "  sh.Run """""" + $pythonw + """"" """"" + $agentPy + """"""", 0, False" + [Environment]::NewLine +
  "End If" + [Environment]::NewLine
[System.IO.File]::WriteAllText($vbsPath, $vbs, (New-Object System.Text.UTF8Encoding($false)))
Write-Output ("Lanzador VBS instalado: {0}" -f $vbsPath)
Write-Output "Listo. Arranca con: pythonw agent.py (o doble clic al VBS). Solo Windows, solo en tu propia maquina."
