# JARVIS - instalador de la parte del PC con Windows (agente remoto + voz). Sin claves.
# Uso (PowerShell normal, NO hace falta administrador):  .\instalar-pc.ps1 -Portatil 192.168.1.50 [-Simulacion]
param([string]$Portatil = "192.168.1.50", [string]$Destino = "C:\jarvis_agent", [string]$Voz = "C:\jarvis_voz", [switch]$Simulacion)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSCommandPath)  # pc-windows\..
function Haz($texto, [scriptblock]$accion) { if ($Simulacion) { "[simulación] $texto" } else { "+ $texto"; & $accion } }

$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "Instale antes Python 3.11+ (python.org) marcando 'Add to PATH'." }
"Python: $py"

Haz "copiar remote_agent a $Destino\remote_agent" { New-Item -ItemType Directory -Force "$Destino" | Out-Null; Copy-Item -Recurse -Force "$repo\pc\remote_agent" "$Destino\" }
Haz "copiar la voz a $Voz" { New-Item -ItemType Directory -Force $Voz | Out-Null; Copy-Item -Recurse -Force "$repo\pc\voz\*" $Voz }
foreach ($req in @("$Destino\remote_agent\requirements.txt", "$Voz\requirements.txt")) {
    if (Test-Path $req) { Haz "pip install -r $req" { & ($py -replace 'pythonw.exe$', 'python.exe') -m pip install -q -r $req } }
}
$inicio = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
Haz "arranque oculto del agente (Startup\JARVIS-Agente.vbs)" {
    "CreateObject(""WScript.Shell"").Run """"""$py"""" """"$Destino\remote_agent\agent.py"""""", 0, False" | Set-Content -Encoding ASCII "$inicio\JARVIS-Agente.vbs" }
Haz "arranque oculto de la voz (Startup\JARVIS-Voz.vbs)" {
    "CreateObject(""WScript.Shell"").Run """"""$py"""" """"$Voz\jarvis_voz.py"""""", 0, False" | Set-Content -Encoding ASCII "$inicio\JARVIS-Voz.vbs" }

@"

Falta a mano (nunca por chat):
  1. Copiar $Destino\remote_agent\.env.example a .env y poner la IP del portátil ($Portatil) y el secreto compartido.
  2. Copiar $Voz\.env.agent.example a .env.agent y poner ws://$Portatil:8765.
  3. Cortafuegos (como administrador): permitir solo desde $Portatil los puertos que use el agente.
  4. Cerrar sesión y volver a entrar (o ejecutar los .vbs de Inicio) para arrancar.
"@
