#Requires -Version 5.1
<#
.SYNOPSIS
  Ajustes de energía que EXIGEN administrador. NO ejecutar sin leer.
  Lanzar con: clic derecho en ajustes_energia_admin.bat > Ejecutar como administrador.
  No toca el roaming.
#>
$ErrorActionPreference = "Stop"
# 1) Hibernación del sistema (requiere admin). Estado actual: HIBERNATEIDLE=0
#    (nunca). Solo si quieres desactivarla del todo:
# powercfg /hibernate off
# 2) Ahorro de energía por NIC Wi-Fi (Device Manager). Sustituye "Wi-Fi" por
#    el nombre exacto de tu adaptador si difiere:
# Set-NetAdapterPowerManagement -Name "Wi-Fi" -WakeOnMagicPacket Disabled `
#   -WakeOnPattern Disabled -DeviceSleepOnDisconnect Disabled
# 3) Acción al cerrar la tapa: en este equipo NO existe la subclave LIDACTION
#    (5ca83367-6e45-459f-a27b-476b1d01c936) en el plan Equilibrado, por lo que
#    powercfg no puede fijarla. Alternativas manuales: Panel de control >
#    Opciones de energía > "Elegir el comportamiento del cierre de la tapa".
Write-Output "Lee el script antes de ejecutar. Nada aplicado por defecto."
