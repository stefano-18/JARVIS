"""Kill-switch local del agente (persistente en disco).

Bloqueado = se deniega TODA accion MEDIUM y HIGH; las LOW de solo lectura
siguen funcionando. NO mata procesos ni apaga nada: solo bloquea la puerta
de execute_action y persiste el estado para sobrevivir a un reinicio.
"""
import json
import time
from pathlib import Path

STATE_FILE_NAME = "killswitch.json"


def state_path(project_root) -> Path:
    return Path(project_root) / STATE_FILE_NAME


def is_locked(path) -> bool:
    """True si el fichero marca bloqueado. Ausente/corrupto = desbloqueado."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return bool(data.get("locked", False))
    except Exception:
        return False


def set_locked(path, locked: bool, trace_id: str = "-") -> dict:
    """Persiste el estado. Retorna el dict escrito."""
    state = {"locked": bool(locked), "ts": int(time.time()),
             "trace_id": str(trace_id or "-")}
    p = Path(path)
    if p.parent and str(p.parent) not in ("", "."):
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return state


def load(path) -> dict:
    """Lee el estado bruto (para tests de supervivencia al reinicio)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {"locked": False}
