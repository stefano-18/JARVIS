# make_agent_release.ps1 — Regenera la exportacion limpia de agent_pc, la escanea,
# la prueba en un venv nuevo con directorios temporales y la compara con el zip.
#
# Uso: powershell -ExecutionPolicy Bypass -File make_agent_release.ps1
# Sale 0 siempre que export+scan+tests pasen. Al final dice "sin cambios"
# (Desktop\agent_pc.zip intacto) o escribe un agent_pc.zip nuevo y lista cambios.
# Nunca toca el agente vivo, su .env, audit, killswitch, logs ni locks.
# Nunca imprime secretos.
param(
  [string]$AgentDir = "C:\jarvis_agent\remote_agent",
  [string]$ExportDir = "C:\jarvis_agent\release_export\agent_pc",
  [string]$ZipPath = ""
)
$ErrorActionPreference = "Stop"
if (-not $ZipPath) { $ZipPath = Join-Path $env:USERPROFILE "Desktop\agent_pc.zip" }
function Fail([string]$msg) { Write-Output ("ERROR: " + $msg); exit 1 }

$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("opencode\release_stage")
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("opencode\agent_release_test_" + (Get-Date -Format "yyyyMMdd-HHmmss"))
foreach ($d in @($stage, $work)) { if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force } }
New-Item -ItemType Directory -Path $stage, (Join-Path $stage "tests"), (Join-Path $stage "scripts"), $work -Force | Out-Null

# 1. Exportacion limpia (listas explicitas; NADA de .env/audit/killswitch/logs/lock/outbox/caches,
#    NADA de tooling operativo check_boot/apply_rotation/make_agent_release/boot_report).
$rootPy = @("__init__.py", "actions.py", "actions_apps.py", "actions_desktop.py",
  "actions_files.py", "actions_media.py", "actions_process.py", "actions_shell.py", "actions_system.py",
  "actions_tasks.py", "agent.py", "audit.py", "config.py", "killswitch.py",
  "policy.py", "presence.py", "protocol.py", "session.py", "voice.py")
foreach ($f in $rootPy) {
  $s = Join-Path $AgentDir $f
  if (-not (Test-Path -LiteralPath $s -PathType Leaf)) { Fail ("falta en origen: " + $f) }
  Copy-Item -LiteralPath $s -Destination (Join-Path $stage $f) -Force
}
Copy-Item -LiteralPath (Join-Path $AgentDir "README_KILLSWITCH.md") -Destination (Join-Path $stage "README_KILLSWITCH.md") -Force
Copy-Item -LiteralPath (Join-Path $AgentDir "scripts\unlock_local.py") -Destination (Join-Path $stage "scripts\unlock_local.py") -Force
Copy-Item -LiteralPath (Join-Path $AgentDir "scripts\unlock_local.bat") -Destination (Join-Path $stage "scripts\unlock_local.bat") -Force
Get-ChildItem -LiteralPath (Join-Path $AgentDir "tests") -Filter "*.py" -File |
  Where-Object { $_.Name -notmatch "__pycache__" } |
  ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $stage "tests\$($_.Name)") -Force }
# Sanitizacion idempotente: ruta personal o de ejemplo -> variable %LOCALAPPDATA%.
$tap = Join-Path $stage "tests\test_apps_owned.py"
$taptxt = Get-Content -LiteralPath $tap -Raw -Encoding UTF8
$taptxt = $taptxt -replace 'IDE = "C:\\\\Users\\\\{{WIN_USUARIO}}\\\\AppData\\\\Local\\\\Programs\\\\Antigravity IDE\\\\Antigravity IDE\.exe"',
  'IDE = "%LOCALAPPDATA%\\Programs\\Antigravity IDE\\Antigravity IDE.exe"'
$taptxt = $taptxt -replace 'IDE = "%LOCALAPPDATA%\\\\Programs\\\\Example IDE\\\\example\.exe"',
  'IDE = "%LOCALAPPDATA%\\Programs\\Antigravity IDE\\Antigravity IDE.exe"'
[System.IO.File]::WriteAllText($tap, $taptxt, (New-Object System.Text.UTF8Encoding($false)))
# Artefactos ya limpios de la exportacion (plantillas versionadas, sin secretos).
foreach ($f in @(".env.example", "install_agent.ps1", "README.md")) {
  $s = Join-Path $ExportDir $f
  if (-not (Test-Path -LiteralPath $s -PathType Leaf)) { Fail ("falta plantilla en exportacion: " + $f) }
  Copy-Item -LiteralPath $s -Destination (Join-Path $stage $f) -Force
}
$staged = @(Get-ChildItem -LiteralPath $stage -Recurse -File)
Write-Output ("Export preparada: " + $staged.Count + " ficheros.")

# 2. Escaner de secretos y datos personales (tolerancia cero; solo recuentos).
$rx = @{
  "TOKEN_TG" = "\b\d{8,10}:[A-Za-z0-9_-]{35}\b";
  "HEX64"    = "\b[0-9a-fA-F]{64}\b";
  "IP_192"   = "192\.168\.\d+\.\d+";
  "IP_10"    = "\b10\.\d+\.\d+\.\d+\b";
  "IP_172"   = "\b172\.(1[6-9]|2\d|3[01])\.\d+\.\d+\b";
  "USUARIO_WIN" = [regex]::Escape($env:USERNAME);   # el usuario de Windows de quien lo ejecuta, sin escribirlo aquí
  "C_USERS"  = "C:\\Users"
}
$bad = 0
foreach ($k in $rx.Keys) {
  $hits = @()
  foreach ($f in $staged) {
    $t = ""
    try { $t = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8 } catch { continue }
    if ([string]::IsNullOrEmpty($t)) { continue }
    $c = ([regex]::Matches($t, $rx[$k])).Count
    if ($c -gt 0) { $hits += ($f.Name + "(x" + $c + ")"); $bad += $c }
  }
  Write-Output ($k + ": " + $bad + " total; ficheros=[" + ($hits -join ", ") + "]")
}
foreach ($n in @(".env", "audit.jsonl", "killswitch.json", "killswitch_local.log", "agent.lock", "voice_outbox.txt")) {
  if (Test-Path -LiteralPath (Join-Path $stage $n)) { Fail ("fichero prohibido en export: " + $n) }
}
if ((Get-ChildItem -LiteralPath $stage -Recurse -Filter "*.log" | Measure-Object).Count -gt 0) { Fail "hay *.log en export" }
if ($bad -gt 0) { Fail "escaner con hallazgos" }
Write-Output "Escaner limpio."

# 3. Prueba en venv nuevo con directorios temporales.
$py = $null
foreach ($c in @("python", "py -3", "py")) {
  try {
    $parts = $c -split " "
    & $parts[0] @($parts[1..($parts.Count - 1)] + "--version") 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $py = $c; break }
  } catch { }
}
if (-not $py) { Fail "sin Python en PATH" }
$parts = $py -split " "
Copy-Item -Path (Join-Path $stage "*") -Destination $work -Recurse -Force
& $parts[0] @($parts[1..($parts.Count - 1)] + @("-m", "venv", (Join-Path $work ".venv"))) 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "no se pudo crear venv" }
$vpy = Join-Path $work ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip 2>&1 | Out-Null
& $vpy -m pip install websockets pytest psutil mss Pillow pywin32 2>&1 | Select-Object -Last 2
if ($LASTEXITCODE -ne 0) { Fail "pip install fallo" }
$tres = & $vpy -m pytest (Join-Path $work "tests") -q -p no:cacheprovider 2>&1
$tres | Select-Object -Last 3 | ForEach-Object { Write-Output $_ }
if ($LASTEXITCODE -ne 0) { Fail "suite en rojo" }
foreach ($n in @("audit.jsonl", "killswitch.json", "killswitch_local.log", "agent.lock", "voice_outbox.txt")) {
  if (Test-Path -LiteralPath (Join-Path $work $n)) { Fail ("la suite toco " + $n + " en el arbol de prueba") }
}
if (Test-Path -LiteralPath (Join-Path $work "logs")) { Fail "la suite creo logs/ en el arbol de prueba" }
Write-Output "Suite verde y sin tocar runtime de prueba."

# 4. Manifiesto del stage vs contenido del zip anterior.
function Get-Manifest([string]$dir) {
  $m = @{}
  foreach ($f in (Get-ChildItem -LiteralPath $dir -Recurse -File)) {
    $rel = $f.FullName.Substring($dir.Length).TrimStart("\", "/")
    $m[$rel] = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
  }
  return $m
}
function Get-ZipManifest([string]$zip) {
  $m = @{}
  if (-not (Test-Path -LiteralPath $zip)) { return $m }
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $z = [System.IO.Compression.ZipFile]::OpenRead($zip)
  try {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    foreach ($e in $z.Entries) {
      if ($e.FullName.EndsWith("/")) { continue }
      $rel = $e.FullName -replace "^agent_pc[\\/]", ""
      $st = $e.Open()
      try { $m[$rel] = ([BitConverter]::ToString($sha.ComputeHash($st))).Replace("-", "") }
      finally { $st.Dispose() }
    }
  } finally { $z.Dispose() }
  return $m
}
$ms = Get-Manifest $stage
$mz = Get-ZipManifest $ZipPath
$added = @($ms.Keys | Where-Object { -not $mz.ContainsKey($_) } | Sort-Object)
$removed = @($mz.Keys | Where-Object { -not $ms.ContainsKey($_) } | Sort-Object)
$changed = @($ms.Keys | Where-Object { $mz.ContainsKey($_) -and $ms[$_] -ne $mz[$_] } | Sort-Object)
Write-Output ("manifiesto: stage=" + $ms.Count + " zip=" + $mz.Count +
  " anadidos=" + $added.Count + " eliminados=" + $removed.Count + " cambiados=" + $changed.Count)
foreach ($a in $added) { Write-Output ("+ " + $a) }
foreach ($r in $removed) { Write-Output ("- " + $r) }
foreach ($c in $changed) { Write-Output ("~ " + $c) }

# 5. Sincronizar exportacion y decidir sobre el zip.
if (Test-Path -LiteralPath $ExportDir) { Remove-Item -LiteralPath $ExportDir -Recurse -Force }
New-Item -ItemType Directory -Path $ExportDir -Force | Out-Null
Copy-Item -Path (Join-Path $stage "*") -Destination $ExportDir -Recurse -Force
if (($added.Count + $removed.Count + $changed.Count) -eq 0) {
  Remove-Item -LiteralPath $stage -Recurse -Force
  Remove-Item -LiteralPath $work -Recurse -Force
  Write-Output "sin cambios"
  exit 0
}
if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Compress-Archive -Path $ExportDir -DestinationPath $ZipPath
Write-Output ("ZIP NUEVO: " + $ZipPath)
Remove-Item -LiteralPath $stage -Recurse -Force
Remove-Item -LiteralPath $work -Recurse -Force
Write-Output "RELEASE CON CAMBIOS (ver lista +,-,~ arriba)"

# 6. ENTREGA SIN USB (en ROOTS): agent_pc.zip + partes base64 48KB + sha256.
# Todo nuevo apagado por defecto ya viene en config (flags=0); aqui solo
# empaquetado verificable via files.read (cada parte <64KB => se lee entera).
$RootsDir = "C:\JARVIS-PC"
$ZipName = "agent_pc.zip"
$RootsZip = Join-Path $RootsDir $ZipName
Copy-Item -LiteralPath $ZipPath -Destination $RootsZip -Force
$ZipBytes = [System.IO.File]::ReadAllBytes($RootsZip)
$Sha = (Get-FileHash -LiteralPath $RootsZip -Algorithm SHA256).Hash
[System.IO.File]::WriteAllText((Join-Path $RootsDir ($ZipName + ".sha256")), ($Sha + "  " + $ZipName), (New-Object System.Text.UTF8Encoding($false)))
Write-Output ("SHA256: " + $Sha)
$b64 = [Convert]::ToBase64String($ZipBytes)
$Chunk = 48 * 1024
Get-ChildItem -LiteralPath $RootsDir -Filter ($ZipName + ".b64.part*.txt") -File -ErrorAction SilentlyContinue | Remove-Item -Force
$n = 0
for ($i = 0; $i -lt $b64.Length; $i += $Chunk) {
  $n++
  $part = $b64.Substring($i, [Math]::Min($Chunk, $b64.Length - $i))
  $pname = ("{0}.b64.part{1:00}.txt" -f $ZipName, $n)
  [System.IO.File]::WriteAllText((Join-Path $RootsDir $pname), $part, (New-Object System.Text.UTF8Encoding($false)))
}
Write-Output ("PARTES: " + $n + " x max 48KB en " + $RootsDir)
$rec = ""
foreach ($f in (Get-ChildItem -LiteralPath $RootsDir -Filter ($ZipName + ".b64.part*.txt") -File | Sort-Object Name)) {
  $t = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8
  if ($t.Length -gt $Chunk) { Fail ("parte excede 48KB: " + $f.Name) }
  if ($t.Length -ge 65536) { Fail ("parte no legible entera via files.read (64KB): " + $f.Name) }
  $rec += $t.Trim()
}
$recBytes = [Convert]::FromBase64String($rec)
$sha2 = ([BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash($recBytes))).Replace("-", "")
if ($sha2 -ne $Sha) { Fail "SHA256 reconstruido no coincide" }
Write-Output "VERIFICADO: reconstruido coincide con SHA256 y partes legibles via files.read."
