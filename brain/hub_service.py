"""Servicio hub jarvis2-remote: UNICO dueno del puerto del agente.

Lee secreto/device de jarvis2/.env (nunca en linea de comandos), sirve el
protocolo jr_* en JR_HOST:JR_PORT + canal local loopback de clientes en
127.0.0.1:<control_port de config/remote.yaml>.

Lock anti-duplicado en logs/hub_service.lock (stale se reclama): si otro
proceso ya es dueno, este sale con codigo 3 en vez de crear split-brain.

Auto-reinicio: si detecta cambios en ficheros del proyecto importados,
se reinicia via VBS (idempotente).

Uso:  pythonw scripts/hub_service.py   (cwd = {{WIN_HOME_ESC}}\\jarvis2)
"""
import asyncio
import os
import sys
import time
from pathlib import Path

_JROOT = Path(__file__).resolve().parent.parent
if str(_JROOT) not in sys.path:
    sys.path.insert(0, str(_JROOT))

LOCK = _JROOT / "logs" / "hub_service.lock"
VBS_LAUNCHER = _JROOT / "Startup" / "JarvisHub18765.vbs"


def _load_dotenv() -> dict:
    vals = {}
    try:
        for line in (_JROOT / ".env").read_text(
                encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return vals


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
            return code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        return False


def acquire() -> bool:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        try:
            old = int(LOCK.read_text(encoding="utf-8").strip().split()[0])
            if old != os.getpid() and _pid_alive(old):
                print(f"hub_service: otro dueno vivo (PID {old}), salgo",
                      flush=True)
                return False
        except Exception:
            pass
    LOCK.write_text(f"{os.getpid()}\n", encoding="utf-8")
    return True


def _make_voice_brain_handler(hub):
    """Consumidor voz->cerebro: jr_voice_text -> handle_voice_text -> TTS.

    Lazy imports (sin ciclos): ctx persistente y COMPLETO (vault, store,
    writer, short via new_context) reutilizado entre mensajes para que la
    memoria de corto plazo y las confirmaciones pendientes sobrevivan al
    multi-turno (antes era un ctx desnudo por mensaje: sin historia, sin
    memoria larga y sin pending). Responde el audio por el mismo hub
    (jr_tts fire-and-forget). Nunca lanza: todo fallo se registra y la
    entrada ya quedó auditada + encolada en el hub.
    """
    _shared = {}

    def _ctx():
        if _shared.get("ctx") is None:
            try:
                from interface.router import new_context as _new_ctx
                from memory.settings import default_vault_path
                from memory.obsidian_vault import ObsidianVault
                from memory.sqlite_store import SQLiteStore
                from memory.writer import MemoryWriter
                v = ObsidianVault(default_vault_path())
                # Misma base que el poller Telegram: pending/confirms y
                # rolling compartidos entre canales (conexiones por llamada,
                # apto para dos procesos).
                s = SQLiteStore(str(_JROOT / "data" / "tg_memory.db"))
                _shared["ctx"] = _new_ctx(
                    vault=v, store=s, writer=MemoryWriter(v, s))
            except Exception:
                from interface.router import new_context as _nc2
                _shared["ctx"] = _nc2()
        return _shared["ctx"]

    async def _on_voice(entry: dict):
        try:
            from voice.inout import handle_voice_text as _hvt
            ctx = _ctx()
            ctx["channel"] = "voice"
            ctx["hub"] = hub
            out = await _hvt(entry.get("text", ""), ctx)
            audio = (out or {}).get("audio")
            if audio:
                import base64 as _b64
                await hub.send_tts(
                    _b64.b64encode(audio).decode("ascii"),
                    mime=(out or {}).get("mime") or "audio/mpeg",
                    trace_id=entry.get("trace_id") or None,
                    device=entry.get("device") or None)
        except Exception as e:
            try:
                import logging as _lg
                _lg.getLogger("hub-service").warning(
                    f"voz->cerebro fallo: {e}")
            except Exception:
                pass
    return _on_voice


async def _amain() -> int:
    from remote.hub import HubServer
    from core.logging import setup_logger
    from core.restart import AutoRestarter
    logger = setup_logger("hub-service")
    env = _load_dotenv()
    # Exporta .env al entorno (sin sobreescribir): voice/tts.py lee
    # JARVIS_PIPER_MODEL al importar y brain/priorities.py lee
    # JARVIS_PRIORITIES en cada dispatch. Sin esto, el handler de voz
    # sintetizaría en vacío aunque .env esté bien.
    for _k, _v in env.items():
        if _k and _v:
            os.environ.setdefault(_k, _v)
    secret = os.getenv("JARVIS_REMOTE_SECRET") or env.get(
        "JARVIS_REMOTE_SECRET", "")
    secret_next = os.getenv("JARVIS_REMOTE_SECRET_NEXT") or env.get(
        "JARVIS_REMOTE_SECRET_NEXT", "")
    device = os.getenv("JARVIS_REMOTE_DEVICE_ID") or env.get(
        "JARVIS_REMOTE_DEVICE_ID", "")
    if not secret or not device:
        print("hub_service: falta JARVIS_REMOTE_DEVICE_ID/SECRET",
              flush=True)
        return 2
    host = os.getenv("JR_HOST", "0.0.0.0")
    port = int(os.getenv("JR_PORT", "18765"))
    control = int(os.getenv("JR_CONTROL_PORT", "0") or 0)
    if not control:
        try:
            import yaml
            reg = yaml.safe_load(
                (_JROOT / "config" / "remote.yaml").read_text(
                    encoding="utf-8"))
            control = int((reg.get("hub", {}) or {}).get(
                "control_port", 18766))
        except Exception:
            control = 18766
    audit = os.getenv("JR_AUDIT",
                      str(_JROOT / "logs" / "remote_audit.jsonl"))
    
    # Auto-restarter: solo si JARVIS_AUTORESTART=1
    restarter = None
    try:
        restarter = AutoRestarter("hub-service", str(VBS_LAUNCHER))
        await restarter.start()
    except RuntimeError:
        # Desactivado por defecto
        pass
    
    async with HubServer(host=host, port=port, secret=secret,
                           device_id=device, audit_path=audit,
                           control_port=control, secret_next=secret_next,
                           env_path=str(_JROOT / ".env")) as hub:
        hub.register_voice_handler(_make_voice_brain_handler(hub))
        logger.info(f"hub en servicio {host}:{port} + local :{control} "
                    f"(voz->cerebro activo)")
        while True:
            await asyncio.sleep(3600)


def main() -> int:
    if not acquire():
        return 3
    try:
        return asyncio.run(_amain())
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            if LOCK.exists() and LOCK.read_text(
                    encoding="utf-8").strip().split()[0] == str(os.getpid()):
                LOCK.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
