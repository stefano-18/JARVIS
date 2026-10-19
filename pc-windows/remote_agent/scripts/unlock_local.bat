@echo off
REM Desbloqueo LOCAL de emergencia del kill-switch (doble clic, sin red).
REM Pide confirmacion en consola y restablece killswitch.json a desbloqueado.
cd /d "%~dp0.."
python "%~dp0unlock_local.py"
pause
