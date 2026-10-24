# JARVIS - instalador de la parte del PC con Windows (agente remoto + voz). Sin claves en el repositorio.
# Uso (PowerShell normal, NO hace falta administrador):
#   .\pc-windows\instalar-pc.ps1 -Portatil 192.168.1.50 [-Simulacion]   # el cerebro está en otro equipo
#   .\pc-windows\instalar-pc.ps1 -Completa [-Simulacion]                # el cerebro está en WSL en este mismo PC
# El secreto del hub (JARVIS_REMOTE_SECRET del cerebro) se pide por teclado; con -Completa se lee solo de WSL.
param([string]$Portatil = "192.168.1.50", [string]$Destino = "C:\jarvis_agent", [string]$Voz = "C:\jarvis_voz",
      [switch]$Completa, [switch]$Simulacion)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSCommandPath  # la carpeta pc-windows
if ($Completa) { $Portatil = "127.0.0.1" }
function Haz($texto, [scriptblock]$accion) { if ($Simulacion) { "[simulación] $texto" } else { "+ $texto"; & $accion } }

$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "Instale antes Python 3.11+ (python.org) marcando 'Add to PATH'." }
$pyc = $py -replace 'pythonw.exe$', 'python.exe'
"Python: $py"

Haz "copiar el agente a $Destino\remote_agent" {
    New-Item -ItemType Directory -Force $Destino | Out-Null; Copy-Item -Recurse -Force "$repo\remote_agent" "$Destino\" }
Haz "copiar la voz a $Voz" { New-Item -ItemType Directory -Force $Voz | Out-Null; Copy-Item -Recurse -Force "$repo\voz\*" $Voz }
Haz "instalar las librerías de Python del agente y la voz" {
    & $pyc -m pip install -q websockets psutil mss pillow pywin32 pycaw comtypes numpy edge-tts sherpa-onnx openwakeword pyaudio }

# Secreto compartido con el cerebro: con -Completa se lee del WSL de este PC; si no, se pide (no se muestra).
$secreto = ""
if ($Completa -and -not $Simulacion) {
    $secreto = (wsl.exe -e sh -c "sed -n 's/^JARVIS_REMOTE_SECRET=//p' ~/jarvis2/.env | tr -d '\042\047' | head -1").Trim()
}
if (-not $secreto -and -not $Simulacion) {
    $s = Read-Host -AsSecureString "Secreto del hub (JARVIS_REMOTE_SECRET del cerebro)"
    $secreto = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}
Haz "configurar el agente ($Destino\remote_agent\.env, hub en ${Portatil}:18765)" {
    @("DEVICE_ID=pc-01", "SECRET=$secreto", "HUB_HOST=$Portatil", "HUB_PORT=18765", "SCREEN_C1=1", "MEDIA_VOLUME=1",
      "ROOTS=$env:USERPROFILE") | Set-Content -Encoding UTF8 "$Destino\remote_agent\.env" }
Haz "decirle a la voz dónde está el cerebro (JARVIS_WS_URL=ws://${Portatil}:8765)" {
    [Environment]::SetEnvironmentVariable("JARVIS_WS_URL", "ws://${Portatil}:8765", "User") }

$inicio = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
Haz "arranque oculto del agente (Inicio\JARVIS-Agente.vbs)" {
    "CreateObject(""WScript.Shell"").Run """"""$py"""" """"$Destino\remote_agent\agent.py"""""", 0, False" | Set-Content -Encoding ASCII "$inicio\JARVIS-Agente.vbs" }
Haz "arranque oculto de la voz (Inicio\JARVIS-Voz.vbs)" {
    "CreateObject(""WScript.Shell"").Run """"""$py"""" """"$Voz\jarvis_voz.py"""""", 0, False" | Set-Content -Encoding ASCII "$inicio\JARVIS-Voz.vbs" }

@"

Listo. Cierre sesión y vuelva a entrar (o haga doble clic en los .vbs de Inicio) para arrancar el agente y la voz.
$(if (-not $Completa) { "Cortafuegos (como administrador): permita solo desde $Portatil los puertos que use el agente." })
"@
