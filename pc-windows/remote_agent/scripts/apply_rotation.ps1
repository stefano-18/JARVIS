# apply_rotation.ps1 — Rota el SECRET del remote_agent desde un paquete firmado/manual.
#
# USO NORMAL (produccion, solo cuando el hub lo indique):
#   powershell -ExecutionPolicy Bypass -File apply_rotation.ps1 -PackageDir <carpeta-del-paquete>
# PRUEBA SEGURA (no toca nada):
#   powershell -ExecutionPolicy Bypass -File apply_rotation.ps1 -PackageDir <carpeta> -DryRun
#
# El paquete es rotation_package.json con:
#   {"new_secret": "<secreto-nuevo>", "hub_host": "<opt>", "device_id": "<opt>",
#    "created_ts": <epoch, opt>, "package_id": "<opt>"}
# Flujo real: valida paquete -> backup .env -> escribe SECRET (UTF-8 sin BOM,
# sin mostrarlo) -> reinicia el agente por PID verificado (lock + cmdline) ->
# comprueba "Conectado y autenticado" en logs y ESTABLISHED al 18765 ->
# destruye el paquete (sobrescribe 3x y borra). Con -DryRun no modifica nada.
# Nunca imprime secretos ni el .env. Sin apagados ni reinicios del PC.
param(
  [Parameter(Mandatory = $true)][string]$PackageDir,
  [string]$AgentDir = "C:\jarvis_agent\remote_agent",
  [int]$HubPort = 18765,
  [switch]$DryRun
)
$ErrorActionPreference = "Stop"

function Fail([string]$msg) { Write-Output ("ERROR: " + $msg); exit 1 }

$pkgFile = Join-Path $PackageDir "rotation_package.json"
if ([string]::IsNullOrWhiteSpace($PackageDir) -or -not (Test-Path -LiteralPath $PackageDir -PathType Container)) { Fail "no existe PackageDir" }
if ((Resolve-Path -LiteralPath $PackageDir).Path.TrimEnd("\") -eq (Resolve-Path -LiteralPath $AgentDir).Path.TrimEnd("\")) { Fail "PackageDir no puede ser el AgentDir" }
if (-not (Test-Path -LiteralPath $pkgFile -PathType Leaf)) { Fail "falta rotation_package.json en PackageDir" }

# 1. Leer + validar paquete (sin mostrar secretos).
try { $pkg = Get-Content -LiteralPath $pkgFile -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { Fail ("paquete JSON invalido: " + $_.Exception.Message) }
$newSecret = [string]$pkg.new_secret
if ([string]::IsNullOrWhiteSpace($newSecret)) { Fail "new_secret vacio" }
if ($newSecret.Length -lt 32) { Fail "new_secret demasiado corto (min 32)" }
if ($newSecret -match "\s") { Fail "new_secret con espacios" }
if ($pkg.created_ts) {
  try {
    $age = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [long]$pkg.created_ts
    if ($age -gt 3600) { Write-Output ("AVISO: paquete con antiguedad {0}s (>3600s)" -f $age) }
  } catch { Write-Output "AVISO: created_ts no numerico" }
}
Write-Output "Paquete valido (campos ok, secreto NO mostrado)."

$envFile = Join-Path $AgentDir ".env"
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) { Fail "no existe .env en AgentDir" }

if ($pkg.hub_host -or $pkg.device_id) {
  $envLines = Get-Content -LiteralPath $envFile -Encoding UTF8
  foreach ($k in @("hub_host", "device_id")) {
    if ($pkg.$k) {
      $want = [string]$pkg.$k
      $have = ($envLines | Where-Object { $_ -match ("(?i)^\s*" + $k + "\s*=") } | Select-Object -First 1)
      if (-not $have -or ($have -split "=", 2)[1].Trim() -ne $want) { Fail ("{0} del paquete no coincide con el .env" -f $k) }
    }
  }
  Write-Output "hub_host/device_id del paquete coinciden con el .env."
}

if ($DryRun) {
  $lockFile = Join-Path $AgentDir "agent.lock"
  $lp = "?"; if (Test-Path -LiteralPath $lockFile) { $lp = (Get-Content -LiteralPath $lockFile -Encoding UTF8 -TotalCount 1) }
  Write-Output ("DRYRUN: se haria backup de .env, se escribiria SECRET (UTF-8 sin BOM), " +
    "se VERIFICARIA el agente del lock PID={0} por lock+cmdline y se reiniciaria, " -f $lp +
    "se comprobaria 'Conectado y autenticado' + ESTABLISHED al puerto $HubPort, " +
    "y se destruiria rotation_package.json. No se ha modificado nada.")
  exit 0
}

# 2. Backup + escritura del SECRET (UTF-8 sin BOM, sin mostrarlo).
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$bak = "$envFile.bak-$stamp"
Copy-Item -LiteralPath $envFile -Destination $bak -Force
Write-Output ("Backup: " + (Split-Path $bak -Leaf))
$lines = Get-Content -LiteralPath $envFile -Encoding UTF8
$done = $false
$newLines = foreach ($ln in $lines) {
  if (-not $done -and $ln -match "(?i)^\s*SECRET\s*=") { $done = $true; "SECRET=$newSecret" } else { $ln }
}
if (-not $done) { $newLines += "SECRET=$newSecret" }
[System.IO.File]::WriteAllLines($envFile, $newLines, (New-Object System.Text.UTF8Encoding($false)))
Write-Output ".env actualizado en UTF-8 sin BOM (secreto NO mostrado)."

# 3. Reinicio por PID verificado (lock + cmdline con agent.py bajo AgentDir).
$lockFile = Join-Path $AgentDir "agent.lock"
if (-not (Test-Path -LiteralPath $lockFile)) { Fail "sin agent.lock: no se puede verificar PID" }
$oldPid = 0
try { $oldPid = [int]((Get-Content -LiteralPath $lockFile -Encoding UTF8 -TotalCount 1).Split()[0]) } catch { Fail "agent.lock ilegible" }
$proc = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $oldPid) -ErrorAction SilentlyContinue
$cmd = [string]$proc.CommandLine
if (-not $proc -or $cmd -notlike "*agent.py*") { Fail ("PID del lock no verificable como agent.py (pid=" + $oldPid + ")") }
if ($cmd -notlike ("*" + $AgentDir + "*")) { Fail "el agent.py del PID no esta bajo AgentDir" }
$interp = [string]$proc.ExecutablePath
if (-not $interp -or -not (Test-Path -LiteralPath $interp)) { Fail "interprete del proceso no localizable" }
Write-Output ("PID verificado: " + $oldPid + " (" + (Split-Path $interp -Leaf) + "). Deteniendo...")
Stop-Process -Id $oldPid -Force
Start-Sleep -Seconds 3
$logFile = Join-Path $AgentDir "logs\remote_agent.log"
$mark = 0
if (Test-Path -LiteralPath $logFile) { $mark = (Get-Item -LiteralPath $logFile).Length }
$agentPy = Join-Path $AgentDir "agent.py"
Start-Process -FilePath $interp -ArgumentList ("`"" + $agentPy + "`"") -WorkingDirectory $AgentDir -WindowStyle Hidden
Write-Output "Agente relanzado, esperando reconexion (max 90s)..."

# 4. Comprobaciones: "Conectado y autenticado" + ESTABLISHED al HubPort desde el nuevo PID.
$newPid = 0
$okLog = $false
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 5
  if (Test-Path -LiteralPath $lockFile) {
    try { $newPid = [int]((Get-Content -LiteralPath $lockFile -Encoding UTF8 -TotalCount 1).Split()[0]) } catch { $newPid = 0 }
  }
  if ($newPid -gt 0 -and $newPid -ne $oldPid) {
    try {
      $tail = Get-Content -LiteralPath $logFile -Encoding UTF8 -Tail 40 -ErrorAction SilentlyContinue
      if ($tail -match "Conectado y autenticado") { $okLog = $true }
    } catch { }
    $est = Get-NetTCPConnection -ErrorAction SilentlyContinue |
      Where-Object { $_.State -eq "Established" -and ($_.LocalPort -eq $HubPort -or $_.RemotePort -eq $HubPort) -and $_.OwningProcess -eq $newPid }
    if ($okLog -and $est) { break }
  }
}
if (-not $okLog) { Fail "sin 'Conectado y autenticado' en logs tras el reinicio" }
$est2 = Get-NetTCPConnection -ErrorAction SilentlyContinue |
  Where-Object { $_.State -eq "Established" -and ($_.LocalPort -eq $HubPort -or $_.RemotePort -eq $HubPort) -and $_.OwningProcess -eq $newPid }
if (-not $est2) { Fail ("sin ESTABLISHED al puerto " + $HubPort + " desde el nuevo PID") }
Write-Output ("Reconexion verificada: PID={0} log ok + ESTABLISHED al puerto {1}." -f $newPid, $HubPort)

# 5. Destruir el paquete (sobrescribir 3x y borrar).
try {
  $len = (Get-Item -LiteralPath $pkgFile).Length
  $rng = New-Object System.Random
  for ($i = 1; $i -le 3; $i++) {
    $buf = New-Object byte[] $len
    $rng.NextBytes($buf)
    [System.IO.File]::WriteAllBytes($pkgFile, $buf)
  }
} catch { Write-Output ("AVISO: no se pudo sobrescribir: " + $_.Exception.Message) }
Remove-Item -LiteralPath $pkgFile -Force
Write-Output "Paquete destruido (sobrescrito y borrado)."
Write-Output "ROTACION OK"
