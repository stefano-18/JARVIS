"""Acciones apps.* Solo allowlist de config. Abrir/cerrar (MEDIUM).

Propiedad por INSTANTANEAS (sesion), no por PID del lanzador: en apps de
instancia unica (Antigravity, Spotify, Electron, Notepad/Calc modernos) el
lanzador sale en ms tras pasar el control a la instancia existente, asi que
su PID no demuestra nada.
- apps.open: instantanea antes (PID, nombre, padre, creacion) de las
  imagenes conocidas -> lanza -> estabiliza hasta _SETTLE_TIMEOUT ->
  instantanea despues. Procesos NUEVOS vivos = lo que abrimos (solo las
  raices del arbol, no los hijos sueltos): owned:true, was_running:false.
  Sin nada nuevo (solo se enfoco lo existente): owned:false,
  was_running:true, sin registrar nada.
- apps.close: con registro propio, taskkill /PID <pid> /T /F solo sobre
  esos PIDs verificando la imagen. Sin registro: rechazo, salvo
  force=true que cierra por imagen EXACTA del alias (nunca otra variante)
  e informa de cuantos procesos mato.
- Alias "antigravity" y "antigravity ide" comparten canon "antigravity".
"""
import asyncio
import subprocess
import sys
import time

# Alias canonicos: misma app, mismo slot de propiedad.
_CANON = {
    "antigravity": "antigravity",
    "antigravity ide": "antigravity",
}

# Imagenes conocidas por canon (snapshot + validacion). El force usa
# SIEMPRE la imagen exacta del alias pedido, nunca esta expansion.
_KNOWN_IMAGES = {
    "antigravity": {"antigravity ide.exe", "antigravity.exe"},
    "spotify": {"spotify.exe"},
    "notepad": {"notepad.exe"},
    "calc": {"calc.exe", "calculatorapp.exe"},
    "rustdesk": {"rustdesk.exe"},
}

_SETTLE_TIMEOUT = 5.0
_SETTLE_POLL = 0.5

_NOT_FOUND_WIN = 128
_NOT_FOUND_POSIX = 1


def _err(code: str, msg: str, **extra) -> dict:
    """Error honesto: texto nunca vacio + codigo estable."""
    msg = (msg or "").strip() or f"error desconocido ({code})"
    d = {"status": "error", "error": msg[:300], "code": code}
    d.update(extra)
    return d


def _norm(app) -> str:
    return str(app or "").strip().lower()


def _canon(app) -> str:
    return _CANON.get(_norm(app), _norm(app))


def _exe_of_target(target) -> str:
    exe = target[0] if isinstance(target, list) else target
    exe = str(exe).split("\\")[-1].split("/")[-1].strip()
    if not exe.lower().endswith(".exe"):
        exe = exe + ".exe"
    return exe


def _known_exes(canon: str, expected: str) -> set:
    known = _KNOWN_IMAGES.get(canon)
    if known:
        return {e.lower() for e in known}
    return {expected.strip().lower()}


def _owned_store(ctx: dict) -> dict:
    try:
        store = ctx.get("_owned")
        if not isinstance(store, dict):
            store = {}
            ctx["_owned"] = store
        return store
    except Exception:
        return {}


def _is_force(params: dict) -> bool:
    v = (params or {}).get("force", False)
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v == 1
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return False


def _lookup_target(app_req: str, ctx: dict):
    apps = ctx.get("apps", {}) or {}
    t = apps.get(app_req)
    if t is None:
        t = apps.get(_canon(app_req))
    return t


def _snapshot(exes: set) -> dict:
    """{pid: {name, ppid, created}} de las imagenes dadas. Mockeable.

    exes en minusculas. En Windows via WMI (PPID + CreationDate reales);
    en POSIX via ps. Si falla, {} (el llamador decide el fallback).
    """
    want = {str(e).lower() for e in (exes or set())}
    if not want:
        return {}
    out = {}
    try:
        if sys.platform == "win32":
            import json
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process | "
                 "Select-Object ProcessId,Name,ParentProcessId,"
                 "CreationDate | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=15)
            data = (r.stdout or "").strip()
            if not data:
                return {}
            rows = json.loads(data)
            if isinstance(rows, dict):
                rows = [rows]
            for row in rows:
                try:
                    name = str(row.get("Name") or "")
                    if name.lower() not in want:
                        continue
                    pid = int(row.get("ProcessId"))
                    out[pid] = {
                        "name": name,
                        "ppid": int(row.get("ParentProcessId") or 0),
                        "created": str(row.get("CreationDate") or ""),
                    }
                except (ValueError, TypeError):
                    continue
            return out
        r = subprocess.run(["ps", "-eo", "pid=,ppid=,lstart=,comm="],
                           capture_output=True, text=True, timeout=15)
        for line in (r.stdout or "").splitlines():
            p = line.strip().split(None, 3)
            if len(p) != 4:
                continue
            try:
                name = p[3].split("/")[-1]
                if name.lower() not in want:
                    continue
                out[int(p[0])] = {"name": name, "ppid": int(p[1]),
                                  "created": p[2]}
            except (ValueError, TypeError):
                continue
        return out
    except Exception:
        return {}


async def _settle(exes: set, launcher_pid: int) -> dict:
    """Espera a que el lanzamiento se estabilice (muerto el lanzador y
    conjunto de PIDs estable) o hasta _SETTLE_TIMEOUT. Devuelve la ultima
    instantanea."""
    last = None
    stable = 0
    cur = {}
    t0 = time.monotonic()
    while True:
        try:
            cur = _snapshot(exes)
        except Exception:
            cur = {}
        try:
            launcher_dead = _pid_image(launcher_pid) is None
        except Exception:
            launcher_dead = True
        key = frozenset(cur.keys())
        if key == last:
            stable += 1
        else:
            stable = 0
        last = key
        if (launcher_dead and stable >= 1) or \
                (time.monotonic() - t0 >= _SETTLE_TIMEOUT):
            break
        await asyncio.sleep(_SETTLE_POLL)
    return cur


def _pid_image(pid: int):
    """Nombre de imagen del pid o None si no existe. Mockeable en tests."""
    try:
        pid = int(pid)
    except Exception:
        return None
    if pid <= 0:
        return None
    try:
        if sys.platform == "win32":
            r = subprocess.run(
                ["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10)
            import csv
            import io
            for row in csv.DictReader(
                    io.StringIO("Image Name,PID\n" + (r.stdout or ""))):
                try:
                    if int(row.get("PID")) == pid:
                        name = (row.get("Image Name") or "").strip()
                        return name or None
                except (ValueError, TypeError):
                    continue
            return None
        r = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)],
                           capture_output=True, text=True, timeout=10)
        name = (r.stdout or "").strip().splitlines()
        if name and name[0].strip():
            return name[0].strip().split("/")[-1]
        return None
    except Exception:
        return None


def _exe_match(canon: str, expected: str, actual: str) -> bool:
    if not actual:
        return False
    a = actual.strip().lower()
    e = (expected or "").strip().lower()
    if a == e:
        return True
    known = _KNOWN_IMAGES.get(canon)
    if known and a in known and e in known:
        return True
    return False


def _owned_pids(entry: dict) -> list:
    try:
        pids = entry.get("pids")
        if isinstance(pids, list):
            return [int(p) for p in pids if int(p) > 0]
        if "pid" in entry and entry.get("pid"):
            return [int(entry["pid"])]
    except Exception:
        pass
    return []


async def apps_open(params: dict, ctx: dict) -> dict:
    """Abre y determina propiedad por instantaneas.

    Nuevo (owned:true, was_running:false, pids=[raices nuevas]) o ya
    estaba abierto (owned:false, was_running:true, pids:[], sin registro).
    """
    app_req = _norm(params.get("app", ""))
    target = _lookup_target(app_req, ctx)
    if not target:
        return _err("app_not_allowed", "app fuera de allowlist",
                    app=app_req, owned=False, was_running=False, pids=[])
    canon = _canon(app_req)
    expected = _exe_of_target(target)
    exes = _known_exes(canon, expected)
    try:
        before = _snapshot(exes)
        before_ok = True
    except Exception:
        before, before_ok = {}, False
    try:
        if isinstance(target, list):
            proc = subprocess.Popen(target)
        elif sys.platform == "win32" and str(target).lower().endswith(
                (".exe", ".bat", ".cmd")):
            proc = subprocess.Popen([target])
        else:
            proc = subprocess.Popen(target, shell=False)
        launcher = int(getattr(proc, "pid", 0) or 0)
    except Exception as e:
        return _err("launch_failed", f"no se pudo lanzar {app_req}: {e}",
                    app=app_req, owned=False, was_running=False, pids=[])
    try:
        after = await _settle(exes, launcher)
    except Exception:
        after = {}
    if before_ok:
        new = {p: info for p, info in (after or {}).items()
               if p not in before}
    else:
        new = {}
    new_ids = set(new)
    alive = set()
    for p in new_ids:
        try:
            img = _pid_image(p)
        except Exception:
            img = None
        if img and img.strip().lower() in exes:
            alive.add(p)
    roots = sorted(p for p in alive
                   if int(new[p].get("ppid", 0)) not in new_ids)
    if roots:
        try:
            _owned_store(ctx)[canon] = {"pids": roots, "exe": expected,
                                        "app": app_req}
        except Exception:
            pass
        return {"status": "ok", "app": app_req, "owned": True,
                "was_running": False, "pids": roots}
    if launcher > 0:
        try:
            limg = _pid_image(launcher)
        except Exception:
            limg = None
        if limg and limg.strip().lower() in exes:
            # Sin instantanea fiable pero el lanzador sigue vivo y es la
            # imagen esperada: propiedad sobre el (fallback conservador).
            try:
                _owned_store(ctx)[canon] = {"pids": [launcher],
                                            "exe": expected, "app": app_req}
            except Exception:
                pass
            return {"status": "ok", "app": app_req, "owned": True,
                    "was_running": False, "pids": [launcher]}
    return {"status": "ok", "app": app_req, "owned": False,
            "was_running": True, "pids": []}


async def apps_close(params: dict, ctx: dict) -> dict:
    """Cierra EXACTAMENTE los PIDs propios (taskkill /PID <pid> /T /F).

    Sin registro: rechazo (closed:false, owned:false) salvo force=true,
    que cierra por imagen EXACTA del alias y cuenta cuantos mato.
    Todo resultado incluye killed_pids.
    """
    app_req = _norm(params.get("app", ""))
    target = _lookup_target(app_req, ctx)
    if not target:
        return _err("app_not_allowed", "app fuera de allowlist",
                    closed=False, owned=False, app=app_req, killed_pids=[])
    canon = _canon(app_req)
    store = _owned_store(ctx)
    entry = store.get(canon)
    force = _is_force(params or {})
    not_found = _NOT_FOUND_WIN if sys.platform == "win32" else _NOT_FOUND_POSIX

    if entry:
        pids = _owned_pids(entry)
        expected = str(entry.get("exe", "") or _exe_of_target(target))
        if not pids:
            store.pop(canon, None)
            return _err("corrupt_registry",
                        "registro de apertura corrupto; nada que cerrar.",
                        closed=False, owned=True, app=app_req,
                        exit_code=not_found, killed_pids=[])
        killed, last_code, last_detail = [], not_found, ""
        for pid in pids:
            try:
                actual = _pid_image(pid)
            except Exception:
                actual = None
            if actual is None:
                continue
            if not _exe_match(canon, expected, actual):
                continue
            try:
                if sys.platform == "win32":
                    r = subprocess.run(["taskkill", "/PID", str(pid),
                                        "/T", "/F"],
                                       capture_output=True, text=True,
                                       timeout=15)
                else:
                    r = subprocess.run(["kill", str(pid)],
                                       capture_output=True, text=True,
                                       timeout=15)
            except Exception as e:
                last_detail = str(e)[:200]
                continue
            last_code = r.returncode
            last_detail = ((r.stderr or r.stdout) or "").strip()[:200]
            if r.returncode == 0:
                killed.append(pid)
        remaining = []
        for pid in pids:
            if pid in killed:
                continue
            try:
                actual = _pid_image(pid)
            except Exception:
                actual = None
            if actual and _exe_match(canon, expected, actual):
                remaining.append(pid)
        if not remaining:
            store.pop(canon, None)
            if killed:
                return {"status": "ok", "closed": True, "owned": True,
                        "app": app_req, "exit_code": 0,
                        "killed_pids": sorted(killed),
                        "message": f"{app_req} cerrada "
                                   f"({len(killed)} proceso(s): "
                                   f"{sorted(killed)}, arbol /T)."}
            return _err("already_gone",
                        "lo que abri ya no esta en ejecucion: "
                        "nada que cerrar.",
                        closed=False, owned=True, app=app_req,
                        exit_code=not_found, killed_pids=[])
        try:
            store[canon] = {"pids": sorted(remaining), "exe": expected,
                            "app": str(entry.get("app", app_req))}
        except Exception:
            pass
        return _err("close_failed",
                    f"no se pudo cerrar del todo {app_req} "
                    f"(exit {last_code}): {last_detail}. Siguen vivos "
                    f"{sorted(remaining)} (verificalo). NO digas que "
                    f"se cerro.",
                    closed=False, owned=True, app=app_req,
                    exit_code=last_code, killed_pids=sorted(killed))

    if not force:
        return _err("not_owned",
                    "no la abri yo; confirmacion necesaria. "
                    "Reenvia con force=true tras confirmar con el "
                    "usuario. No se cerro nada.",
                    closed=False, owned=False, app=app_req, killed_pids=[])
    # force=true: SOLO la imagen exacta del alias pedido, nunca otra
    # variante del mismo nombre.
    apps = ctx.get("apps", {}) or {}
    exact_target = apps.get(app_req)
    if exact_target is None:
        exact_target = target
    exe = _exe_of_target(exact_target)
    try:
        before = _snapshot({exe.lower()})
    except Exception:
        before = {}
    try:
        if sys.platform == "win32":
            r = subprocess.run(["taskkill", "/IM", exe, "/F"],
                               capture_output=True, text=True, timeout=15)
        else:
            r = subprocess.run(["pkill", "-f", exe],
                               capture_output=True, text=True, timeout=15)
    except Exception as e:
        return _err("close_failed",
                    f"no se pudo intentar el cierre de {app_req}: "
                    f"{str(e)[:200]}",
                    closed=False, owned=False, app=app_req, killed_pids=[])
    code = r.returncode
    detail = ((r.stderr or r.stdout) or "").strip()[:200]
    try:
        after = _snapshot({exe.lower()})
    except Exception:
        after = {}
    killed = sorted(p for p in (before or {}) if p not in (after or {}))
    if code == 0 or killed:
        return {"status": "ok", "closed": True, "owned": False,
                "app": app_req, "exit_code": 0,
                "killed_pids": killed,
                "message": f"{app_req} cerrada por imagen exacta {exe} "
                           f"con force ({len(killed)} proceso(s))."}
    if code == not_found:
        return _err("already_gone",
                    f"{app_req} no estaba en ejecucion (exit {code}): "
                    f"nada que cerrar." + (f" {detail}" if detail else ""),
                    closed=False, owned=False, app=app_req,
                    exit_code=code, killed_pids=[])
    return _err("close_failed",
                f"no se pudo cerrar {app_req} (exit {code}): "
                f"{detail}. Sigue en ejecucion (verificalo). "
                f"NO digas que se cerro.",
                closed=False, owned=False, app=app_req,
                exit_code=code, killed_pids=killed)
