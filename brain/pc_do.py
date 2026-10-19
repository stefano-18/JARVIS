"""pc_do.py - Control del PC fijo por el canal hub (Fase 5, Bloque C).

Uso: python scripts/pc_do.py <cmd> [args] [--yes] [--wait N]
  status | open <app> | close <app> | lock
  suspend [--yes] | shutdown [--yes] | restart [--yes]
  sendfile <local> <remoto> | wol [--wait 90] | ensure-awake [--wait 90]
  game on|off | idle-check

Seguridad: secreto solo de jarvis2/.env en proceso, nunca se imprime.
HIGH (suspend/shutdown/restart) exige --yes (= "si" del usuario en Telegram).
WOL: magic packet + espera TCP 18765/11434 (max 90 s).
game_mode persiste en data/game_mode.json; con game on no hay WOL para IA.
Plan B: ensure-awake --for-ia marca uso; idle-check (watchdog) suspende
tras 30 min sin uso si el PC se desperto por plan B.
"""
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

_JROOT = Path(__file__).resolve().parent.parent
if str(_JROOT) not in sys.path:
    sys.path.insert(0, str(_JROOT))

PC_IP_DEFAULT = "{{PC_IP}}"
try:  # arreglo 76: config unica
    import tomllib as _tl
    PC_IP_DEFAULT = _tl.load(open(os.path.expanduser("~/.config/jarvis/config.toml"), "rb")).get("pc_ip", PC_IP_DEFAULT)
except Exception:  # noqa: BLE001
    pass
GAME_FILE = _JROOT / "data" / "game_mode.json"
USE_FILE = _JROOT / "data" / "pc_ai_use.json"
HIGH = {"system.shutdown", "system.restart", "system.lock", "suspend.pc",
        "shell.exec"}


def load_env():
    vals = {}
    try:
        for line in (_JROOT / ".env").read_text(encoding="utf-8",
                                                errors="ignore").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return vals


_ENV = load_env()
SECRET = _ENV.get("JARVIS_REMOTE_SECRET", "")
DEVICE = _ENV.get("JARVIS_PC_DEVICE", "") or "pc-01"
PC_IP = (_ENV.get("JARVIS_PC_IP") or _ENV.get("PC_IP") or PC_IP_DEFAULT).strip()
MAC = (_ENV.get("JARVIS_PC_MAC") or "").strip()


def game_on() -> bool:
    try:
        return bool(json.loads(GAME_FILE.read_text(
            encoding="utf-8")).get("game_mode"))
    except Exception:
        return False


def set_game(on: bool):
    GAME_FILE.parent.mkdir(parents=True, exist_ok=True)
    GAME_FILE.write_text(json.dumps({"game_mode": on,
                                     "ts": int(time.time())}),
                         encoding="utf-8")


def stamp_use(woken: bool):
    USE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USE_FILE.write_text(json.dumps({"last_use": int(time.time()),
                                    "woken_by_planb": woken}),
                        encoding="utf-8")


def read_use():
    try:
        return json.loads(USE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _tcp_ok(ip, port, timeout=3) -> bool:
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def _ping_ok(ip) -> bool:
    try:
        r = subprocess.run(["ping", "-n", "1", "-w", "1000", ip],
                           capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except Exception:
        return False


def pc_awake() -> bool:
    return (_ping_ok(PC_IP) or _tcp_ok(PC_IP, 18765, 2)
            or _tcp_ok(PC_IP, 11434, 2))


def wol_send() -> int:
    parts = MAC.replace("-", ":").lower().split(":")
    if len(parts) != 6:
        raise ValueError("sin JARVIS_PC_MAC valida")
    hw = bytes(int(p, 16) for p in parts)
    pkt = b"\xff" * 6 + hw * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    n = 0
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for b in ("{{RED}}.255", "255.255.255.255"):
            for pt in (9, 7):
                try:
                    s.sendto(pkt, (b, pt))
                    n += 1
                except OSError:
                    pass
    finally:
        s.close()
    return n


def ensure_awake(wait_s=90, for_ia=False) -> dict:
    if for_ia and game_on():
        return {"status": "error", "code": "game_mode",
                "error": "modo juego activo: no se despierta el PC para IA"}
    if pc_awake():
        if for_ia:
            stamp_use(False)
        return {"status": "ok", "awake": True, "waited_s": 0}
    if for_ia and game_on():
        return {"status": "error", "code": "game_mode",
                "error": "modo juego activo"}
    try:
        wol_send()
    except ValueError as e:
        return {"status": "error", "code": "no_mac", "error": str(e)}
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(5)
        if pc_awake():
            if for_ia:
                stamp_use(True)
            return {"status": "ok", "awake": True,
                    "waited_s": int(time.time() - t0)}
    return {"status": "error", "code": "timeout",
            "error": f"PC no responde en {wait_s}s"}


async def _call(action, params=None, grant=None, timeout=20):
    from remote import hub_client as hc
    from remote import grants as G
    if not SECRET:
        return {"status": "error", "code": "no_secret",
                "error": "falta JARVIS_REMOTE_SECRET"}
    g = grant
    if g is None and action in HIGH:
        g = G.create_grant(SECRET, action, params or {})
    return await hc.acall_action(action, params or {}, grant=g,
                                 timeout=timeout, device=DEVICE,
                                 secret=SECRET)


def run(action, params=None, timeout=20):
    return asyncio.run(_call(action, params, timeout=timeout))


def hud_msg(text, title="Jarvis"):
    """Aviso al HUD por el WS local :8765 (best effort)."""
    import json as _j

    async def _send():
        try:
            from websockets.asyncio.client import connect
        except ImportError:
            from websockets import connect
        async with connect("ws://127.0.0.1:8765",
                           max_size=2 * 1024 * 1024) as ws:
            try:
                await asyncio.wait_for(ws.recv(), timeout=10)
            except Exception:
                pass
            await ws.send(_j.dumps({"type": "hud", "title": title,
                                    "text": text}))
    try:
        asyncio.run(_send())
        return True
    except Exception:
        return False


def ollama_models_pc():
    import urllib.request as _u
    try:
        req = _u.Request(f"http://{PC_IP}:11434/api/ps",
                         headers={"User-Agent": "jarvis-pcdo"})
        with _u.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return [m.get("name", "") for m in (data.get("models") or [])
                if isinstance(m, dict) and m.get("name")]
    except Exception:
        return []


def main(argv) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    yes = "--yes" in argv[1:]
    wait = 90
    for a in argv[1:]:
        if a.startswith("--wait"):
            try:
                wait = int(a.split("=", 1)[1] if "=" in a else argv[argv.index(a) + 1])
            except Exception:
                pass
    for_ia = "--for-ia" in argv[1:]
    if not args:
        print("uso: pc_do.py status|open|close|lock|suspend|shutdown|restart|sendfile|wol|ensure-awake|game|idle-check [--yes]")
        return 2
    cmd = args[0].lower()
    if cmd in ("open", "close", "lock", "sendfile") and not pc_awake():  # mejora 17: WOL automatico
        r = ensure_awake(120)
        if r.get("status") != "ok":
            print(f"El PC está apagado y no ha respondido al encenderlo, señor ({r.get('error')}).")
            return 1
        print("Encendiendo el PC primero, señor.")

    if cmd == "status":
        st = asyncio.run(_status())
        print(json.dumps(st, ensure_ascii=False)[:600])
        return 0 if st.get("status") == "ok" else 1
    if cmd == "wol":
        if game_on() and for_ia:
            print("game_mode on: sin WOL")
            return 1
        r = ensure_awake(wait)
        print(json.dumps(r, ensure_ascii=False)[:300])
        return 0 if r.get("status") == "ok" else 1
    if cmd == "ensure-awake":
        r = ensure_awake(wait, for_ia)
        print(json.dumps(r, ensure_ascii=False)[:300])
        return 0 if r.get("status") == "ok" else 1
    if cmd == "game" and len(args) > 1 and args[1] in ("on", "off"):
        on = args[1] == "on"
        set_game(on)
        if on:
            stopped = []
            for m in ollama_models_pc():
                rr = run("shell.exec", {"cmd": "ollama",
                                        "args": ["stop", m]}, timeout=30)
                if rr.get("status") == "ok":
                    stopped.append(m)
            hud_msg("Modo juego ON: PC libre para jugar",
                    title="Jarvis")
            print(f"game_mode=on (modelos detenidos: {stopped or 'ninguno'})")
        else:
            hud_msg("Modo juego OFF: HUD activo", title="Jarvis")
            print("game_mode=off")
        return 0
    if cmd == "idle-check":
        u = read_use()
        if (u.get("woken_by_planb")
                and time.time() - int(u.get("last_use", 0)) > 1800
                and pc_awake()):
            rr = run("shell.exec",
                     {"cmd": "powershell",
                      "args": ["-NoProfile", "-Command",
                               "Add-Type -AssemblyName System.Windows.Forms; "
                               "[System.Windows.Forms.Application]::"
                               "SetSuspendState('Suspend',$false,$false)"]},
                     timeout=30)
            if rr.get("status") == "ok":
                stamp_use(False)
                print("plan B: PC suspendido por inactividad (30 min)")
                return 0
            print("plan B: no se pudo suspender: "
                  + str(rr.get("error", ""))[:120])
            return 1
        print("plan B: nada que hacer")
        return 0
    if cmd == "open" and len(args) > 1:
        rr = run("apps.open", {"app": " ".join(args[1:])}, timeout=20)
    elif cmd == "close" and len(args) > 1:
        rr = run("apps.close", {"app": " ".join(args[1:])}, timeout=20)
    elif cmd == "lock":
        rr = run("system.lock", {}, timeout=30)
    elif cmd in ("suspend", "shutdown", "restart"):
        if not yes:
            print("HIGH_REQUIRES_USER_CONFIRM: usa --yes (= 'si' en Telegram)")
            return 2
        if cmd == "suspend":
            # shutdown /h exige hibernacion (off en el PC): suspender via
            # SetSuspendState con grant de params exactos (Fase 5).
            rr = run("shell.exec",
                     {"cmd": "powershell",
                      "args": ["-NoProfile", "-Command",
                               "Add-Type -AssemblyName System.Windows.Forms; "
                               "[System.Windows.Forms.Application]::"
                               "SetSuspendState('Suspend',$false,$false)"]},
                     timeout=30)
            if rr.get("code") == "timeout" and not pc_awake():
                rr = {"status": "ok", "note": "sin respuesta: PC dormido"}
        elif cmd == "shutdown":
            rr = run("system.shutdown", {}, timeout=30)
        else:
            rr = run("system.restart", {}, timeout=30)
    elif cmd == "sendfile" and len(args) > 2:
        try:
            content = Path(args[1]).read_text(encoding="utf-8",
                                              errors="replace")
        except OSError as e:
            print(f"no se lee local: {e}")
            return 2
        # El PC solo acepta rutas ABSOLUTAS en
        # {{WIN_HOME}}\Desktop\JARVIS-recibidos (fase8E).
        dest = args[2]
        if not re.match(r"^[A-Za-z]:", dest):
            name = dest.split("/")[-1].split("\\")[-1]
            if name in ("JARVIS-recibidos", ""):
                name = Path(args[1]).name
            dest = "{{WIN_HOME_ESC}}\\Desktop\\JARVIS-recibidos\\" + name
        rr = run("files.write", {"path": dest, "content": content},
                 timeout=30)
    else:
        print("comando o args invalidos")
        return 2
    ok = rr.get("status") == "ok"
    print(("OK " if ok else "ERROR ")
          + json.dumps(rr, ensure_ascii=False)[:400])
    return 0 if ok else 1


async def _status():
    from remote import hub_client as hc
    if not SECRET:
        return {"status": "error", "code": "no_secret"}
    try:
        st = await hc.astatus(secret=SECRET)
    except Exception as e:
        return {"status": "error", "code": "hub_down", "error": str(e)[:120]}
    devs = (st.get("devices") or []) if isinstance(st, dict) else []
    return {"status": "ok" if DEVICE in devs else "degraded",
            "hub": "up", "pc": DEVICE if DEVICE in devs else "desconectado",
            "ping": _ping_ok(PC_IP), "game_mode": game_on()}


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
