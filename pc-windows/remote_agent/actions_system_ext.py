"""Módulo de acciones del sistema para JARVIS remote agent.
Contains stub functions for system status and operations.
"""


async def sistema_estado(params: dict, ctx: dict) -> dict:
    """Devuelve el estado del PC: CPU, GPU, RAM, temperaturas, disco."""
    import os
    import platform
    try:
        import psutil
    except ImportError:
        psutil = None

    if psutil:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disco = psutil.disk_usage('/')
        mensaje = (f"CPU: {cpu}% | RAM: {mem.used // (1024**3)}GB / {mem.total // (1024**3)}GB "
                   f"| Disco: {disco.used // (1024**3)}GB / {disco.total // (1024**3)}GB "
                   f"| Temp: (lectura stub)")
    else:
        mensaje = "Estado del sistema (modo stub: psutil no disponible)"

    return {"status": "ok", "executed": True, "action": "sistema_estado",
            "mensaje": f"Estado del PC: {mensaje}"}


async def acciones_sistema_base(params: dict, ctx: dict) -> dict:
    """Acción base para acciones del sistema (apagar, reiniciar, etc.)"""
    nombre = params.get("accion", "")
    return {"status": "ok", "executed": True, "action": "acciones_sistema_base",
            "mensaje": f"Comando del sistema '{nombre}' recibido (modo stub)"}