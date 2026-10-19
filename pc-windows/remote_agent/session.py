"""Grants DE SESION (FASE B1). Detras de SESSION_GRANTS=1 (0 = apagado).

Formato para la laptop (documentado):
  session = {"session_id": str, "actions": [str...], "issued": int,
             "expires": int, "max_actions": int, "target": str-opcional,
             "hmac": str}
  hmac = HMAC_SHA256(secret, session_id.actions_canonical.issued.expires.
                     max_actions.target)
  actions_canonical = ",".join(sorted(actions))

Reglas:
 - TTL = expires-issued <= 600 s (si falta alguno -> rechazo).
 - Rechaza si falta id/acciones/TTL/max, si caduco, si contador agotado,
   si la accion no esta en la lista o si esta en EXCLUIDAS.
 - EXCLUIDAS: clipboard.read, shell.exec, system.* (shutdown/restart/lock/
   logoff), borrado (files.delete). Esas SIEMPRE exigen concesion de un
   solo uso (protocol.check_grant), nunca sesion.
 - Un solo ID de sesion activo (el ultimo valido revoca el anterior).
 - Kill switch revoca la sesion (se limpia al bloquear/desbloquear).
 - Audita session_id, restantes y resultado (el llamador lo registra).
 - Respuesta: {"status","executed","session_remaining","error","code"}
   (error nunca vacio cuando status=error).
"""
import time

try:
    from remote_agent import protocol as P
except ImportError:
    import protocol as P

SESSION_TTL_MAX_S = 600
EXCLUDED_EXACT = {"clipboard.read", "shell.exec", "files.delete"}
EXCLUDED_PREFIX = ("system.",)


def is_excluded(action: str) -> bool:
    a = str(action or "")
    if a in EXCLUDED_EXACT:
        return True
    return any(a.startswith(p) for p in EXCLUDED_PREFIX)


def _canon_actions(actions) -> str:
    try:
        return ",".join(sorted(str(x) for x in (actions or [])))
    except Exception:
        return ""


def mint_session(secret: str, actions: list, max_actions: int,
                 ttl_s: int = 600, target: str = "",
                 session_id: str = None, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    ttl_s = min(int(ttl_s), SESSION_TTL_MAX_S)
    session_id = session_id or P.new_id()
    issued = int(now)
    expires = issued + int(ttl_s)
    acts = list(actions or [])
    canon = _canon_actions(acts)
    sig = P.hmac_hex(secret,
                     f"{session_id}.{canon}.{issued}.{expires}."
                     f"{int(max_actions)}.{target or ''}")
    return {"session_id": session_id, "actions": acts, "issued": issued,
            "expires": expires, "max_actions": int(max_actions),
            "target": target or "", "hmac": sig}


def check_session(secret: str, session: dict, action: str,
                  ctx: dict, now: int = None) -> tuple:
    """(ok, remaining|0, why). No muta contador (el llamador descuenta)."""
    now = int(time.time()) if now is None else now
    try:
        sid = session["session_id"]
        acts = session["actions"]
        issued = int(session["issued"])
        exp = int(session["expires"])
        maxn = int(session["max_actions"])
    except (KeyError, TypeError, ValueError):
        return False, 0, "sesion incompleta (falta id/acciones/TTL/max)"
    if not sid or not isinstance(acts, list) or not acts:
        return False, 0, "sesion incompleta (id/acciones vacios)"
    if exp - issued > SESSION_TTL_MAX_S or exp <= issued:
        return False, 0, "sesion TTL>600s o invalido"
    if now > exp:
        return False, 0, "sesion caducada"
    if str(action or "") not in [str(x) for x in acts]:
        return False, 0, "accion no permitida en esta sesion"
    if is_excluded(action):
        return False, 0, "accion EXCLUIDA de sesiones (exige concesion unica)"
    canon = _canon_actions(acts)
    expect = P.hmac_hex(secret,
                         f"{sid}.{canon}.{issued}.{exp}."
                         f"{maxn}.{session.get('target', '') or ''}")
    try:
        import hmac as _hm
        if not _hm.compare_digest(expect, str(session.get("hmac", ""))):
            return False, 0, "firma de sesion invalida"
    except Exception:
        return False, 0, "firma de sesion invalida"
    # Un solo ID activo + contador.
    active = ctx.get("_session_id")
    if active is not None and active != sid:
        return False, 0, "otra sesion activa (un solo ID)"
    used = int(ctx.get("_session_used", 0) or 0)
    remaining = int(maxn) - used
    if remaining <= 0:
        return False, 0, "sesion agotada (contador)"
    return True, remaining - 1, "ok"


def consume_session(ctx: dict, session: dict) -> int:
    """Registra un uso (tras ejecucion autorizada). Retorna restantes."""
    try:
        sid = session.get("session_id")
    except Exception:
        return 0
    if ctx.get("_session_id") is None:
        ctx["_session_id"] = sid
    ctx["_session_used"] = int(ctx.get("_session_used", 0) or 0) + 1
    try:
        maxn = int(session.get("max_actions", 0))
    except Exception:
        maxn = 0
    return max(0, maxn - int(ctx.get("_session_used", 0)))


def revoke_session(ctx: dict) -> None:
    ctx.pop("_session_id", None)
    ctx.pop("_session_used", None)


def session_response(ok: bool, remaining: int, action: str,
                     error: str = "", code: str = "") -> dict:
    if ok:
        return {"status": "ok", "executed": True,
                "session_remaining": int(remaining),
                "error": "", "code": code or "ok"}
    msg = (error or "").strip() or f"sesion denegada ({action})"
    return {"status": "error", "executed": False,
            "session_remaining": int(remaining),
            "error": msg[:300], "code": code or "session_denied"}
