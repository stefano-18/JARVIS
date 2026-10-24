"""hud_server_8765.py — WS :8765 para HUD (jarvis-ui) y JarvisV2Agent.

Sigue ref-8765: hud.js (WS_URL ws://{{PORTATIL_IP}}:8765, mensajes
state/transcript/voice_result/tts_chunk/subtitle/model_info/gpu_info/map)
y cliente-v2/PROTOCOLO.md v2.0+v2.1 (hello role=agent, heartbeat, pong,
pc_result, task_progress, task_result, tts_result, offline).

Sin auth (como el supervisor original). Solo LAN (UFW limita a
{{RED}}.0/24). Logs a stdout (journald).
"""
import asyncio
import json
import logging
import time
import voz_cerebro  # arreglo 16: cerebro de voz

try:
    from websockets.asyncio.server import serve
except ImportError:  # pragma: no cover
    from websockets import serve  # type: ignore

def _escucha_ip():
    # arreglo 88: sale de ~/.config/jarvis/config.toml (escucha_ip); por defecto solo este equipo
    try:
        import os, tomllib
        with open(os.path.expanduser("~/.config/jarvis/config.toml"), "rb") as f:
            return tomllib.load(f).get("escucha_ip", "127.0.0.1")
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


HOST = _escucha_ip()
PORT = 8765

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [8765] %(levelname)s %(message)s")
log = logging.getLogger("hud-8765")

CLIENTS: set = set()
AGENTS: set = set()
LAST_STATE = {"state": "idle"}


def model_info_msg() -> str:
    return json.dumps({"type": "model_info", "model": "qwen3-jarvis-fast",
                       "provider": "ollama-pc"}, ensure_ascii=False)


async def broadcast(msg: str, skip=None) -> None:
    dead = []
    for ws in list(CLIENTS):
        if ws is skip:
            continue
        try:
            await ws.send(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        CLIENTS.discard(ws)
        AGENTS.discard(ws)


async def handle(ws) -> None:
    CLIENTS.add(ws)
    peer = getattr(ws, "remote_address", "?")
    log.info("conexion %s (total=%d)", peer, len(CLIENTS))
    try:
        await ws.send(json.dumps({"type": "state", **LAST_STATE},
                                  ensure_ascii=False))
        await ws.send(model_info_msg())
        async for raw in ws:
            try:
                data = json.loads(raw)
            except Exception:
                continue
            t = str(data.get("type") or "")
            if t == "audio":
                asyncio.create_task(voz_cerebro.handle_audio(ws, data))
                continue
            if t == "hello":
                if data.get("role") == "agent":
                    AGENTS.add(ws)
                    log.info("agente registrado %s node=%s", peer,
                             data.get("node", {}).get("location", "?"))
                await ws.send(json.dumps({"type": "state", **LAST_STATE},
                                         ensure_ascii=False))
            elif t == "heartbeat":
                pass  # v2.1: se acepta, respuesta opcional
            elif t == "pong":
                pass
            elif t == "state" and data.get("role") == "agent":
                if data.get("online") is not None:
                    log.info("agente state %s", data.get("online"))
            elif t == "offline":
                AGENTS.discard(ws)
                log.info("agente offline %s", peer)
            elif t in ("subtitle", "transcript"):
                await broadcast(json.dumps(data, ensure_ascii=False), skip=ws)
            elif t in ("pc_result", "task_result", "tts_result"):
                log.info("%s ok=%s %s", t, data.get("ok"),
                         str(data.get("summary") or data.get("error") or "")[:120])
            elif t == "task_progress":
                pass
            elif t in ("audio", "mic_level"):
                pass  # HUD mic desactivado (Fase1b); se acepta y se ignora
    except Exception as e:
        log.info("cierre %s: %s", peer, type(e).__name__)
    finally:
        CLIENTS.discard(ws)
        AGENTS.discard(ws)
        log.info("desconexion %s (total=%d)", peer, len(CLIENTS))


async def ping_loop() -> None:
    while True:
        await asyncio.sleep(60)
        if AGENTS:
            msg = json.dumps({"type": "ping", "ts": time.time()})
            for ws in list(AGENTS):
                try:
                    await ws.send(msg)
                except Exception:
                    pass


async def decir_loop() -> None:
    """arreglo 76: lo que el equipo deja en ~/.config/jarvis/decir/ lo dice la voz del PC (si esta conectada)."""
    import glob, os
    d = os.path.expanduser("~/.config/jarvis/decir")
    while True:
        await asyncio.sleep(2)
        for f in sorted(glob.glob(os.path.join(d, "*.txt"))):
            try:
                txt = open(f, encoding="utf-8").read().strip()
                viejo = time.time() - os.path.getmtime(f) > 120
                if CLIENTS and txt:
                    await broadcast(json.dumps({"type": "reply", "text": voz_cerebro._pronuncia(txt), "end": True}, ensure_ascii=False))
                    os.remove(f)
                elif viejo or not txt:
                    os.remove(f)
            except Exception as e:  # noqa: BLE001
                log.info("decir: %s", e)


async def main() -> None:
    log.info("WS 8765 en %s:%d (HUD + agentes)", HOST, PORT)
    async with serve(handle, HOST, PORT, max_size=16 * 1024 * 1024):
        asyncio.create_task(decir_loop())
        await ping_loop()


if __name__ == "__main__":
    asyncio.run(main())
