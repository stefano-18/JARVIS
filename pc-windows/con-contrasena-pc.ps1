# JARVIS: lo que necesita administrador EN EL PC. Clic derecho sobre este archivo -> "Ejecutar con PowerShell"
# (pedirá permiso de administrador una vez). Hace:
#   1) desactiva las reglas genéricas "python.exe"/"pythonw.exe" que dejaban entrar por CUALQUIER puerto
#   2) crea reglas de JARVIS solo desde el portátil (agente, voz y Ollama)
#   3) permite el ping desde el portátil (así el estado del PC deja de salir "contradictorio")
# No borra reglas: solo desactiva las genéricas (se pueden volver a activar en el Firewall de Windows).
param([string]$Portatil = "")
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Portatil `"$Portatil`""
    exit
}
if (-not $Portatil) { $Portatil = Read-Host "IP del portátil (cerebro de JARVIS)" }
Write-Host "Portátil: $Portatil" -ForegroundColor Cyan
Write-Host "== 1) desactivar reglas genéricas de Python"
Get-NetFirewallRule -Direction Inbound -Action Allow -Enabled True | Where-Object { $_.DisplayName -in @("python.exe", "pythonw.exe") } | ForEach-Object {
    Disable-NetFirewallRule -Name $_.Name; Write-Host "  desactivada: $($_.DisplayName) ($($_.Profile))"
}
Write-Host "== 2) reglas de JARVIS solo desde el portátil"
$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
foreach ($r in @(@{n = "JARVIS-Python-desde-portatil"; p = $py })) {
    if ($r.p -and -not (Get-NetFirewallRule -DisplayName $r.n -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $r.n -Direction Inbound -Action Allow -Program $r.p -RemoteAddress $Portatil -Profile Any | Out-Null
        Write-Host "  creada: $($r.n)"
    }
}
Write-Host "== 3) ping desde el portátil"
if (-not (Get-NetFirewallRule -DisplayName "JARVIS-Ping-ICMP-desde-portatil" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "JARVIS-Ping-ICMP-desde-portatil" -Direction Inbound -Action Allow -Protocol ICMPv4 -IcmpType 8 -RemoteAddress $Portatil -Profile Any | Out-Null
    Write-Host "  creada: JARVIS-Ping-ICMP-desde-portatil"
}
Write-Host "`nListo. Las reglas Ollama-LAN-JARVIS y JARVIS-8765 (ya limitadas al portátil) no se tocan." -ForegroundColor Green
Read-Host "Pulsa Enter para cerrar"
