"""Config del agente (SOLO stdlib: parser .env propio, sin dependencias).

Orden: variables de entorno del proceso > .env junto al agente > valores base.
En tests se puede pasar overrides dict (sin tocar disco).
"""
import os
from pathlib import Path

BASE = {
    "HUB_HOST": "127.0.0.1",
    "HUB_PORT": "18765",
    "DEVICE_ID": "",
    "SECRET": "",
    "ROOTS": "",            # separados por os.pathsep
    "APPS": "",             # "nombre=exe;nombre=exe" o "nombre" (PATH)
    "COMMANDS": "hostname,whoami",
    "SHELL_TIMEOUT": "10",
    "OUTPUT_MAX": "65536",
    "BACKOFF_BASE": "1.0",
    "BACKOFF_MAX": "30.0",
    "AUDIT_LOG": "audit.jsonl",
    "HIGH_MAX_PER_MINUTE": "10",  # limitador local HIGH: max/60s
    "HIGH_MAX_PER_HOUR": "60",    # limitador local HIGH: max/3600s
    "VOICE_IN": "0",            # 1 = captura microfono + STT local (fase 2)
    "VOICE_VAD": "25",          # umbral RMS (mismo que mic_bridge.py)
    "VOICE_STT_MODEL": "medium",
    "VOICE_SHADOW": "0",
    "VOICE_WAKE": "0",
    "VOICE_WAKE_MODEL": "hey_jarvis",
    "VOICE_WAKE_THRESHOLD": "0.5",
    "VOICE_SHADOW_LOG": "voice_shadow.jsonl",
    "PRESENCE": "0",
    "TTS_PRIORITY": "0",
    "SESSION_GRANTS": "0",
    "MEDIA_VOLUME": "0",
    "FILES_EXT": "0",
    "SCREEN_C1": "0",
}


def _parse_dotenv(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return out


def load(overrides: dict = None, dotenv_path: Path = None) -> dict:
    cfg = dict(BASE)
    base = dotenv_path or (Path(__file__).parent / ".env")
    cfg.update(_parse_dotenv(base))
    for k in BASE:
        if k in os.environ and os.environ[k]:
            cfg[k] = os.environ[k]
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


def roots(cfg: dict) -> list:
    return [r for r in (cfg.get("ROOTS") or "").split(os.pathsep) if r]


def apps(cfg: dict) -> dict:
    out = {}
    for item in (cfg.get("APPS") or "").split(";"):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            k, v = item.split("=", 1)
            out[k.strip().lower()] = v.strip()
        else:
            out[item.lower()] = item
    return out


def commands(cfg: dict) -> list:
    return [c.strip().lower() for c in (cfg.get("COMMANDS") or "").split(",") if c.strip()]
