"""Acciones process.* listar/info LOW; terminar HIGH (concesion).

Contrato de errores: todo dict con status error lleva SIEMPRE `error`
(texto legible, jamas vacio) y `code` (maquina-legible)."""

import csv
import io
import os
import re
import subprocess
import sys


def _err(code: str, msg: str, **extra) -> dict:
    """Error honesto: texto nunca vacio + codigo estable."""
    msg = (msg or "").strip() or f"error desconocido ({code})"
    d = {"status": "error", "error": msg[:300], "code": code}
    d.update(extra)
    return d


def _parse_tasklist(csv_text: str) -> list:
    out = []
    try:
        for row in csv.DictReader(io.StringIO(csv_text)):
            try:
                # tasklist informa "6,976 KB" / "8 KB": quedarse solo con
                # digitos (el "B" colgante hacia int() fallar y vaciaba top).
                raw = row.get("Mem Usage", "")
                digits = re.sub(r"[^\d]", "", raw or "")
                mem = int(digits) if digits else 0
                out.append({"name": row.get("Image Name"), "pid": int(row.get("PID")),
                            "ram_kb": mem})
            except (ValueError, TypeError):
                continue
    except Exception:
        pass
    return out


async def process_list(params: dict, ctx: dict) -> dict:
    try:
        if sys.platform == "win32":
            r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                               capture_output=True, text=True, timeout=15)
            procs = _parse_tasklist("Image Name,PID,Session Name,Session#,Mem Usage\n" + r.stdout)
        else:
            r = subprocess.run(["ps", "-eo", "pid,comm,rss"],
                               capture_output=True, text=True, timeout=15)
            procs = []
            for line in r.stdout.splitlines()[1:]:
                p = line.split()
                if len(p) == 3:
                    procs.append({"name": p[1], "pid": int(p[0]), "ram_kb": int(p[2])})
        procs.sort(key=lambda x: x["ram_kb"], reverse=True)
        return {"status": "ok", "top": procs[: int(params.get("limit", 10))]}
    except Exception as e:
        return _err("list_failed", f"listar procesos fallo: {e}")


async def process_info(params: dict, ctx: dict) -> dict:
    try:
        pid = int(params.get("pid"))
    except (TypeError, ValueError):
        return _err("invalid_pid", "pid invalido")
    res = await process_list({"limit": 4096}, ctx)
    if res.get("status") != "ok":
        return res
    for p in res["top"]:
        if p["pid"] == pid:
            return {"status": "ok", "process": p}
    return _err("pid_not_found", "pid no encontrado")


async def process_terminate(params: dict, ctx: dict) -> dict:
    try:
        pid = int(params.get("pid"))
    except (TypeError, ValueError):
        return _err("invalid_pid", "pid invalido")
    if pid in (0, 1) or pid == os.getpid():
        return _err("protected_pid", "pid protegido")
    try:
        if sys.platform == "win32":
            r = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return {"status": "ok", "pid": pid}
            detail = ((r.stderr or r.stdout) or "").strip()
            low = detail.lower()
            if r.returncode == 128 or "no se encontr" in low or "not found" in low:
                return _err("pid_not_found",
                            f"pid no encontrado ({pid})"
                            + (f": {detail}" if detail else ""),
                            pid=pid, exit_code=r.returncode)
            if "denegado" in low or "denied" in low or "acceso" in low:
                return _err("access_denied",
                            f"acceso denegado al terminar pid {pid}"
                            + (f": {detail}" if detail else ""),
                            pid=pid, exit_code=r.returncode)
            return _err("terminate_failed",
                        f"no se pudo terminar pid {pid} "
                        f"(exit={r.returncode})"
                        + (f": {detail}" if detail else
                           ": el SO rechazo la operacion"),
                        pid=pid, exit_code=r.returncode)
        else:
            os.kill(pid, 15)
            return {"status": "ok", "pid": pid}
    except ProcessLookupError:
        return _err("pid_not_found", f"pid no encontrado ({pid})", pid=pid)
    except PermissionError:
        return _err("access_denied",
                    f"acceso denegado al terminar pid {pid}", pid=pid)
    except Exception as e:
        return _err("terminate_failed",
                    f"no se pudo terminar pid {pid}: {e}", pid=pid)
