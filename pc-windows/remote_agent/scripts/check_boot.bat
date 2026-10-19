@echo off
REM check_boot — doble clic: diagnostico de arranque + abre boot_report.txt (solo lectura).
cd /d "%~dp0.."
python "scripts\check_boot.py"
echo.
echo Veredicto arriba y en scripts\boot_report.txt (sin secretos).
start "" notepad.exe "scripts\boot_report.txt"
pause
