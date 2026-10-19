@echo off
REM Lanzador: clic derecho > "Ejecutar como administrador". No auto-eleva.
powershell -ExecutionPolicy Bypass -File "%~dp0ajustes_energia_admin.ps1"
pause
