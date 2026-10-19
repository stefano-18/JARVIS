"""watchdog.py - Vigila gateway :18789, supervisor :8765 y OpenJarvis :8000.

- Si un puerto cae: intenta reinicio (gateway y OpenJarvis via schtasks
  /run; supervisor 8765 via pythonw Jarvis-v2/supervisor.py con su lock).
  NOTA Fase 4: la tarea "OpenJarvis Server" la crea un admin (ver reporte);
  hasta entonces su reinicio se informa como fallido por Telegram.
- Maximo 3 reinicios por hora (global, fichero de estado). Sin bucles.
- Avisa por Telegram (Bot API directa con tokenFile + allowFrom de openclaw;
  nunca imprime secretos). Si Telegram falla, lo deja en el log.
- Log: logs/watchdog.log (rotacion simple 200 KB).

Uso: tarea programada "JarvisWatchdog" cada 5 min (SYSTEM o usuario).
"""
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_JROOT = Path(__file__).resolve().parent.parent
LOG = _JROOT / "logs" / "watchdog.log"
STATE = _JROOT / "logs" / "watchdog_state.json"
MAX_RESTARTS_PER_HOUR = 3
PYTHONW = r"{{WIN_HOME}}\AppData\Local\Programs\Python\Python312\pythonw.exe"
SUPERVISOR = r"{{WIN_HOME}}\Jarvis-v2\supervisor.py"


def log(msg):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 200_000:
            LOG.write_text("", encoding="utf-8")
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def tcp_ok(port, host="127.0.0.1", timeout=5):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"restarts": []}


def save_state(st):
    try:
        STATE.write_text(json.dumps(st), encoding="utf-8")
    except Exception:
        pass


def budget_ok():
    st = load_state()
    now = time.time()
    st["restarts"] = [t for t in st.get("restarts", [])
                      if now - t < 3600]
    save_state(st)
    return len(st["restarts"]) < MAX_RESTARTS_PER_HOUR


def note_restart():
    st = load_state()
    st["restarts"] = st.get("restarts", []) + [time.time()]
    save_state(st)


def tg_send(text):
    try:
        cfg = json.loads((Path.home() / ".openclaw" / "openclaw.json"
                          ).read_text(encoding="utf-8"))
        token = (Path.home() / ".openclaw" / "telegram-token"
                 ).read_text(encoding="utf-8").strip()
        allow = cfg.get("channels", {}).get("telegram", {}).get(
            "allowFrom", [])
        if not token or not allow:
            return False
        body = json.dumps({"chat_id": allow[0], "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body, headers={"Content-Type": "application/json",
                                "User-Agent": "jarvis-watchdog"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception as e:
        log(f"telegram fallo: {str(e)[:100]}")
        return False


def restart_gateway():
    r = subprocess.run(["schtasks", "/run", "/tn", "OpenClaw Gateway"],
                       capture_output=True, text=True, timeout=60)
    return r.returncode == 0


def restart_openjarvis():
    r = subprocess.run(["schtasks", "/run", "/tn", "OpenJarvis Server"],
                       capture_output=True, text=True, timeout=60)
    return r.returncode == 0


def pc_idle_check():
    """Plan B (Fase 5): si el PC se desperto para IA y lleva 30+ min
    sin uso, pc_do.py lo suspende. Avisa por Telegram solo si actua."""
    try:
        r = subprocess.run(
            [PYTHONW, r"{{WIN_HOME}}\jarvis2\scripts\pc_do.py",
             "idle-check"], capture_output=True, text=True, timeout=100)
        if "suspendido por inactividad" in (r.stdout or ""):
            tg_send("JARVIS plan B: PC suspendido tras 30 min sin uso IA.")
    except Exception as e:
        log(f"idle-check fallo: {str(e)[:100]}")


def restart_supervisor():
    try:
        subprocess.Popen(
            [PYTHONW, SUPERVISOR], cwd=r"{{WIN_HOME}}\Jarvis-v2",
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        log(f"supervisor relanzar fallo: {str(e)[:100]}")
        return False


def main():
    problems = []
    pc_idle_check()  # Plan B Fase 5 (no bloquea; avisa solo si actua)
    if not tcp_ok(18789):
        problems.append("gateway :18789 caido")
    if not tcp_ok(8765):
        problems.append("supervisor :8765 caido")
    if not tcp_ok(8000):
        problems.append("openjarvis :8000 caido")
    if not problems:
        return 0
    log("detectado: " + "; ".join(problems))
    if not budget_ok():
        msg = ("Watchdog: " + "; ".join(problems) +
               ". Tope 3 reinicios/hora alcanzado, no actuo.")
        log(msg)
        tg_send(msg)
        return 1
    done = []
    if "gateway :18789 caido" in problems:
        if restart_gateway():
            note_restart()
            done.append("gateway reiniciado")
        else:
            done.append("gateway NO se pudo reiniciar")
    if "supervisor :8765 caido" in problems:
        if restart_supervisor():
            note_restart()
            done.append("supervisor relanzado")
        else:
            done.append("supervisor NO se pudo relanzar")
    if "openjarvis :8000 caido" in problems:
        if restart_openjarvis():
            note_restart()
            done.append("openjarvis reiniciado")
        else:
            done.append("openjarvis NO se pudo reiniciar")
    msg = "Watchdog JARVIS: " + "; ".join(problems) + " -> " + "; ".join(done)
    log(msg)
    tg_send(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
