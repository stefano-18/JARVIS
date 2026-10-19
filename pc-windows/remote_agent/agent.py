"""Cliente del agente: conexion SALIENTE al hub, handshake HMAC, ejecuta
acciones con politica re-evaluada localmente, reconexion con backoff.

Uso PC:  python agent.py   (cwd = carpeta remote_agent, con su .env)
Uso test: python -m remote_agent.agent  (cwd = jarvis2)
"""
import subprocess as _jx_sp, sys as _jx_sys
if _jx_sys.platform == "win32":
    class _JxNoWin(_jx_sp.Popen):
        def __init__(self, *a, **k):
            if not k.get("creationflags"):
                k["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: nada de ventanas a la vista
            super().__init__(*a, **k)
    _jx_sp.Popen = _JxNoWin
import asyncio
import atexit
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from remote_agent import protocol as P, config as C, policy as _pol
    from remote_agent import actions as A, audit as _audit
    from remote_agent import voice as V
    from remote_agent import killswitch as _ks
    from remote_agent import presence as _pr
except ImportError:  # autocontenido en el PC
    import protocol as P, config as C, policy as _pol
    import actions as A, audit as _audit
    import voice as V
    import killswitch as _ks
    try:
        import presence as _pr
    except ImportError:
        _pr = None

try:
    from websockets.asyncio.client import connect
except ImportError:
    from websockets import connect  # fallback API antigua


# --- PRODUCCION PC: lock anti-duplicado + log local (no toca el protocolo) ---
# Mismo patron que mic_bridge.lock de jarvis-v2-fijo.
PROJECT_ROOT = Path(__file__).resolve().parent
LOCK_FILE = PROJECT_ROOT / "agent.lock"
LOG_FILE = PROJECT_ROOT / "logs" / "remote_agent.log"
KILL_FILE = PROJECT_ROOT / "killswitch.json"
UNLOCK_ACTION = "agent.unlock"
_lock_owned = False


def _redact(msg: str) -> str:
    """Espejo del filtro de la laptop: cualquier pinta de secreto/token/hex
    largo se redacta ANTES de escribirse al log. Solo informativo: los
    hashes del audit.jsonl viven en su fichero estructurado, no pasan por
    aqui (redactarlos romperia la cadena)."""
    try:
        msg = _RE_BOT.sub("[REDACTED_TELEGRAM_TOKEN]", msg)
        msg = _RE_HEX64.sub("[REDACTED_HEX64]", msg)
        msg = _RE_KV.sub(lambda m: f"{m.group(1)}=[REDACTED]", msg)
    except Exception:
        return "[REDACTED_LOG_LINE]"
    return msg


def _log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{ts} {_redact(msg)}\n")
    except Exception:
        pass


def _pid_alive(pid: int) -> bool:
    """True si el proceso pid sigue vivo (Windows + POSIX)."""
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(pid)
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = kernel32.OpenProcess(0x1000, False, pid)
            if h:
                kernel32.CloseHandle(h)
                return True
            return False
        except Exception:
            pass
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe pero sin permiso -> vivo
    except Exception:
        return False


def acquire_lock() -> None:
    """Toma agent.lock o se niega con error claro si otra instancia vive."""
    global _lock_owned
    me = os.getpid()
    if LOCK_FILE.exists():
        try:
            other = int(LOCK_FILE.read_text(encoding="utf-8", errors="ignore").strip().split()[0])
        except Exception:
            other = -1
        if other > 0 and other != me and _pid_alive(other):
            msg = (f"ERROR: remote_agent ya corriendo (PID {other} vivo, lock {LOCK_FILE}). "
                   f"Este proceso (PID {me}) se niega a arrancar un duplicado.")
            _log(msg)
            print(msg, file=sys.stderr, flush=True)
            sys.exit(1)
        reason = "huerfano" if other > 0 else "corrupto/vacio"
        _log(f"Lock {LOCK_FILE} {reason} (pid={other}) -> tomando el lock con PID {me}")
    try:
        LOCK_FILE.write_text(str(me), encoding="utf-8")
        _lock_owned = True
    except Exception as e:
        print(f"ERROR: no se pudo escribir lock {LOCK_FILE}: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
    atexit.register(release_lock)
    _log(f"Lock adquirido: {LOCK_FILE} (PID {me})")


def release_lock() -> None:
    global _lock_owned
    try:
        if _lock_owned and LOCK_FILE.exists():
            try:
                owner = int(LOCK_FILE.read_text(encoding="utf-8", errors="ignore").strip().split()[0])
            except Exception:
                owner = -1
            if owner == os.getpid():
                LOCK_FILE.unlink()
    except Exception:
        pass
_lock_owned = False

_RE_BOT = re.compile(r"\b(?:bot)?\d{6,12}:[A-Za-z0-9_-]{35,}\b")
_RE_HEX64 = re.compile(r"\b[0-9a-fA-F]{64}\b")
_RE_KV = re.compile(r"(?i)\b(secret|token|password|passwd|api[_-]?key|hmac)\b\s*[:=]\s*\S+")
# --- fin bloque produccion PC ---


def build_ctx(cfg: dict) -> dict:
    def _int(key: str, default: int) -> int:
        try:
            return int(str(cfg.get(key, default)))
        except (TypeError, ValueError):
            return default
    return {
        "roots": C.roots(cfg),
        "apps": C.apps(cfg),
        "commands": C.commands(cfg),
        "shell_timeout": float(cfg.get("SHELL_TIMEOUT", 10)),
        "output_max": int(cfg.get("OUTPUT_MAX", 65536)),
        "trash_dir": cfg.get("TRASH_DIR", "_jarvis_trash"),
        "disk_anchor": (C.roots(cfg) + ["C:\\"])[0],
        "high_max_per_minute": _int("HIGH_MAX_PER_MINUTE", 10),
        "high_max_per_hour": _int("HIGH_MAX_PER_HOUR", 60),
        "kill_file": str(KILL_FILE),
        "session_grants": str(cfg.get("SESSION_GRANTS", "0")),
        "media_volume": str(cfg.get("MEDIA_VOLUME", "0")),
        "files_ext": str(cfg.get("FILES_EXT", "0")),
        "screen_c1": str(cfg.get("SCREEN_C1", "0")),
    }


def _high_limits(ctx: dict) -> tuple:
    """Limites HIGH/minuto y HIGH/hora (defecto 10/60, configurables via .env)."""
    try:
        per_min = int(ctx.get("high_max_per_minute", 10))
    except (TypeError, ValueError):
        per_min = 10
    try:
        per_hour = int(ctx.get("high_max_per_hour", 60))
    except (TypeError, ValueError):
        per_hour = 60
    return per_min, per_hour


def _high_now(ctx: dict) -> float:
    clk = ctx.get("_clock")
    if callable(clk):
        try:
            return float(clk())
        except Exception:
            pass
    return time.time()


def _check_high_limit(ctx: dict, now: float):
    """Sliding-window 60s/3600s. Retorna (ok, espera_s).

    Al permitir, registra `now` en ctx["_high_ts"]. Al denegar NO registra
    (la propia denegacion no consume cuota). Reloj inyectable via
    ctx["_clock"] para tests con tiempo simulado.
    """
    per_min, per_hour = _high_limits(ctx)
    ts = ctx.setdefault("_high_ts", [])
    try:
        # poda: solo interesa la ultima hora
        ts[:] = [t for t in ts if t > now - 3600]
    except Exception:
        pass
    in_min = [t for t in ts if t > now - 60]
    if len(in_min) >= per_min and per_min > 0:
        oldest = min(in_min)
        wait_s = max(1, int(60 - (now - oldest) + 1))
        return False, wait_s
    if len(ts) >= per_hour and per_hour > 0:
        oldest = min(ts) if ts else now
        wait_s = max(1, int(3600 - (now - oldest) + 1))
        return False, wait_s
    if per_min <= 0 or per_hour <= 0:
        return False, 1
    ts.append(now)
    return True, 0


def _is_locked(ctx: dict) -> bool:
    """Bloqueo kill-switch. ctx["_kill_locked"] manda en tests; en
    produccion manda el fichero persistente ctx["kill_file"]/KILL_FILE."""
    if "_kill_locked" in ctx:
        return bool(ctx.get("_kill_locked"))
    try:
        return _ks.is_locked(ctx.get("kill_file", str(KILL_FILE)))
    except Exception:
        return False


def _audit_append(log, name: str, risk: str, result: str,
                  trace_id: str, grant: dict) -> None:
    """Registra en audit.jsonl. La auditoria NUNCA tumba nada: si falla,
    deja AVISO en remote_agent.log y se sigue. log=None = sin auditoria."""
    if log is None:
        return
    try:
        log.append(name, risk, result, trace_id=trace_id,
                   grant_id=(grant or {}).get("grant_id", "-"))
    except Exception as e:
        _log(f"AVISO: audit.append fallo (action {name} trace={trace_id}): "
             f"{type(e).__name__}: {e}")


async def execute_action(manifest: dict, params: dict, grant: dict,
                         ctx: dict, secret: str, used: set,
                         log=None, trace_id: str = "-") -> dict:
    """Ejecuta una accion con politica y la deja auditada.

    El log.append vive AQUI (no en run_once): cualquier llamada directa
    queda registrada igual que la via jr_req. Sin log no hay auditoria.
    """
    action = dict(manifest)
    # shell fuera de allowlist sube a HIGH (evaluado aqui Y en el Core)
    if action["name"] == "shell.exec":
        cmd = str(params.get("cmd", "")).lower()
        if cmd not in ctx.get("commands", []):
            action = dict(action, risk="high")
    # Flags Fase B (todo nuevo APAGADO por defecto): sin flag se deniega
    # con feature_disabled (no se debilita nada existente).
    # Fase 8D: files.write en JARVIS-recibidos baja a LOW (sin
    # confirmacion); en Downloads/Documents sigue MEDIUM (= confirmacion).
    # Rutas y audit intactos: files_write exige containment y todo se audita
    # con el _risk efectivo.
    _aname = action["name"]
    if _aname == "files.write":
        try:
            if _pol.is_inbox_path((params or {}).get("path", ""),
                                  ctx.get("roots", [])):
                action = dict(action, risk="low")
        except Exception:
            pass
    if _aname.startswith(("media.", "volume.")) and \
            str(ctx.get("media_volume", "0")) != "1":
        res = {"status": "error", "executed": False,
               "code": "feature_disabled",
               "error": f"{_aname} apagado por defecto (flag MEDIA_VOLUME=0). "
                        f"NO SE EJECUTO NADA.",
               "_risk": action.get("risk", "?")}
        _audit_append(log, _aname, action.get("risk", "?"), "error",
                      trace_id, grant)
        return res
    if _aname in ("files.mkdir", "files.hash") and \
            str(ctx.get("files_ext", "0")) != "1":
        res = {"status": "error", "executed": False,
               "code": "feature_disabled",
               "error": f"{_aname} apagado por defecto (flag FILES_EXT=0). "
                        f"NO SE EJECUTO NADA.",
               "_risk": action.get("risk", "?")}
        _audit_append(log, _aname, action.get("risk", "?"), "error",
                      trace_id, grant)
        return res
    # Sesion B1: grant con session_id se distingue del grant de un solo uso.
    _is_session = isinstance(grant, dict) and "session_id" in grant
    if _is_session:
        try:
            from remote_agent import session as _sess
        except ImportError:
            import session as _sess
        if str(ctx.get("session_grants", "0")) != "1":
            res = _sess.session_response(False, 0, _aname,
                                         f"sesiones apagadas (flag SESSION_GRANTS=0). "
                                         f"NO SE EJECUTO NADA.",
                                         "feature_disabled")
            res["_risk"] = action.get("risk", "?")
            _audit_append(log, _aname, action.get("risk", "?"), "error",
                          trace_id, grant)
            return res
        if _is_locked(ctx):
            _sess.revoke_session(ctx)
            res = _sess.session_response(False, 0, _aname,
                                         f"BLOQUEADO por kill-switch ({_aname}): "
                                         f"sesion revocada. NO SE EJECUTO NADA.",
                                         "killswitch_locked")
            res["_risk"] = action.get("risk", "?")
            _audit_append(log, _aname, action.get("risk", "?"), "error",
                          trace_id, grant)
            return res
        ok_s, rem_after, why_s = _sess.check_session(secret, grant, _aname,
                                                     ctx)
        try:
            _log(f"session {grant.get('session_id')} accion={_aname} "
                 f"restantes~{rem_after} resultado={'ok' if ok_s else 'error:' + why_s}")
        except Exception:
            pass
        if not ok_s:
            res = _sess.session_response(False, 0, _aname,
                                         f"BLOQUEADO sesion ({_aname}): {why_s}. "
                                         f"NO SE EJECUTO NADA.",
                                         "session_denied")
            res["_risk"] = action.get("risk", "?")
            _audit_append(log, _aname, action.get("risk", "?"), "error",
                          trace_id, grant)
            return res
        # Sesion valida: HIGH sigue con limitador local (no se debilita).
        risk_eff = action.get("risk", "?")
        if risk_eff == "high":
            now = _high_now(ctx)
            allow, wait_s = _check_high_limit(ctx, now)
            if not allow:
                res = _sess.session_response(
                    False, rem_after + 1, _aname,
                    f"limite de acciones HIGH superado; espera {wait_s} s",
                    "high_rate_limited")
                res["_risk"] = risk_eff
                _audit_append(log, _aname, risk_eff, "error", trace_id,
                              grant)
                return res
        try:
            res_action = await asyncio.wait_for(
                action["fn"](params, ctx), timeout=action.get("timeout", 30))
        except asyncio.TimeoutError:
            res_action = {"status": "error", "code": "action_timeout",
                          "error": f"timeout en {_aname}"}
        if res_action.get("status") == "error":
            if not str(res_action.get("error") or "").strip():
                res_action["error"] = (f"error desconocido en {_aname}")
            res_action.setdefault("code", "action_failed")
            try:
                log.append(_aname, action.get("risk", "?"), "error",
                           trace_id=trace_id,
                           grant_id=str(grant.get("session_id", "-")))
            except Exception:
                pass
            res = _sess.session_response(False, rem_after + 1, _aname,
                                         str(res_action.get("error", "")),
                                         str(res_action.get("code", "action_failed")))
            res["_risk"] = action.get("risk", "?")
            return res
        remaining = _sess.consume_session(ctx, grant)
        try:
            log.append(_aname, action.get("risk", "?"), "ok",
                       trace_id=trace_id,
                       grant_id=str(grant.get("session_id", "-")))
        except Exception:
            pass
        res = _sess.session_response(True, remaining, _aname, "", "ok")
        # Propaga campos utiles de la accion (p.ej. level, path) sin romper
        # el formato {status,executed,session_remaining,error,code}.
        for k, v in (res_action or {}).items():
            if k not in res:
                res[k] = v
        res["_risk"] = action.get("risk", "?")
        return res
    risk_eff = action.get("risk", "?")
    # Kill-switch: bloqueado deniega TODA MEDIUM y HIGH (LOW sigue).
    if risk_eff in ("medium", "high") and _is_locked(ctx):
        res = {"status": "error", "executed": False, "code": "killswitch_locked",
               "error": f"BLOQUEADO por kill-switch ({action['name']}): "
                        f"agente en modo bloqueado. NO SE EJECUTO NADA. "
                        f"Se requiere jr_unlock con grant HIGH valido.",
               "_risk": risk_eff}
        _audit_append(log, action["name"], risk_eff, "error", trace_id, grant)
        return res
    ok, why = _pol.evaluate(action, params, grant, ctx, secret, used)
    if not ok:
        # Denegacion HONESTA y anti-alucinacion: el hub/LLM debe propagar
        # ok=false al usuario y jamas afirmar que la accion se realizo.
        res = {"status": "error", "executed": False, "code": "policy_denied",
               "error": f"BLOQUEADO por politica ({action['name']}): {why}. "
                        f"NO SE EJECUTO NADA. Informa al usuario de que NO "
                        f"se realizo y pide confirmacion explicita. "
                        f"PROHIBIDO decir que tuvo exito.",
               "_risk": action.get("risk", "?")}
        _audit_append(log, action["name"], action.get("risk", "?"),
                      "error", trace_id, grant)
        return res
    # Limitador local HIGH: max N/min y M/hora (sliding window).
    if risk_eff == "high":
        now = _high_now(ctx)
        allow, wait_s = _check_high_limit(ctx, now)
        if not allow:
            res = {"status": "error", "executed": False,
                   "code": "high_rate_limited",
                   "error": f"limite de acciones HIGH superado; espera {wait_s} s",
                   "_risk": risk_eff}
            _audit_append(log, action["name"], risk_eff, "error",
                          trace_id, grant)
            return res
    if grant and action.get("risk") == "high":
        used.add(grant.get("grant_id"))
    try:
        res = await asyncio.wait_for(
            action["fn"](params, ctx), timeout=action.get("timeout", 30))
    except asyncio.TimeoutError:
        res = {"status": "error", "code": "action_timeout",
               "error": f"timeout en {action['name']}"}
    # Red de seguridad: NINGUN error sale vacio ni sin codigo, venga de
    # la accion que venga (p. ej. process.terminate con PID inexistente).
    if res.get("status") == "error":
        if not str(res.get("error") or "").strip():
            res["error"] = (f"error desconocido en {action['name']}: "
                            f"la accion fallo sin motivo legible")
        res.setdefault("code", "action_failed")
    # Riesgo EFECTIVO (tras escalado shell->HIGH), no el declarado.
    risk = res.pop("_risk", action.get("risk", "?"))
    _audit_append(log, action["name"], risk, res.get("status", "?"),
                  trace_id, grant)
    res["_risk"] = risk
    return res


async def _play_one_tts(audio: bytes, mime: str) -> dict:
    """Reproduce un audio marcando playing (para barge-in A2)."""
    try:
        V.set_playing(True)
    except Exception:
        pass
    try:
        return await asyncio.to_thread(V.play_audio_bytes, audio, "jrtts",
                                       mime)
    finally:
        try:
            V.set_playing(False)
        except Exception:
            pass


async def _handle_tts(ws, mtype: str, payload: dict, cfg: dict,
                      secret: str, log, assembler, ctr: int) -> int:
    """Reproduce jr_tts / jr_tts_chunk reensamblado y confirma jr_voice_result.

    FASE A4 (detras de TTS_PRIORITY=1): jr_tts admite priority P0/P1/P2.
    P0 interrumpe (cancela actual y suena ya); resto se encola FIFO.
    Con TTS_PRIORITY=0 (defecto): comportamiento viejo (suena ya, cancela).
    """
    use_queue = str((cfg or {}).get("TTS_PRIORITY", "0")) == "1"
    if mtype == "jr_tts_chunk":
        audio, mime, sid, is_final = assembler.add(payload)
        trace = str((payload or {}).get("trace_id") or sid)
        if audio is None:
            if is_final:
                _log(f"Voz: stream {sid} final con huecos, descartado")
            return ctr
        if V._played_key(V.play_key(audio)):
            _log(f"Voz: chunks de audio ya reproducido, sin replay (stream {sid})")
            ctr += 1
            await ws.send(json.dumps(P.make_envelope(
                secret, "jr_voice_result",
                V.make_voice_result_payload(True, False, len(audio), mime,
                                            trace, "duplicado: ya reproducido"),
                ctr)))
            return ctr
    else:
        audio, mime, _text, trace = V.extract_audio(payload)
        if audio is None:
            _log("Voz: jr_tts sin audio decodificable, se ignora")
            return ctr
        V._played_key(V.play_key(audio))  # jr_tts manda: siempre suena
    if use_queue:
        prio = V.tts_priority_of(payload or {})
        if prio == "P0":
            V.tts_enqueue(audio, mime, trace, prio)
            item = V.tts_dequeue()
            audio, mime, trace = item["audio"], item["mime"], item["trace"]
            _log(f"Voz: P0 interrumpe, cola={len(V._TTS_QUEUE)} trace={trace}")
        else:
            qlen = V.tts_enqueue(audio, mime, trace, prio)
            if V.is_playing() or qlen > 1:
                _log(f"Voz: encolado {prio} cola={qlen} trace={trace}")
                ctr += 1
                await ws.send(json.dumps(P.make_envelope(
                    secret, "jr_voice_result",
                    V.make_voice_result_payload(True, False, len(audio),
                                                mime, trace,
                                                f"encolado {prio}"),
                    ctr)))
                return ctr
            item = V.tts_dequeue()
            audio, mime, trace = item["audio"], item["mime"], item["trace"]
    try:
        res = await _play_one_tts(audio, mime)
    except Exception as e:
        res = {"played": False, "bytes": len(audio), "mime": mime,
               "error": f"excepcion reproduciendo: {e}"}
    # Drena cola FIFO (solo modo TTS_PRIORITY=1; P0 ya interrumpio).
    while use_queue and V._TTS_QUEUE and bool(res.get("played")):
        nxt = V.tts_dequeue()
        try:
            res = await _play_one_tts(nxt["audio"], nxt["mime"])
        except Exception as e:
            res = {"played": False, "bytes": 0, "mime": nxt["mime"],
                   "error": f"excepcion reproduciendo: {e}"}
        trace = nxt["trace"]
    ok = bool(res.get("played"))
    _log(f"Voz: {'reproducidos' if ok else 'FALLO reproduccion'} "
         f"{res.get('bytes')} bytes ({res.get('mime')}) trace={trace} "
         f"{res.get('error', '')}".rstrip())
    try:
        log.append("voice.play", "low", "ok" if ok else "error", trace_id=trace)
    except OSError as e:
        # La auditoria nunca debe tumbar la sesion de voz: se registra
        # en remote_agent.log y se sigue con jr_voice_result igualmente.
        _log(f"AVISO: audit.append fallo (voice.play trace={trace}): "
             f"{type(e).__name__}: {e}")
    ctr += 1
    await ws.send(json.dumps(P.make_envelope(
        secret, "jr_voice_result",
        V.make_voice_result_payload(ok, ok, int(res.get("bytes", 0)),
                                    str(res.get("mime", "")), trace,
                                    str(res.get("error", ""))), ctr)))
    return ctr


async def _recv_or_stop(ws, stop, timeout: float):
    """Espera un mensaje, el evento stop o el timeout (None en ambos casos).

    ConnectionClosed se propaga (el llamador reconecta con backoff).
    """
    recv_task = asyncio.create_task(ws.recv())
    if stop is None:
        try:
            return await asyncio.wait_for(recv_task, timeout=timeout)
        except asyncio.TimeoutError:
            return None
    stop_task = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait({recv_task, stop_task}, timeout=timeout,
                                     return_when=asyncio.FIRST_COMPLETED)
    except Exception:
        recv_task.cancel()
        stop_task.cancel()
        raise
    if stop_task in done:
        recv_task.cancel()
        return None
    stop_task.cancel()
    if recv_task in done:
        return recv_task.result()  # puede lanzar ConnectionClosed: reconectar
    recv_task.cancel()
    return None


async def _handle_killswitch(ws, payload: dict, secret: str, ctx: dict,
                             used: set, log, ctr: int) -> int:
    """jr_killswitch firmado (HMAC del canal): bloquea MEDIUM+HIGH.

    Invalida grants pendientes en la practica: mientras bloqueado toda
    MEDIUM/HIGH se deniega aunque el grant sea valido. `used` se conserva
    (jamas se permite reutilizar). Persiste en kill_file. LOW sigue.
    NO mata procesos ni apaga nada. Responde jr_res.
    """
    trace = str((payload or {}).get("trace_id") or "-")
    kill_path = ctx.get("kill_file", str(KILL_FILE))
    try:
        _ks.set_locked(kill_path, True, trace)
    except Exception as e:
        _log(f"AVISO: kill-switch no pudo persistir bloqueo: {e}")
    try:
        from remote_agent import session as _sess2
    except ImportError:
        try:
            import session as _sess2
        except ImportError:
            _sess2 = None
    try:
        if _sess2 is not None:
            _sess2.revoke_session(ctx)
    except Exception:
        pass
    _log(f"Kill-switch ACTIVADO trace={trace} "
         f"(MEDIUM/HIGH denegados, LOW sigue; grants pendientes invalidos)")
    try:
        log.append("agent.killswitch", "high", "ok", trace_id=trace)
    except OSError as e:
        _log(f"AVISO: audit.append fallo (agent.killswitch trace={trace}): "
             f"{type(e).__name__}: {e}")
    ctr += 1
    await ws.send(json.dumps(P.make_envelope(
        secret, "jr_res",
        {"ok": True,
         "result": {"status": "ok", "locked": True,
                    "message": "kill-switch activado: MEDIUM/HIGH bloqueados"},
         "trace_id": trace}, ctr)))
    return ctr


async def _handle_unlock(ws, payload: dict, secret: str, ctx: dict,
                         used: set, log, ctr: int) -> int:
    """jr_unlock firmado (HMAC) + grant HIGH de un solo uso para agent.unlock.

    Sin grant valido se deniega (y se audita). Con grant valido restaura.
    Responde jr_res.
    """
    trace = str((payload or {}).get("trace_id") or "-")
    grant = (payload or {}).get("grant")
    if not grant:
        why = "unlock sin grant HIGH de un solo uso"
        _log(f"Kill-switch unlock DENEGADO trace={trace}: {why}")
        try:
            log.append("agent.unlock", "high", "error", trace_id=trace)
        except OSError as e:
            _log(f"AVISO: audit.append fallo (agent.unlock trace={trace}): "
                 f"{type(e).__name__}: {e}")
        ctr += 1
        await ws.send(json.dumps(P.make_envelope(
            secret, "jr_res",
            {"ok": False,
             "result": {"status": "error", "executed": False, "locked": True,
                        "code": "unlock_denied",
                        "error": f"unlock denegado: {why}"},
             "trace_id": trace}, ctr)))
        return ctr
    ok, why = P.check_grant(secret, grant, UNLOCK_ACTION, {}, used)
    if not ok:
        _log(f"Kill-switch unlock DENEGADO trace={trace}: {why}")
        try:
            log.append("agent.unlock", "high", "error", trace_id=trace,
                       grant_id=grant.get("grant_id", "-"))
        except OSError as e:
            _log(f"AVISO: audit.append fallo (agent.unlock trace={trace}): "
                 f"{type(e).__name__}: {e}")
        ctr += 1
        await ws.send(json.dumps(P.make_envelope(
            secret, "jr_res",
            {"ok": False,
             "result": {"status": "error", "executed": False, "locked": True,
                        "code": "unlock_denied",
                        "error": f"unlock denegado: {why}"},
             "trace_id": trace}, ctr)))
        return ctr
    used.add(grant.get("grant_id"))
    kill_path = ctx.get("kill_file", str(KILL_FILE))
    try:
        _ks.set_locked(kill_path, False, trace)
    except Exception as e:
        _log(f"AVISO: kill-switch no pudo persistir desbloqueo: {e}")
    _log(f"Kill-switch DESACTIVADO trace={trace} (grant {grant.get('grant_id')})")
    try:
        log.append("agent.unlock", "high", "ok", trace_id=trace,
                   grant_id=grant.get("grant_id", "-"))
    except OSError as e:
        _log(f"AVISO: audit.append fallo (agent.unlock trace={trace}): "
             f"{type(e).__name__}: {e}")
    ctr += 1
    await ws.send(json.dumps(P.make_envelope(
        secret, "jr_res",
        {"ok": True,
         "result": {"status": "ok", "locked": False,
                    "message": "kill-switch desactivado: operativa restaurada"},
         "trace_id": trace}, ctr)))
    return ctr


async def run_once(cfg: dict, stop=None) -> str:
    """Una sesion: conecta, autentica, sirve. Retorna motivo de salida."""
    secret = cfg.get("SECRET", "")
    device = cfg.get("DEVICE_ID", "")
    if not secret or not device:
        _log("ERROR: falta DEVICE_ID/SECRET (.env incompleto), sin intentar conectar")
        return "falta DEVICE_ID/SECRET"
    ctx = build_ctx(cfg)
    _audit_path = Path(str(cfg.get("AUDIT_LOG", "audit.jsonl")))
    if not _audit_path.is_absolute():
        _audit_path = PROJECT_ROOT / _audit_path
    log = _audit.AuditLog(_audit_path, side="agent")
    used: set = set()
    guard = P.ChannelGuard(secret)
    ctr = 0
    uri = f"ws://{cfg.get('HUB_HOST', '127.0.0.1')}:{cfg.get('HUB_PORT', '18765')}"
    async with connect(uri, max_size=2 * 1024 * 1024) as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=15)
        hello = json.loads(raw)
        if hello.get("type") != "jr_hello":
            _log("ERROR: hello inesperado del hub, reconectando")
            return "hello inesperado"
        await ws.send(json.dumps(P.make_auth(secret, hello["nonce"], device)))
        raw = await asyncio.wait_for(ws.recv(), timeout=15)
        if json.loads(raw).get("type") != "jr_welcome":
            _log(f"AUTH RECHAZADO por el hub ({cfg.get('HUB_HOST')}:{cfg.get('HUB_PORT')})")
            return "auth rechazado"
        _log(f"Conectado y autenticado como '{device}' en {cfg.get('HUB_HOST')}:{cfg.get('HUB_PORT')}")
        try:
            if _ks.is_locked(ctx.get("kill_file", str(KILL_FILE))):
                _log("Kill-switch: estado persistente BLOQUEADO "
                     "(MEDIUM/HIGH denegados hasta jr_unlock con grant)")
        except Exception:
            pass
        assembler = V.ChunkAssembler()
        mic_q = None
        shadow_on = str(cfg.get("VOICE_SHADOW", "0")) == "1"
        if shadow_on:
            for d in V.describe_downloads():
                _log(f"VOICE_SHADOW descarga: {d['name']} "
                     f"{'presente' if d['present'] else 'AUSENTE'} "
                     f"size={d['size_bytes']}")
            V.start_shadow_stt(cfg, log_fn=_log)
            _log("VOICE_SHADOW: sombra activa (SOLO local, sin envios, "
                 "sin guardar audio; mic compartido con mic_bridge, "
                 "sin duplicar envios)")
        if str(cfg.get("VOICE_IN", "0")) == "1" and not shadow_on:
            import queue as _q
            mic_q = _q.Queue()
            V.start_mic_stt(cfg, mic_q, log_fn=_log)
            if str(cfg.get("VOICE_WAKE", "0")) == "1":
                _log("VOICE_IN vivo wake-gated (Hey Jarvis -> envia "
                     "jr_voice_text al hub; sin wake no se envia nada)")
            else:
                _log("VOICE_IN vivo VAD libre (sin wake: envia todo lo oido)")
        elif str(cfg.get("VOICE_IN", "0")) == "1" and shadow_on:
            _log("VOICE_SHADOW: VOICE_IN=1 ignorado (sombra no envia; "
                 "mic_bridge sigue dueno, sin duplicar envios)")
        else:
            _log("Voz: solo salida TTS + outbox manual (VOICE_IN=0, microfono intacto)")
        presence_on = str(cfg.get("PRESENCE", "0")) == "1"
        last_presence = None
        import time as _tmod
        next_presence = _tmod.time() + 30
        while True:
            if stop is not None and stop.is_set():
                return "stop"
            for text, source in ([(t, "manual") for t in V.drain_outbox()]
                                 + [(t, "stt") for t in V.drain_queue(mic_q)]):
                if not text.strip():
                    continue
                ctr += 1
                await ws.send(json.dumps(P.make_envelope(
                    secret, "jr_voice_text",
                    V.make_voice_text_payload(text, source), ctr)))
                _log(f"jr_voice_text enviado ({len(text)} chars, {source}): {text[:80]}")
            if presence_on and _pr is not None:
                try:
                    cur = _pr.make_presence_payload()
                    if _tmod.time() >= next_presence or \
                            _pr.changed(last_presence, cur):
                        ctr += 1
                        await ws.send(json.dumps(P.make_envelope(
                            secret, "jr_presence", cur, ctr)))
                        last_presence = cur
                        next_presence = _tmod.time() + 30
                except Exception:
                    pass
            raw = await _recv_or_stop(ws, stop, timeout=30)
            if raw is None:  # stop solicitado o timeout de keepalive
                if stop is not None and stop.is_set():
                    return "stop"
                ctr += 1
                await ws.send(json.dumps(
                    P.make_envelope(secret, "jr_ping", {}, ctr)))
                continue
            try:
                env = json.loads(raw)
            except ValueError:
                continue
            if env.get("type") == "jr_ping":
                ctr += 1
                await ws.send(json.dumps(
                    P.make_envelope(secret, "jr_pong", {}, ctr)))
                continue
            mtype = env.get("type")
            if mtype in ("jr_tts", "jr_tts_chunk"):
                ok, why = guard.check(env)
                if not ok:
                    continue  # firma/ts/ctr invalidos: se ignoran en silencio
                ctr = await _handle_tts(ws, mtype, env["payload"], cfg,
                                        secret, log, assembler, ctr)
                continue
            if mtype == "jr_killswitch":
                ok, why = guard.check(env)
                if not ok:
                    continue  # replay/firma/ts/ctr invalidos: se ignoran
                ctr = await _handle_killswitch(ws, env["payload"], secret,
                                               ctx, used, log, ctr)
                continue
            if mtype == "jr_unlock":
                ok, why = guard.check(env)
                if not ok:
                    continue
                ctr = await _handle_unlock(ws, env["payload"], secret,
                                           ctx, used, log, ctr)
                continue
            if mtype != "jr_req":
                continue
            ok, why = guard.check(env)
            if not ok:
                continue  # replay/firma/ts/ctr invalidos: se ignoran en silencio
            p = env["payload"]
            manifest = A.BY_NAME.get(p.get("action", ""))
            trace = p.get("trace_id", "-")
            if manifest is None:
                res = {"status": "error", "executed": False,
                       "code": "unknown_action",
                       "error": f"accion desconocida '{p.get('action', '')}'. "
                                f"NO SE EJECUTO NADA. PROHIBIDO afirmar exito."}
                _audit_append(log, p.get("action", "?"), "-", "error",
                              trace, p.get("grant"))
            else:
                res = await execute_action(manifest, p.get("params", {}),
                                           p.get("grant"), ctx, secret, used,
                                           log=log, trace_id=trace)
                # Riesgo EFECTIVO ya auditado dentro; se retira del payload.
                res.pop("_risk", None)
            ctr += 1
            await ws.send(json.dumps(P.make_envelope(
                secret, "jr_res",
                {"ok": res.get("status") == "ok", "result": res,
                 "trace_id": trace}, ctr)))


async def run_forever(cfg: dict, stop=None) -> None:
    base = float(cfg.get("BACKOFF_BASE", 1.0))
    cap = float(cfg.get("BACKOFF_MAX", 30.0))
    delay = base
    while True:
        if stop is not None and stop.is_set():
            return
        try:
            why = await run_once(cfg, stop)
            if why == "stop":
                return
        except Exception as e:
            why = f"excepcion {type(e).__name__}: {e}"
        _log(f"Sesion terminada ({why}), reintentando en {delay:.0f}s")
        await asyncio.sleep(delay)
        delay = min(cap, delay * 2 if delay else base)


def main() -> int:
    cfg = C.load()
    acquire_lock()
    _log(f"Arranque remote_agent PID={os.getpid()} device='{cfg.get('DEVICE_ID')}' "
         f"hub={cfg.get('HUB_HOST')}:{cfg.get('HUB_PORT')}")
    try:
        asyncio.run(run_forever(cfg))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
