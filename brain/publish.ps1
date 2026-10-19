#Requires -Version 5.1
<#
.SYNOPSIS
  Publica jarvis2-release como repo PRIVADO y añade un colaborador.
  NO ejecutar sin leer. Nunca crea repos públicos.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/publish.ps1 -Repo "mi-jarvis" -Amigo "usuario" -DryRun
#>
param(
  [string]$Repo = "",
  [string]$Amigo = "",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Release = "{{WIN_HOME_BARRA}}/jarvis2-release"

function Abort([string]$msg) { Write-Error $msg; exit 2 }

if ([string]::IsNullOrWhiteSpace($Repo)) { Abort "Falta -Repo (nombre del repo)." }
if ([string]::IsNullOrWhiteSpace($Amigo)) { Abort "Falta -Amigo (usuario de GitHub)." }

$dirty = git -C $Release status --porcelain
if ($dirty) { Abort "El release tiene cambios sin commit. Regenera con make_release.py." }
$n = (git -C $Release rev-list --count HEAD).Trim()
if ($n -ne "1") { Abort "El release debe tener 1 commit (tiene $n)." }

# Escaneo de secretos: reutiliza las claves de make_release (solo recuento).
Write-Output "Escaneando secretos (solo recuentos)..."
$scan = python -X utf8 -c "
import sys; sys.path.insert(0, '{{WIN_HOME_BARRA}}/jarvis2/scripts')
import make_release as M
u, p = M._secretos_vivos()
from pathlib import Path
mal = 0
for f in Path('{{WIN_HOME_BARRA}}/jarvis2-release').rglob('*'):
    if f.is_dir() or '.git' in f.parts: continue
    try:
        if f.stat().st_size > 2000000: continue
        t = f.read_text(encoding='utf-8', errors='ignore')
    except Exception: continue
    if any(len(s) >= 8 and s in t for s in u): mal += 1
print(mal)
"
if ($scan.Trim() -ne "0") { Abort "Escaneo de secretos distinto de 0. No se publica." }

$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
  Abort ("gh sin instalar: ejecuta 'winget install GitHub.cli' y luego "
    + "'gh auth login' (navegador), y repite.")
}
gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
  Abort ("gh sin autenticar: ejecuta 'gh auth login' y repite. "
    + "Si no tienes gh: 'winget install GitHub.cli'.")
}

if ($DryRun) {
  Write-Output "[DryRun] crearía repo PRIVADO '$Repo', añadiría '$Amigo' y haría push. NADA hecho."
  exit 0
}

gh repo create $Repo --private --source $Release --push
if ($LASTEXITCODE -ne 0) { Abort "gh repo create falló." }
$owner = (gh api user -q .login).Trim()
gh api "repos/$owner/$Repo/collaborators/$Amigo" -X PUT -f permission=push 2>$null
if ($LASTEXITCODE -ne 0) { Abort "Repo creado pero falló añadir a '$Amigo' (hazlo a mano en GitHub)." }
Write-Output "Repo PRIVADO '$Repo' publicado y '$Amigo' añadido. Verifica en GitHub que es privado."
