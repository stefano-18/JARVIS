"""Politica evaluada en el agente (y espejada en el Core).

LOW: directo. MEDIUM: solo dentro de allowed_roots / apps / comandos.
HIGH: exige concesion firmada valida (ver protocol.check_grant).
"""
import os
from pathlib import Path

try:
    from remote_agent import protocol as P
except ImportError:  # ejecucion autocontenida en el PC (cwd=remote_agent)
    import protocol as P


def inbox_roots(roots: list) -> list:
    """Bandeja sin confirmacion: roots cuyo nombre es JARVIS-recibidos."""
    out = []
    for r in roots or []:
        try:
            if Path(r).name.lower() == "jarvis-recibidos":
                out.append(str(Path(r).resolve()))
        except Exception:
            continue
    return out


def is_inbox_path(path: str, roots: list) -> bool:
    """True si path resuelto esta dentro de JARVIS-recibidos."""
    try:
        real = str(Path(path).resolve())
    except Exception:
        return False
    for b in inbox_roots(roots):
        if real == b or real.startswith(b + os.sep):
            return True
    return False


def resolve_in_roots(path: str, roots: list) -> tuple[bool, str, str]:
    """Normaliza, resuelve symlinks y exige containment. Retorna (ok, real, motivo)."""
    try:
        real = str(Path(path).resolve())
    except Exception as e:
        return False, "", f"ruta invalida: {e}"
    for r in roots:
        try:
            base = str(Path(r).resolve())
        except Exception:
            continue
        if real == base or real.startswith(base + os.sep):
            return True, real, "ok"
    return False, real, "fuera de allowed_roots"


def evaluate(action: dict, params: dict, grant: dict, ctx: dict,
             secret: str, used_grants: set) -> tuple[bool, str]:
    """action: manifiesto {name, risk, ...}. ctx: {roots, apps, commands}."""
    risk = action.get("risk", "low")
    if risk == "low":
        return True, "ok"
    if risk == "medium":
        scope = action.get("scope", "")
        if scope == "files":
            if "path" in (params or {}):
                ok, _, why = resolve_in_roots(params.get("path", ""), ctx.get("roots", []))
                return ok, why
            if "src" in (params or {}) or "dst" in (params or {}):
                ok1, _, w1 = resolve_in_roots((params or {}).get("src", ""),
                                              ctx.get("roots", []))
                if not ok1:
                    return False, f"origen: {w1}"
                ok2, _, w2 = resolve_in_roots((params or {}).get("dst", ""),
                                              ctx.get("roots", []))
                return (ok2, w2)
            ok, _, why = resolve_in_roots(params.get("path", ""), ctx.get("roots", []))
            return ok, why
        if scope == "apps":
            app = str(params.get("app", "")).lower()
            return (app in ctx.get("apps", {}), "ok" if app in ctx.get("apps", {}) else "app fuera de allowlist")
        if scope == "shell":
            cmd = str(params.get("cmd", "")).lower()
            return (cmd in ctx.get("commands", []), "ok" if cmd in ctx.get("commands", []) else "comando fuera de allowlist")
        if scope == "clipboard":
            # el portapapeles se limita a 64KB por operacion. read no lleva
            # parametros que limitar; write con texto mayor se deniega.
            # (En este PC clipboard.read/write estan declarados HIGH, asi que
            # esta rama solo se alcanza si un manifiesto baja a MEDIUM.)
            if action.get("name") == "clipboard.write":
                text = params.get("text")
                if text is None:
                    return False, "clipboard.write sin text"
                if len(str(text)) > 64 * 1024:
                    return False, "clipboard.write supera 64KB"
            return True, "ok"
        if scope == "media":
            return True, "ok"
        return False, "medium sin scope conocido"
    if risk == "high":
        if not grant:
            return False, "HIGH sin concesion"
        return P.check_grant(secret, grant, action["name"], params, used_grants)
    return False, "riesgo desconocido"
