"""Módulo de acciones de juegos para JARVIS remote agent.
Contains stub functions for game-related actions.
"""


async def juego_abrir(params: dict, ctx: dict) -> dict:
    """Abre un juego por nombre."""
    nombre = params.get("nombre", "")
    return {"status": "ok", "executed": True, "action": "juego_abrir", "nombre": nombre,
            "mensaje": f"Comando 'juego.abrir {nombre}' recibido (modo stub)"}


async def juego_actualizar(params: dict, ctx: dict) -> dict:
    """Actualiza un juego por nombre."""
    nombre = params.get("nombre", "")
    return {"status": "ok", "executed": True, "action": "juego_actualizar", "nombre": nombre,
            "mensaje": f"Comando 'juego.actualizar {nombre}' recibido (modo stub). Para Fortnite: abrir Epic Games Launcher y verificar actualización."}


async def juego_listar(params: dict, ctx: dict) -> dict:
    """Lista juegos instalados."""
    return {"status": "ok", "executed": True, "action": "juego_listar",
            "mensaje": "Lista de juegos (modo stub): Cyberpunk 2077, ELDEN RING, Fortnite, etc."}