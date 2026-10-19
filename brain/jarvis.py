"""Arranque/apagado ejemplo del proceso principal: store + bus +
notificador + manager, espera Ctrl+C y cierra limpio con aclose().

Uso:  cd {{WIN_HOME_ESC}}\\jarvis2  ;  python scripts\\jarvis.py
"""
import asyncio
import sys
from pathlib import Path

_JROOT = Path(__file__).resolve().parent.parent
if str(_JROOT) not in sys.path:
    sys.path.insert(0, str(_JROOT))

from core.event_bus import EventBus
from core.logging import setup_logger
from tasks.store import TaskStore
from tasks.worker import TaskManager
from tasks.notify import TaskNotifier

logger = setup_logger("jarvis-main")


async def amain() -> int:
    bus = EventBus()
    notifier = TaskNotifier()  # data/task_notifications.jsonl
    notifier.attach(bus)
    store = TaskStore(str(_JROOT / "data" / "tasks.db"))
    manager = TaskManager(store, bus=bus)
    # Warmup Piper en background: evita 5 s de carga en la primera voz.
    async def _warm():
        from voice import tts as _t
        secs = await asyncio.to_thread(_t.warmup_piper)
        logger.info("warmup Piper: %s",
                    f"{secs:.1f}s" if secs else "no disponible")
    asyncio.create_task(_warm())
    from remote import bootstrap as _boot
    ctx0 = {}
    boot = await _boot.ensure_hub(ctx0)
    logger.info("hub remoto: %s",
                "arriba" if boot.get("hub") else boot.get("error"))
    logger.info("jarvis listo (Ctrl+C para salir)")
    try:
        while True:
            await asyncio.sleep(1.0)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await _boot.close_hub(ctx0)
        await manager.aclose()  # cancela dispatcher + workers en curso
        logger.info("jarvis detenido limpio")
    return 0


def main() -> int:
    try:
        return asyncio.run(amain())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
