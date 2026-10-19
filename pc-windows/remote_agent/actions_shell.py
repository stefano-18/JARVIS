"""Accion shell.exec. SIN shell=True, argumentos en lista.

Allowlist de comandos solo-lectura = LOW; cualquier otro = HIGH (concesion).
Timeout configurable, salida maxima 64 KB, devuelve stdout/stderr/exit_code.
"""
import subprocess


def _err(code: str, msg: str, **extra) -> dict:
    """Error honesto: texto nunca vacio + codigo estable."""
    msg = (msg or "").strip() or f"error desconocido ({code})"
    d = {"status": "error", "error": msg[:300], "code": code}
    d.update(extra)
    return d


async def shell_exec(params: dict, ctx: dict) -> dict:
    cmd = params.get("cmd")
    args = params.get("args", [])
    if not isinstance(cmd, str) or not cmd:
        return _err("invalid_cmd", "cmd invalido")
    if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
        return _err("invalid_args", "args debe ser lista de strings")
    # Sin shell=True: el primer token es el ejecutable, el resto args literales.
    # Caracteres como ; && | viajan como argumento, nunca se interpretan.
    cap = int(ctx.get("output_max", 65536))
    timeout = float(params.get("timeout", ctx.get("shell_timeout", 10)))
    try:
        r = subprocess.run([cmd] + args, capture_output=True, text=True,
                           timeout=timeout, shell=False)
        out, err = r.stdout or "", r.stderr or ""
        trunc = len(out) > cap or len(err) > cap
        return {"status": "ok", "stdout": out[:cap], "stderr": err[:cap],
                "exit_code": r.returncode, "truncated": trunc}
    except subprocess.TimeoutExpired:
        return _err("exec_timeout", f"timeout {timeout}s")
    except FileNotFoundError:
        return _err("command_not_found", f"comando no encontrado: {cmd}")
    except Exception as e:
        return _err("exec_failed", f"ejecucion fallo: {e}")
