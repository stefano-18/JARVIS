"""check_boot.py — Diagnostico de arranque de jarvis2 + jarvis-v2-fijo.

SOLO LECTURA: no arranca, no para, no modifica nada (solo escribe
boot_report.txt junto a este script). Uso: doble clic en check_boot.bat
o `python scripts\\check_boot.py` desde remote_agent.

Comprueba:
  * procesos Jarvis (agent.py, main.py, mic_bridge.py): interprete y consola,
  * conexiones TCP a 8765 (hub viejo) y 18765 (hub jarvis2),
  * killswitch.json (bloqueado/desbloqueado),
  * audit.verify() de remote_agent (solo lectura),
  * que haya exactamente 1 agent.py, 1 main.py y 1 mic_bridge,
  * locks con PID verificado (agent.lock, main.lock, mic_bridge.lock).
Veredicto OK/KO en boot_report.txt y por consola. Sin secretos.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REMOTE_AGENT = HERE.parent
VIEJO = Path(r"{{WIN_HOME}}\jarvis-v2-fijo")
REPORT = HERE / "boot_report.txt"

OLD_PORT = 8765
NEW_PORT = 18765

_RE_TG = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")
_RE_KV = re.compile(r"(?i)\b(secret|token|password|passwd|api[_-]?key|hmac)\b\s*[:=]\s*\S+")

_TCP_STATES = {"1": "Closed", "2": "Listen", "3": "SynSent", "4": "SynReceived",
               "5": "Established", "6": "FinWait1", "7": "FinWait2",
               "8": "CloseWait", "9": "Closing", "10": "LastAck",
               "11": "TimeWait", "12": "DeleteTCB"}


def _canon_state(s) -> str:
    t = str(s or "").strip()
    if t in _TCP_STATES:
        return _TCP_STATES[t]
    for name in _TCP_STATES.values():
        if t.lower() == name.lower():
            return name
    return t or "?"


def _redact(s: str) -> str:
    try:
        s = _RE_TG.sub("[REDACTED_TOKEN]", s or "")
        s = _RE_KV.sub(lambda m: f"{m.group(1)}=[REDACTED]", s)
    except Exception:
        return "[REDACTED]"
    return s


def _ps_json(cmd: str):
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, timeout=60)
        txt = (r.stdout or "").strip()
        if not txt or txt == "null":
            return []
        data = json.loads(txt)
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else []
    except Exception as e:
        return [{"_error": f"{type(e).__name__}: {e}"}]


def _pid_alive(pid: int) -> bool:
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, pid)
            if h:
                k.CloseHandle(h)
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
        return True
    except Exception:
        return False


def _role_of(cmd: str):
    c = (cmd or "").lower().replace("/", "\\")
    if "mic_bridge.py" in c:
        return "mic_bridge"
    if "remote_agent" in c and "agent.py" in c:
        return "agent.py"
    if "jarvis-v2-fijo" in c and "main.py" in c:
        return "main.py"
    return None


def collect_processes():
    rows = _ps_json(
        "Get-CimInstance Win32_Process "
        "-Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
        "Select-Object ProcessId,Name,ExecutablePath,CommandLine | "
        "ConvertTo-Json -Compress -Depth 3")
    procs = []
    for r in rows:
        if "_error" in r:
            return [], r["_error"]
        try:
            pid = int(r.get("ProcessId"))
        except (TypeError, ValueError):
            continue
        cmd = str(r.get("CommandLine") or "")
        role = _role_of(cmd)
        if not role:
            continue
        procs.append({
            "role": role,
            "pid": pid,
            "exe": str(r.get("Name") or ""),
            "consola": (str(r.get("Name") or "").lower() == "python.exe"),
            "interp": str(r.get("ExecutablePath") or ""),
            "cmd": _redact(cmd[:300]),
        })
    return procs, ""


def collect_conns():
    rows = _ps_json(
        "Get-NetTCPConnection | Select-Object LocalAddress,LocalPort,"
        "RemoteAddress,RemotePort,State,OwningProcess | "
        "ConvertTo-Json -Compress -Depth 2")
    out = []
    for r in rows:
        if "_error" in r:
            return [], r["_error"]
        try:
            lp, rp = int(r.get("LocalPort")), int(r.get("RemotePort"))
        except (TypeError, ValueError):
            continue
        if lp not in (OLD_PORT, NEW_PORT) and rp not in (OLD_PORT, NEW_PORT):
            continue
        out.append({
            "local": f"{r.get('LocalAddress')}:{lp}",
            "remote": f"{r.get('RemoteAddress')}:{rp}",
            "state": _canon_state(r.get("State")),
            "pid": r.get("OwningProcess"),
        })
    return out, ""


def kill_state():
    p = REMOTE_AGENT / "killswitch.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return ("BLOQUEADO" if data.get("locked") else "desbloqueado",
                f"locked={bool(data.get('locked'))}")
    except FileNotFoundError:
        return ("desbloqueado", "sin fichero")
    except Exception as e:
        return ("desbloqueado", f"corrupto ({type(e).__name__})")


def audit_check():
    try:
        sys.path.insert(0, str(REMOTE_AGENT))
        from audit import AuditLog
        ok, msg = AuditLog(REMOTE_AGENT / "audit.jsonl", side="agent").verify()
        return ok, msg
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def lock_check(path: Path, token: str):
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore").strip().split()
        pid = int(raw[0]) if raw else -1
    except FileNotFoundError:
        return ("ausente", -1, False, False)
    except Exception:
        return ("corrupto", -1, False, False)
    alive = _pid_alive(pid)
    match = False
    if alive and pid > 0:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                capture_output=True, text=True, timeout=30)
            match = token in ((r.stdout or "").lower().replace("/", "\\"))
        except Exception:
            match = False
    if alive and match:
        return ("verificado", pid, True, True)
    if alive:
        return ("PID vivo sin token", pid, True, False)
    return ("huerfano", pid, False, False)


def main() -> int:
    checks = []  # (nombre, estado PASS/FAIL/AVISO, detalle)
    procs, perr = collect_processes()
    by_role = {}
    for p in procs:
        by_role.setdefault(p["role"], []).append(p)
    n_agent = len(by_role.get("agent.py", []))
    n_main = len(by_role.get("main.py", []))
    n_mic = len(by_role.get("mic_bridge", []))
    checks.append(("agent.py x1", "PASS" if n_agent == 1 else "FAIL", f"n={n_agent}"))
    checks.append(("main.py x1", "PASS" if n_main == 1 else "FAIL", f"n={n_main}"))
    checks.append(("mic_bridge x1", "PASS" if n_mic == 1 else "FAIL", f"n={n_mic}"))
    if perr:
        checks.append(("enumerar procesos", "FAIL", perr[:150]))

    conns, cerr = collect_conns()
    if cerr:
        checks.append(("conexiones 8765/18765", "FAIL", cerr[:150]))
    agent_pids = {p["pid"] for p in by_role.get("agent.py", [])}
    main_pids = {p["pid"] for p in by_role.get("main.py", [])}
    est_new = [c for c in conns if c["state"] == "Established"
               and (c["local"].endswith(f":{NEW_PORT}") or c["remote"].endswith(f":{NEW_PORT}"))
               and c["pid"] in agent_pids]
    est_old = [c for c in conns if c["state"] == "Established"
               and (c["local"].endswith(f":{OLD_PORT}") or c["remote"].endswith(f":{OLD_PORT}"))
               and c["pid"] in main_pids]
    checks.append(("ESTABLISHED 18765 (agent.py)",
                   "PASS" if est_new else "FAIL",
                   f"n={len(est_new)}"))
    checks.append(("conexion 8765 (main.py)",
                   "PASS" if est_old else "FAIL",
                   f"n={len(est_old)}"))

    ks, ksdet = kill_state()
    checks.append(("killswitch", "AVISO" if ks == "BLOQUEADO" else "PASS",
                   f"{ks} ({ksdet})"))

    aok, amsg = audit_check()
    checks.append(("audit.verify()", "PASS" if aok else "FAIL", amsg[:150]))

    la, pa, aa, ma = lock_check(REMOTE_AGENT / "agent.lock", "agent.py")
    checks.append(("agent.lock",
                   "PASS" if la == "verificado" else "FAIL",
                   f"{la} pid={pa}"))
    lm, pm, am, mm = lock_check(VIEJO / "main.lock", "main.py")
    if lm == "verificado":
        checks.append(("main.lock", "PASS", f"verificado pid={pm}"))
    elif lm == "ausente" and n_main == 1:
        checks.append(("main.lock", "AVISO",
                       "ausente con 1 instancia (legacy: arrancada antes del lock)"))
    else:
        checks.append(("main.lock", "FAIL", f"{lm} pid={pm}"))
    lb, pb, ab, mb = lock_check(VIEJO / "mic_bridge.lock", "mic_bridge.py")
    checks.append(("mic_bridge.lock",
                   "PASS" if lb == "verificado" else "FAIL",
                   f"{lb} pid={pb}"))

    fails = sum(1 for _, s, _ in checks if s == "FAIL")
    verdict = "KO" if fails else "OK"

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    L = [f"boot_report {now} (solo lectura, sin secretos)",
         f"veredicto: {verdict} (fallos={fails}; criterio: 1 agent.py + 1 main.py + "
         "1 mic_bridge, audit.verify ok, locks verificados, ESTABLISHED 18765/8765)",
         ""]
    L.append("== procesos Jarvis ==")
    for p in procs:
        L.append(f"- {p['role']} pid={p['pid']} exe={p['exe']} "
                 f"consola={'SI' if p['consola'] else 'NO'} interp={p['interp']}")
        L.append(f"  cmd: {p['cmd']}")
    if not procs:
        L.append("(ninguno)")
    L.append("")
    L.append("== conexiones 8765/18765 ==")
    pid2role = {}
    for p in procs:
        pid2role[p["pid"]] = p["role"]
    for c in conns:
        L.append(f"- {c['local']} -> {c['remote']} {c['state']} "
                 f"pid={c['pid']} ({pid2role.get(c['pid'], '?')})")
    if not conns:
        L.append("(ninguna)")
    L.append("")
    L.append("== checks ==")
    for name, st, det in checks:
        L.append(f"[{st}] {name}: {det}")
    L.append("")
    L.append(f"VEREDICTO: {verdict}")
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"boot_report.txt: {REPORT}")
    for name, st, det in checks:
        print(f"[{st}] {name}: {det}")
    print(f"VEREDICTO: {verdict}")
    return 0 if verdict == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
