"""Servicio poller Telegram jarvis2 (UNICO poller del bot).

Con excepthook+faulthandler a archivo (bajo pythonw no hay consola) y
lock anti-duplicado. Lanzar vía Startup/JarvisTelegram.vbs (idempotente).
Auto-reinicio: si detecta cambios en ficheros del proyecto importados,
se reinicia via VBS (idempotente).
Uso:  pythonw scripts/telegram_service.py  (cwd = {{WIN_HOME_ESC}}\\jarvis2)
"""
import faulthandler
import os
import sys
import time
import traceback
from pathlib import Path

_JROOT = Path(__file__).resolve().parent.parent
if str(_JROOT) not in sys.path:
    sys.path.insert(0, str(_JROOT))

os.chdir(_JROOT)

LOGDIR = _JROOT / "logs"
LOGDIR.mkdir(exist_ok=True)
_FAULT_FH = open(LOGDIR / "telegram_service.fault.log", "a",
                 encoding="utf-8")
faulthandler.enable(_FAULT_FH)

ERRLOG = LOGDIR / "telegram_service.err.log"

VBS_LAUNCHER = _JROOT / "Startup" / "JarvisTelegram.vbs"


def _hook(t, v, tb):
    try:
        with open(ERRLOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S") + " EXCEPTHOOK:\n"
                    + "".join(traceback.format_exception(t, v, tb)) + "\n")
    except Exception:
        pass


sys.excepthook = _hook

LOCK = LOGDIR / "telegram_service.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong(0)
            if not ctypes.windll.kernel32.GetExitCodeProcess(
                    h, ctypes.byref(code)):
                return False
            return code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        return False


def acquire() -> bool:
    if LOCK.exists():
        try:
            old = int(LOCK.read_text(encoding="utf-8").strip().split()[0])
            if old != os.getpid() and _pid_alive(old):
                return False
        except Exception:
            pass
    LOCK.write_text(f"{os.getpid()}\n", encoding="utf-8")
    return True


def main() -> int:
    if not acquire():
        return 3
    try:
        from interface.telegram_client import main as tg_main
        from core.restart import AutoRestarter
        import asyncio
        
        async def run_with_restart():
            restarter = None
            try:
                restarter = AutoRestarter("telegram-service", str(VBS_LAUNCHER))
                await restarter.start()
            except RuntimeError:
                # AutoRestarter desactivado por defecto (JARVIS_AUTORESTART=0)
                pass
            # tg_main() es síncrono y bloqueante, lo ejecutamos en executor
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, tg_main)
            if restarter:
                await restarter.stop()
        
        return asyncio.run(run_with_restart())
    finally:
        try:
            if LOCK.exists() and LOCK.read_text(
                    encoding="utf-8").strip().split()[0] == str(os.getpid()):
                LOCK.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
