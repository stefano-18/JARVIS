"""Accion system.* (LOW). psutil si esta disponible; si no, stdlib minim managed.

Acciones de energia (HIGH, con concesion firmada obligatoria):
  system.shutdown / system.restart / system.lock / system.logoff /
  system.suspend.
Solo retornan status ok si el SO acepto de verdad el comando (returncode 0).
Cualquier denegacion de politica ocurre ANTES (execute_action) y jamas
retorna ok: el llamador (LLM del hub) debe leer el campo ok y NUNCA
anunciar exito si ok=false.
"""
import platform
import shutil
import subprocess
import sys

try:
    import psutil as _psutil
except Exception:
    _psutil = None


def _gpu() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return {"present": True, "info": out.stdout.strip().splitlines()[0]}
    except Exception:
        return {"present": False}
    return {"present": False}


def _run_power(cmd: list, action: str) -> dict:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {"returncode": out.returncode, "stdout": out.stdout, "stderr": out.stderr}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e)}


async def system_shutdown(params: dict, ctx: dict) -> dict:
    """Apaga el sistema. HIGH: requiere concesion firmada."""
    if sys.platform == "win32":
        r = _run_power(["shutdown", "/s", "/t", "0"], "shutdown")
    else:
        r = _run_power(["shutdown", "-h", "now"], "shutdown")
    ok = r["returncode"] == 0
    return {"status": "ok" if ok else "error", "executed": ok,
            "code": "ok" if ok else "shutdown_failed",
            "mensaje": f"Apagado {'exitoso' if ok else 'fallido'}"}


async def system_restart(params: dict, ctx: dict) -> dict:
    """Reinicia el sistema. HIGH: requiere concesion firmada."""
    if sys.platform == "win32":
        r = _run_power(["shutdown", "/r", "/t", "0"], "restart")
    else:
        r = _run_power(["reboot"], "restart")
    ok = r["returncode"] == 0
    return {"status": "ok" if ok else "error", "executed": ok,
            "code": "ok" if ok else "restart_failed",
            "mensaje": f"Reinicio {'exitoso' if ok else 'fallido'}"}


async def system_lock(params: dict, ctx: dict) -> dict:
    """Bloquea la estacion (Win+L). HIGH: solo llega aqui con concesion."""
    if sys.platform == "win32":
        return _run_power(
            ["rundll32.exe", "user32.dll,LockWorkStation"], "lock")
    return _run_power(["loginctl", "lock-session"], "lock")


async def system_suspend(params: dict, ctx: dict) -> dict:
    """Suspende el equipo (S3). HIGH: solo llega aqui con concesion.

    Windows: rundll32 powrprof.dll,SetSuspendState 0,1,0 (con hibernacion
    apagada suspende, no hiberna). Linux: systemctl suspend.
    """
    if sys.platform == "win32":
        return _run_power(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], "suspend")
    return _run_power(["systemctl", "suspend"], "suspend")


async def system_info(params: dict, ctx: dict) -> dict:
    """INFO: bajo riesgo (LOW), devuelve basic info del SO."""
    import platform
    return {"status": "ok", "executed": True, "action": "system_info",
            "sistema": platform.system(), "release": platform.release(),
            "version": platform.version(), "maquina": platform.machine()}


async def system_logoff(params: dict, ctx: dict) -> dict:
    """Cierra la sesion actual. HIGH: requiere concesion firmada."""
    if sys.platform == "win32":
        r = _run_power(["shutdown", "/l", "/f"], "logoff")
    else:
        r = _run_power(["loginctl", "session-close"], "logoff")
    ok = r["returncode"] == 0
    return {"status": "ok" if ok else "error", "executed": ok,
            "code": "ok" if ok else "logoff_failed",
            "mensaje": f"Sesion {'cerrada' if ok else 'fallida'}"}


async def sistema_estado(params: dict, ctx: dict) -> dict:
    """Devuelve el estado del PC: CPU, GPU, RAM, temperaturas, disco."""
    import os
    import platform
    try:
        import psutil as _psutil
    except Exception:
        _psutil = None

    if _psutil:
        cpu = _psutil.cpu_percent(interval=1)
        mem = _psutil.virtual_memory()
        disco = _psutil.disk_usage('/')
        mensaje = (f"CPU: {cpu}% | RAM: {mem.used // (1024**3)}GB / {mem.total // (1024**3)}GB "
                   f"| Disco: {disco.used // (1024**3)}GB / {disco.total // (1024**3)}GB "
                   f"| Temp: (lectura stub)")
    else:
        mensaje = "Estado del sistema (modo stub: psutil no disponible)"

    return {"status": "ok", "executed": True, "action": "sistema_estado",
            "mensaje": f"Estado del PC: {mensaje}"}