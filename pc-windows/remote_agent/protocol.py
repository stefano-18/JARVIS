"""Protocolo jarvis2-remote (SOLO stdlib, autocontenido para el PC).

Tipos de mensaje (prefijo jr_, NUNCA reutilizan el protocolo del hub antiguo):
  jr_hello (S->C): {"type":"jr_hello","nonce","hub","v"}
  jr_auth  (C->S): {"type":"jr_auth","device_id","ts","hmac"}
                   hmac = HMAC_SHA256(secret, nonce.device_id.ts)
  jr_welcome (S->C): {"type":"jr_welcome","device_id"}
  jr_req   (S->C, con sobre): {"action","params","grant","trace_id"}
  jr_res   (C->S, con sobre): {"ok","result","error","trace_id"}
  jr_evt   (C->S, con sobre): eventos (p.ej. audit)

Sobre (todos los mensajes tras el handshake):
  {"msg_id","ts","ctr","type","payload","hmac"}
  hmac = HMAC_SHA256(secret, msg_id.ts.ctr.type.json_canonical(payload))

NOTA: sin TLS el trafico va FIRMADO pero NO cifrado.
"""
import hashlib
import hmac as _hmac
import json
import time
import uuid

PROTOCOL_V = 1
TS_WINDOW_S = 30


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def hmac_hex(secret: str, msg: str) -> str:
    return _hmac.new(secret.encode("utf-8"), msg.encode("utf-8"),
                     hashlib.sha256).hexdigest()


def new_nonce() -> str:
    import secrets
    return secrets.token_hex(16)


def new_id() -> str:
    return uuid.uuid4().hex


def sign_envelope(secret: str, msg_id: str, ts: int, ctr: int,
                  mtype: str, payload: dict) -> str:
    return hmac_hex(secret, f"{msg_id}.{ts}.{ctr}.{mtype}.{canonical(payload)}")


def make_envelope(secret: str, mtype: str, payload: dict,
                  ctr: int, ts: int = None, msg_id: str = None) -> dict:
    ts = int(time.time()) if ts is None else ts
    msg_id = new_id() if msg_id is None else msg_id
    return {
        "msg_id": msg_id,
        "ts": ts,
        "ctr": ctr,
        "type": mtype,
        "payload": payload,
        "hmac": sign_envelope(secret, msg_id, ts, ctr, mtype, payload),
    }


class ChannelGuard:
    """Valida sobre entrante: firma, ventana ts, contador creciente, anti-replay."""

    def __init__(self, secret: str, ts_window: int = TS_WINDOW_S):
        self.secret = secret
        self.ts_window = ts_window
        self.last_ctr: int = 0
        self.seen: set = set()

    def check(self, env: dict) -> tuple[bool, str]:
        try:
            msg_id = env["msg_id"]
            ts = int(env["ts"])
            ctr = int(env["ctr"])
            mtype = env["type"]
            payload = env["payload"]
            sig = env["hmac"]
        except (KeyError, TypeError, ValueError):
            return False, "sobre incompleto"
        now = int(time.time())
        if abs(now - ts) > self.ts_window:
            return False, "ts fuera de ventana"
        if ctr <= self.last_ctr:
            return False, "contador no creciente"
        if msg_id in self.seen:
            return False, "replay (msg_id repetido)"
        if len(self.seen) > 10000:
            self.seen.clear()
        expect = sign_envelope(self.secret, msg_id, ts, ctr, mtype, payload)
        if not _hmac.compare_digest(expect, sig):
            return False, "firma invalida"
        self.last_ctr = ctr
        self.seen.add(msg_id)
        return True, "ok"


def make_auth(secret: str, nonce: str, device_id: str, ts: int = None) -> dict:
    ts = int(time.time()) if ts is None else ts
    return {
        "type": "jr_auth",
        "device_id": device_id,
        "ts": ts,
        "hmac": hmac_hex(secret, f"{nonce}.{device_id}.{ts}"),
    }


def check_auth_multi(secret: str, nonce: str, accepted: set,
                   msg: dict, ts_window: int = TS_WINDOW_S) -> tuple[bool, str]:
    """Como check_auth pero acepta cualquiera de los device_id del conjunto."""
    try:
        dev = msg["device_id"]
    except (KeyError, TypeError):
        return False, "auth incompleto"
    if dev not in accepted:
        return False, "device_id desconocido"
    return check_auth(secret, nonce, dev, msg, ts_window)


def check_auth(secret: str, nonce: str, device_id_expected: str,
               msg: dict, ts_window: int = TS_WINDOW_S) -> tuple[bool, str]:
    try:
        dev = msg["device_id"]
        ts = int(msg["ts"])
        sig = msg["hmac"]
    except (KeyError, TypeError, ValueError):
        return False, "auth incompleto"
    if dev != device_id_expected:
        return False, "device_id desconocido"
    if abs(int(time.time()) - ts) > ts_window:
        return False, "ts fuera de ventana"
    expect = hmac_hex(secret, f"{nonce}.{dev}.{ts}")
    if not _hmac.compare_digest(expect, sig):
        return False, "firma invalida"
    return True, "ok"


# ---- Concesiones HIGH (firmadas, 60 s, un solo uso, ligadas a accion+params) ----

GRANT_TTL_S = 60


def params_hash(params: dict) -> str:
    return sha256_hex(canonical(params or {}))


def mint_grant(secret: str, action: str, params: dict,
               now: int = None, grant_id: str = None) -> dict:
    now = int(time.time()) if now is None else now
    grant_id = new_id() if grant_id is None else grant_id
    ph = params_hash(params)
    exp = now + GRANT_TTL_S
    sig = hmac_hex(secret, f"{grant_id}.{action}.{ph}.{exp}")
    return {"grant_id": grant_id, "action": action, "params_hash": ph,
            "expires": exp, "hmac": sig}


def check_grant(secret: str, grant: dict, action: str, params: dict,
                used: set, now: int = None) -> tuple[bool, str]:
    now = int(time.time()) if now is None else now
    try:
        gid = grant["grant_id"]
        exp = int(grant["expires"])
        sig = grant["hmac"]
    except (KeyError, TypeError, ValueError):
        return False, "concesion incompleta"
    if grant.get("action") != action:
        return False, "concesion de otra accion"
    if grant.get("params_hash") != params_hash(params):
        return False, "concesion de otros parametros"
    if now > exp:
        return False, "concesion caducada"
    if gid in used:
        return False, "concesion reutilizada"
    expect = hmac_hex(secret, f"{gid}.{action}.{grant['params_hash']}.{exp}")
    if not _hmac.compare_digest(expect, sig):
        return False, "firma de concesion invalida"
    return True, "ok"
