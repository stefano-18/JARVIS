#!/usr/bin/env python3
"""jarvis_gate.py - Control del modo seguro JARVIS por Telegram.

Comandos:
  verify <palabra>           Verifica palabra (constante-tiempo). No la muestra.
  activate <chat_id> <msg_id>  Activa modo seguro, borra mensaje, avisa.
  close                      Desactiva modo seguro ("cerrar jarvis").
  status                     Estado del modo seguro / bloqueo.
  check-high                 "OK" si UNLOCKED vigente, "DENIED" si no.

Seguridad:
  - Nunca imprime la palabra candidata ni la almacenada.
  - 3 fallos consecutivos => LOCK + aviso por Telegram.
  - Hash en tiempo constante (pbkdf2, hmac.compare_digest).
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path("{{HOME}}/jarvis-control")
HASH_FILE = BASE / "clave.hash"
LOCK_FILE = BASE / "LOCK"
UNLOCKED_FILE = BASE / "UNLOCKED"
FAIL_FILE = BASE / "fail_count"
AUDIT = BASE / "audit.log"
TG_TOKEN_FILE = Path("{{HOME}}/.openclaw/telegram-token")
SAFE_MODE_MINUTES = 5
MAX_FAILS = 3


def _read_hash() -> str:
    try:
        return HASH_FILE.read_text().strip()
    except FileNotFoundError:
        return ""


def _audit(action: str, detail: str = ""):
    try:
        with open(AUDIT, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {action} {detail}\n")
    except OSError:
        pass


def _tg_token() -> str:
    try:
        return TG_TOKEN_FILE.read_text().strip()
    except FileNotFoundError:
        return ""


def _tg_delete_message(chat_id: str, message_id: str) -> bool:
    """Borra mensaje por API de Telegram. True si OK."""
    token = _tg_token()
    if not token:
        return False
    url = f"https://api.telegram.org/bot{token}/deleteMessage"
    data = json.dumps({"chat_id": chat_id, "message_id": int(message_id)}).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read().decode())
            return resp.get("ok") is True
    except Exception as e:
        _audit("TG_DELETE_FAIL", str(e)[:100])
        return False


def _tg_send_message(chat_id: str, text: str) -> bool:
    """Envía mensaje por API de Telegram. True si OK."""
    token = _tg_token()
    if not token:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read().decode())
            return resp.get("ok") is True
    except Exception as e:
        _audit("TG_SEND_FAIL", str(e)[:100])
        return False


def verify_keyword(candidate: str) -> bool:
    """Verifica en tiempo constante. Nunca filtra la candidata."""
    stored = _read_hash()
    if not stored or not candidate:
        return False
    try:
        algo, salt, h = stored.split(":", 2)
    except ValueError:
        return False
    if algo != "pbkdf2":
        return False
    calc = hashlib.pbkdf2_hmac("sha256", candidate.encode(),
                               salt.encode(), 200000).hex()
    return hmac.compare_digest(calc, h)


def _get_fails() -> int:
    try:
        return int(FAIL_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _set_fails(n: int):
    FAIL_FILE.write_text(str(n))


def is_locked() -> bool:
    return LOCK_FILE.exists()


def safe_mode_active() -> bool:
    """True si UNLOCKED existe y no expiró (5 min)."""
    try:
        ts = float(UNLOCKED_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return False
    if time.time() - ts > SAFE_MODE_MINUTES * 60:
        try:
            UNLOCKED_FILE.unlink()
        except FileNotFoundError:
            pass
        return False
    return True


def activate_safe_mode(chat_id: str, message_id: str) -> dict:
    """Activa modo seguro. Borra mensaje. Resetea fallos."""
    if is_locked():
        return {"status": "locked", "message": "Sistema bloqueado. Contacta al administrador."}

    # Escribir UNLOCKED con timestamp actual
    UNLOCKED_FILE.write_text(str(int(time.time())))
    _set_fails(0)

    # Borrar mensaje del usuario
    deleted = _tg_delete_message(chat_id, message_id)

    _audit("UNLOCK", f"chat={chat_id} deleted={deleted}")
    return {
        "status": "unlocked",
        "message": "Modo seguro activado, señor",
        "message_deleted": deleted,
    }


def close_safe_mode(chat_id: str = "") -> dict:
    """Cierra modo seguro. 'cerrar jarvis'"""
    existed = UNLOCKED_FILE.exists()
    try:
        UNLOCKED_FILE.unlink()
    except FileNotFoundError:
        pass
    if chat_id:
        _tg_send_message(chat_id, "Modo seguro desactivado, señor.")
    _audit("CLOSE", f"chat={chat_id} existed={existed}")
    return {"status": "closed", "existed": existed}


def handle_verify(chat_id: str, message_id: str, candidate: str) -> dict:
    """Flujo completo: verifica, activa o bloquea."""
    if is_locked():
        return {"status": "locked", "message": "Sistema bloqueado. Contacta al administrador."}

    if verify_keyword(candidate):
        # Éxito: resetea fallos y activa
        _set_fails(0)
        return activate_safe_mode(chat_id, message_id)
    else:
        # Fallo: incrementa y verifica bloqueo
        fails = _get_fails() + 1
        _set_fails(fails)
        _audit("FAIL", f"chat={chat_id} count={fails}")
        if fails >= MAX_FAILS:
            LOCK_FILE.touch()
            _audit("LOCK", f"chat={chat_id}")
            _tg_send_message(chat_id, "Demasiados intentos fallidos. Sistema bloqueado. Contacta al administrador.")
            return {"status": "locked", "message": "Demasiados intentos fallidos. Sistema bloqueado."}
        remaining = MAX_FAILS - fails
        return {
            "status": "wrong",
            "message": f"Palabra incorrecta. {remaining} intentos restantes antes del bloqueo.",
            "attempts_remaining": remaining,
        }


def cmd_status() -> dict:
    locked = is_locked()
    unlocked = safe_mode_active()
    fails = _get_fails()
    return {
        "locked": locked,
        "unlocked": unlocked,
        "fails": fails,
        "unlock_file": str(UNLOCKED_FILE) if UNLOCKED_FILE.exists() else None,
    }


def main():
    if len(sys.argv) < 2:
        print("Uso: jarvis_gate.py verify <palabra> | activate <chat_id> <msg_id> | close [chat_id] | status | check-high")
        return 2

    cmd = sys.argv[1]

    if cmd == "verify":
        if len(sys.argv) < 3:
            print("Falta palabra")
            return 2
        # En modo producción, verify se llama desde el skill con chat_id y msg_id
        # pero para testing directo solo verificamos
        ok = verify_keyword(sys.argv[2])
        print("OK" if ok else "FAIL")
        return 0 if ok else 1

    elif cmd == "activate":
        if len(sys.argv) < 4:
            print("Falta chat_id o message_id")
            return 2
        chat_id, msg_id = sys.argv[2], sys.argv[3]
        # Para testing directo sin verificación real
        UNLOCKED_FILE.write_text(str(int(time.time())))
        deleted = _tg_delete_message(chat_id, msg_id)
        _audit("UNLOCK", f"chat={chat_id} deleted={deleted}")
        print(json.dumps({"status": "unlocked", "message_deleted": deleted}))
        return 0

    elif cmd == "close":
        chat_id = sys.argv[2] if len(sys.argv) > 2 else ""
        result = close_safe_mode(chat_id)
        print(json.dumps(result))
        return 0

    elif cmd == "status":
        print(json.dumps(cmd_status(), indent=2))
        return 0

    elif cmd == "check-high":
        if safe_mode_active():
            print("OK")
            return 0
        else:
            print("DENIED")
            return 1

    elif cmd == "test-flow":
        # Flujo completo: verify + activate (para testing)
        if len(sys.argv) < 5:
            print("Uso: test-flow <chat_id> <msg_id> <palabra>")
            return 2
        chat_id, msg_id, candidate = sys.argv[2], sys.argv[3], sys.argv[4]
        result = handle_verify(chat_id, msg_id, candidate)
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "unlocked" else 1

    else:
        print(f"Comando desconocido: {cmd}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
