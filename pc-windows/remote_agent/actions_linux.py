"""Acciones del agente para Linux (Omarchy: Hyprland/Wayland + PipeWire).

Mismos nombres, parametros y respuestas que las de Windows: el hub y el
cerebro no notan la diferencia. actions.py sustituye las funciones de
Windows por estas cuando el agente corre en Linux.

Herramientas: grim (capturas), hyprctl (ventanas y raton), wtype (teclado),
ydotool (clic, si esta instalado), wl-copy/wl-paste (portapapeles),
wpctl (volumen), playerctl (multimedia), gtk-launch / steam / heroic (apps).
"""
import asyncio
import base64
import glob
import io
import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

try:
    from PIL import Image as _PILImage
except Exception:
    _PILImage = None

HOME = Path.home()
JUEGO_TXT = "jarvis-juego.txt"


def _err(code: str, msg: str, **extra) -> dict:
    msg = (msg or "").strip() or f"error desconocido ({code})"
    d = {"status": "error", "error": msg[:300], "code": code, "executed": False}
    d.update(extra)
    return d


def _run(cmd: list, timeout: float = 10) -> subprocess.CompletedProcess:
    _hypr_env()
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _hypr_env() -> None:
    """Si el agente arrancó antes que Hyprland (o Hyprland se reinició), busca la sesión viva."""
    run = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    sesiones = sorted(glob.glob(os.path.join(run, "hypr", "*", ".socket.sock")), key=os.path.getmtime)
    if sesiones and not os.path.exists(os.path.join(run, "hypr", os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "-"),
                                                   ".socket.sock")):
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = os.path.basename(os.path.dirname(sesiones[-1]))
    # sin WAYLAND_DISPLAY las apps que se abren mueren al momento (y el cerebro creía que se habían abierto)
    if not os.path.exists(os.path.join(run, os.environ.get("WAYLAND_DISPLAY", "-"))):
        pantallas = sorted((p for p in glob.glob(os.path.join(run, "wayland-*")) if not p.endswith(".lock")),
                           key=os.path.getmtime)
        if pantallas:
            os.environ["WAYLAND_DISPLAY"] = os.path.basename(pantallas[-1])


def _hypr(*args) -> object:
    _hypr_env()
    r = _run(["hyprctl", "-j"] + list(args))
    return json.loads(r.stdout or "null")


def _dispatch(*args) -> bool:
    _hypr_env()
    r = _run(["hyprctl", "dispatch"] + list(args))
    return r.returncode == 0 and "ok" in (r.stdout or "").lower()


def _lua(expr: str) -> bool:
    """Hyprland con configuración en Lua (Omarchy actual): los dispatchers son hl.dsp.*"""
    return _dispatch(expr)


def _w(w) -> str:
    return 'window = "address:0x%x"' % w["hwnd"]


def _plain(t) -> str:
    t = unicodedata.normalize("NFD", str(t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


# --- Rutas: el cerebro aun manda rutas de Windows (unidad:\carpeta de usuarios\nombre\Documents\...) ---

def linux_path(p) -> str:
    s = str(p or "")
    m = re.match(r"^[a-zA-Z]:\\Users\\[^\\]+\\?(.*)$", s)
    if m:
        rest = m.group(1).replace("\\", "/")
        rest = re.sub(r"^OneDrive/", "", rest)
        rest = rest.replace("Desktop/", "Documents/", 1) if rest.startswith("Desktop/") else rest
        return str(HOME / rest)
    return s


# --- Pantalla ---

def _monitors() -> list:
    """Como en Windows: la pantalla principal (la que está en 0,0) es la 1; las demás, de izquierda a derecha."""
    mons = _hypr("monitors") or []
    return sorted(mons, key=lambda m: (not (m.get("x") == 0 and m.get("y") == 0), m.get("x", 0), m.get("y", 0)))


async def screen_capture(params: dict, ctx: dict) -> dict:
    """monitor 0 = todas las pantallas; 1, 2... = de izquierda a derecha."""
    fmt = str(params.get("format", "jpeg")).lower()
    fmt = "jpeg" if fmt == "jpg" else fmt
    if fmt not in ("png", "jpeg"):
        return _err("bad_format", f"format debe ser png|jpeg, no '{fmt}'")
    try:
        monitor = int(params.get("monitor", 1))
        max_w = int(params["max_width"]) if params.get("max_width") else None   # sin tope: tamaño real, como Windows
        quality = max(10, min(95, int(params.get("quality", 70))))
    except Exception:
        return _err("bad_param", "monitor, max_width y quality deben ser int")
    if _PILImage is None:
        return _err("no_backend", "falta Pillow para la captura")
    cmd = ["grim"]
    if monitor > 0:
        mons = _monitors()
        if monitor > len(mons):
            return _err("bad_monitor", f"monitor {monitor} fuera de rango (hay {len(mons)})")
        cmd += ["-o", mons[monitor - 1]["name"]]
    try:
        r = await asyncio.to_thread(subprocess.run, cmd + ["-t", "png", "-"], capture_output=True, timeout=15)
        if r.returncode != 0:
            return _err("capture_failed", (r.stderr or b"").decode(errors="replace"))
        img = _PILImage.open(io.BytesIO(r.stdout)).convert("RGB")
        w, h = img.size
        if max_w and w > max_w:
            img = img.resize((max_w, int(h * max_w / w)), _PILImage.LANCZOS)
            w, h = img.size
        cap = 1024 * 1024
        for q in (quality, 60, 50, 40):
            buf = io.BytesIO()
            img.save(buf, "JPEG" if fmt == "jpeg" else "PNG", quality=q)
            raw = buf.getvalue()
            if fmt == "png" or len(raw) <= cap:
                break
    except Exception as e:
        return _err("capture_failed", f"captura fallo: {type(e).__name__}: {str(e)[:200]}")
    return {"status": "ok", "mime": f"image/{fmt}", "width": w, "height": h,
            "bytes": len(raw), "data_b64": base64.b64encode(raw).decode("ascii")}


# --- Ventanas (hwnd = direccion de la ventana en Hyprland, como entero) ---

def _clients() -> list:
    out = []
    for c in _hypr("clients") or []:
        if not c.get("mapped", True):
            continue
        out.append({"hwnd": int(c["address"], 16), "title": c.get("title", ""),
                    "pid": c.get("pid", -1), "process": c.get("class", ""),
                    "visible": not c.get("hidden", False),
                    "workspace": (c.get("workspace") or {}).get("name", "")})
    return out


async def window_list(params: dict, ctx: dict) -> dict:
    try:
        wins = await asyncio.to_thread(_clients)
    except Exception as e:
        return _err("enumerate_failed", f"enumerar fallo: {e}")
    vis = [w for w in wins if w["visible"] and w["title"]]
    return {"status": "ok", "count_total": len(wins), "count_visible_titled": len(vis), "windows": vis}


def _find(params: dict):
    wins = _clients()
    if params.get("hwnd") is not None:
        try:
            h = int(params["hwnd"])
        except Exception:
            return None, _err("bad_param", "hwnd debe ser int")
        for w in wins:
            if w["hwnd"] == h:
                return w, None
        return None, _err("window_not_found", f"no hay ventana {h}")
    t = _plain(params.get("title"))
    if not t:
        return None, _err("missing_param", "falta hwnd o title")
    for w in wins:
        if t in _plain(w["title"]) or t in _plain(w["process"]):
            return w, None
    return None, _err("window_not_found", f"no hay ventana con '{params.get('title')}'")


def _addr(w) -> str:
    return "address:0x%x" % w["hwnd"]


async def window_focus(params: dict, ctx: dict) -> dict:
    w, e = _find(params)
    if e:
        return e
    ok = _lua("hl.dsp.focus({ %s })" % _w(w))
    return {"status": "ok" if ok else "error", "hwnd": w["hwnd"], "title": w["title"], "executed": ok}


async def window_minimize(params: dict, ctx: dict) -> dict:
    w, e = _find(params)
    if e:
        return e
    ok = _lua('hl.dsp.window.move({ workspace = "special:minimized", follow = false, %s })' % _w(w))
    return {"status": "ok" if ok else "error", "hwnd": w["hwnd"], "executed": ok}


async def window_maximize(params: dict, ctx: dict) -> dict:
    w, e = _find(params)
    if e:
        return e
    ok = _lua('hl.dsp.window.fullscreen({ mode = "maximized", %s })' % _w(w))
    return {"status": "ok" if ok else "error", "hwnd": w["hwnd"], "executed": ok}


async def window_move(params: dict, ctx: dict) -> dict:
    w, e = _find(params)
    if e:
        return e
    try:
        x, y = int(params["x"]), int(params["y"])
    except Exception:
        return _err("bad_param", "x/y deben ser int")
    a = _addr(w)
    ok = _lua('hl.dsp.window.float({ action = "enable", %s })' % _w(w)) and \
        _lua("hl.dsp.window.move({ x = %d, y = %d, %s })" % (x, y, _w(w)))
    if ok and params.get("w") and params.get("h"):
        ok = _lua("hl.dsp.window.resize({ x = %d, y = %d, %s })" % (int(params["w"]), int(params["h"]), _w(w)))
    return {"status": "ok" if ok else "error", "hwnd": w["hwnd"], "x": x, "y": y, "executed": ok}


async def apps_close_window(params: dict, ctx: dict) -> dict:
    """Cierra la ventana de una app por nombre (como pulsar su X)."""
    w, e = _find({"title": params.get("app")})
    if e:
        return e
    ok = _lua("hl.dsp.window.close({ %s })" % _w(w))
    for _ in range(8):  # comprobar que de verdad se ha cerrado (si pide guardar, sigue ahí)
        if not ok or all(v["hwnd"] != w["hwnd"] for v in _clients()):
            break
        await asyncio.sleep(0.5)
    else:
        return _err("still_open", "la ventana sigue abierta (puede que pida guardar)", app=params.get("app"), title=w["title"])
    return {"status": "ok" if ok else "error", "app": params.get("app"), "title": w["title"], "executed": ok}


# --- Portapapeles ---

async def clipboard_read(params: dict, ctx: dict) -> dict:
    r = _run(["wl-paste", "--no-newline"])
    if r.returncode != 0:
        return {"status": "ok", "text": ""}
    return {"status": "ok", "text": r.stdout[:65536]}


async def clipboard_write(params: dict, ctx: dict) -> dict:
    text = str(params.get("text", ""))
    try:
        p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.communicate(text.encode("utf-8"), timeout=5)
    except Exception as e:
        return _err("clipboard_failed", str(e))
    return {"status": "ok", "chars": len(text)}


# --- Raton y teclado ---

_BTN = {"left": "0xC0", "right": "0xC1", "middle": "0xC2"}


def _cursor():
    try:
        x, y = (int(v) for v in _run(["hyprctl", "cursorpos"]).stdout.split(","))
        return x, y
    except Exception:
        return None


def _monitor_de(x, y, mons):
    return next((m for m in mons if m["x"] <= x < m["x"] + m["width"] and m["y"] <= y < m["y"] + m["height"]), None)


def _ir(x: int, y: int, intentos: int = 30) -> bool:
    """Movimientos relativos cortos, midiendo dónde queda cada vez (la aceleración varía), hasta 1-2 px del objetivo."""
    for _ in range(intentos):
        c = _cursor()
        if not c:
            return False
        dx, dy = x - c[0], y - c[1]
        if abs(dx) <= 1 and abs(dy) <= 1:
            return True
        paso = lambda d: 0 if d == 0 else max(-200, min(200, int(d / 2) or (1 if d > 0 else -1)))
        _run(["ydotool", "mousemove", "-x", str(paso(dx)), "-y", str(paso(dy))])
        time.sleep(0.03)
    c = _cursor()
    return bool(c) and abs(x - c[0]) <= 2 and abs(y - c[1]) <= 2


def mover_cursor(x: int, y: int, mons=None) -> bool:
    """Lleva el ratón EXACTAMENTE a (x, y) recorriendo el escritorio de forma continua, sin cambiar el foco.

    Para pasar de una pantalla a otra va en «L» por la franja donde las dos se solapan en altura (la pequeña está
    250 px más abajo: por encima de esa franja el borde es una pared). Comprueba con hyprctl cursorpos;
    si no queda donde debe devuelve False y NO se hace clic.
    """
    mons = mons or _monitors()
    dest = _monitor_de(x, y, mons)
    c = _cursor()
    if not dest or not c:
        return False
    orig = _monitor_de(*c, mons)
    if orig and orig["name"] != dest["name"]:
        arriba = max(orig["y"], dest["y"]) + 10
        abajo = min(orig["y"] + orig["height"], dest["y"] + dest["height"]) - 11
        if arriba <= abajo:                                   # hay solape: ruta en L, cruzando por él
            yw = max(arriba, min(abajo, c[1]))
            borde = dest["x"] + dest["width"] - 10 if dest["x"] < orig["x"] else dest["x"] + 10
            if not (_ir(c[0], yw) and _ir(borde, yw)):
                return False
        else:                                                 # sin solape: enfocar la pantalla lleva el ratón allí
            _lua('hl.dsp.focus({ monitor = "%s" })' % dest["name"])
            time.sleep(0.08)
    return _ir(x, y)


async def ui_point(params: dict, ctx: dict) -> dict:
    """Mueve el ratón al punto SIN pulsar (para que el señor confirme antes de un clic)."""
    try:
        x, y = int(params["x"]), int(params["y"])
    except Exception:
        return _err("bad_param", "faltan x/y (int)")
    if not shutil.which("ydotool"):
        return _err("gui_unavailable", "falta ydotool")
    ok = await asyncio.to_thread(mover_cursor, x, y)
    return {"status": "ok", "x": x, "y": y, "cursor": _cursor()} if ok else _err("cursor_mismatch", "no pude colocar el ratón")


async def ui_click(params: dict, ctx: dict) -> dict:
    """Coordenadas del escritorio completo (como en Windows): mueve con hyprctl y pulsa con ydotool."""
    try:
        x, y = int(params["x"]), int(params["y"])
    except Exception:
        return _err("bad_param", "faltan x/y (int)")
    button = str(params.get("button", "left")).lower()
    if button not in _BTN:
        return _err("bad_button", f"button debe ser left|right|middle, no '{button}'")
    mons = _monitors()
    if mons and not any(m["x"] <= x < m["x"] + m["width"] and m["y"] <= y < m["y"] + m["height"] for m in mons):
        return _err("out_of_bounds", f"({x},{y}) fuera de las pantallas: no se hizo clic")
    if not shutil.which("ydotool"):
        return _err("gui_unavailable", "falta ydotool para hacer clic en Linux")
    if not mover_cursor(x, y, mons):        # nunca un clic a ciegas: si el ratón no está justo ahí, no se pulsa
        return _err("cursor_mismatch", f"no he podido poner el ratón en ({x},{y}): no se hizo clic")
    time.sleep(0.08)
    r = _run(["ydotool", "click", _BTN[button]])
    if r.returncode != 0:
        return _err("click_failed", r.stderr or "ydotool fallo (¿servicio ydotoold parado?)")
    return {"status": "ok", "x": x, "y": y, "button": button}


_WTYPE_MODS = {"ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift",
               "win": "logo", "super": "logo", "meta": "logo"}
_WTYPE_KEYS = {"enter": "Return", "tab": "Tab", "esc": "Escape", "escape": "Escape", "space": "space",
               "backspace": "BackSpace", "delete": "Delete", "del": "Delete", "insert": "Insert",
               "ins": "Insert", "home": "Home", "end": "End", "pgup": "Prior", "pgdn": "Next",
               "up": "Up", "down": "Down", "left": "Left", "right": "Right", "capslock": "Caps_Lock",
               "printscreen": "Print", "pause": "Pause", "apps": "Menu", "menu": "Menu"}


async def ui_keypress(params: dict, ctx: dict) -> dict:
    """Mismo formato que Windows: "a", "Enter", "ctrl+v", "alt+F4", "win+r", "shift"."""
    keys = str(params.get("keys") or "").strip()
    tokens = [t for t in keys.split("+") if t]
    if not tokens:
        return _err("missing_param", "falta param keys")
    *mods, main = tokens
    cmd = ["wtype"]
    for m in mods:
        if m.lower() not in _WTYPE_MODS:
            return _err("bad_modifier", f"modificador invalido '{m}'")
        cmd += ["-M", _WTYPE_MODS[m.lower()]]
    low = main.lower()
    if low in _WTYPE_MODS and not mods:          # solo un modificador (p. ej. "shift" para despertar)
        cmd += ["-M", _WTYPE_MODS[low], "-m", _WTYPE_MODS[low]]
    elif len(main) == 1:
        cmd += ["-k", main] if main.isalnum() else [main]
    elif low in _WTYPE_KEYS:
        cmd += ["-k", _WTYPE_KEYS[low]]
    elif low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
        cmd += ["-k", "F" + low[1:]]
    else:
        return _err("unknown_key", f"tecla '{main}' desconocida")
    for m in reversed(mods):
        cmd += ["-m", _WTYPE_MODS[m.lower()]]
    r = _run(cmd)
    if r.returncode != 0:
        return _err("keypress_failed", r.stderr or "wtype fallo")
    return {"status": "ok", "keys": keys, "pressed": [m.lower() for m in mods] + [main]}


# --- Multimedia y volumen ---

def _player(cmd: str) -> dict:
    r = _run(["playerctl", cmd])
    return {"status": "ok" if r.returncode == 0 else "error", "executed": r.returncode == 0,
            **({} if r.returncode == 0 else {"code": "no_player", "error": (r.stderr or "sin reproductor").strip()})}


async def media_play_pause(params: dict, ctx: dict) -> dict:
    return _player("play-pause")


async def media_next(params: dict, ctx: dict) -> dict:
    return _player("next")


async def media_previous(params: dict, ctx: dict) -> dict:
    return _player("previous")


def _vol() -> tuple:
    r = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    m = re.search(r"([\d.]+)", r.stdout or "")
    return (round(float(m.group(1)) * 100) if m else None), "MUTED" in (r.stdout or "")


async def volume_get(params: dict, ctx: dict) -> dict:
    lvl, muted = _vol()
    return {"status": "ok", "level": lvl, "muted": muted}


async def volume_set(params: dict, ctx: dict) -> dict:
    try:
        lvl = max(0, min(100, int(params.get("level"))))
    except Exception:
        return _err("bad_param", "level debe ser int 0..100")
    _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
    r = _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{lvl}%"])
    if r.returncode != 0:
        return _err("volume_failed", r.stderr)
    return {"status": "ok", "level": _vol()[0]}


async def volume_mute(params: dict, ctx: dict) -> dict:
    m = params.get("muted")
    arg = "toggle" if m is None else ("1" if m else "0")
    r = _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", arg])
    if r.returncode != 0:
        return _err("volume_failed", r.stderr)
    return {"status": "ok", "muted": _vol()[1]}


# --- Sistema ---

async def system_lock(params: dict, ctx: dict) -> dict:
    r = _run(["loginctl", "lock-session"])
    if r.returncode != 0 and shutil.which("hyprlock"):
        subprocess.Popen(["hyprlock"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"status": "ok", "executed": True}
    return {"status": "ok" if r.returncode == 0 else "error", "executed": r.returncode == 0}


async def system_shutdown(params: dict, ctx: dict) -> dict:
    r = _run(["systemctl", "poweroff"], 30)
    ok = r.returncode == 0
    return {"status": "ok" if ok else "error", "executed": ok, "code": "ok" if ok else "shutdown_failed",
            "mensaje": f"Apagado {'exitoso' if ok else 'fallido'}"}


async def system_suspend(params: dict, ctx: dict) -> dict:
    """Suspensión (la vía para encenderlo luego a distancia con Wake-on-LAN sin pedir la contraseña del disco)."""
    # se lanza en segundo plano y con un respiro, para que la respuesta llegue al cerebro antes de dormirse
    pid = _launch(["sh", "-c", "sleep 2; systemctl suspend"])
    return {"status": "ok", "executed": True, "code": "ok", "mensaje": "Suspendiendo el PC", "pid": pid}


async def system_restart(params: dict, ctx: dict) -> dict:
    r = _run(["systemctl", "reboot"], 30)
    ok = r.returncode == 0
    return {"status": "ok" if ok else "error", "executed": ok, "code": "ok" if ok else "restart_failed",
            "mensaje": f"Reinicio {'exitoso' if ok else 'fallido'}"}


# --- Apps y juegos ---

def _desktop_entries() -> list:
    dirs = [HOME / ".local/share/applications", Path("/usr/share/applications"),
            Path("/var/lib/flatpak/exports/share/applications"),
            HOME / ".local/share/flatpak/exports/share/applications"]
    out, seen = [], set()
    for d in dirs:
        for f in sorted(glob.glob(str(d / "*.desktop"))):
            did = os.path.basename(f)[:-8]
            if did in seen:
                continue
            seen.add(did)
            name, nodisp = "", False
            try:
                for ln in open(f, encoding="utf-8", errors="replace"):
                    if ln.startswith("[") and ln.strip() != "[Desktop Entry]":
                        break
                    if ln.startswith("Name=") and not name:
                        name = ln[5:].strip()
                    elif ln.strip() in ("NoDisplay=true", "Hidden=true"):
                        nodisp = True
            except OSError:
                continue
            if name and not nodisp:
                out.append({"id": did, "name": name, "file": f})
    return out


def _steam_games() -> list:
    out = []
    for root in (HOME / ".local/share/Steam", HOME / ".steam/steam"):
        for f in glob.glob(str(root / "steamapps/appmanifest_*.acf")):
            try:
                txt = open(f, encoding="utf-8", errors="replace").read()
                appid = re.search(r'"appid"\s+"(\d+)"', txt).group(1)
                name = re.search(r'"name"\s+"([^"]+)"', txt).group(1)
                out.append({"appid": appid, "name": name})
            except Exception:
                continue
        if out:
            break
    return out


def _launch(cmd: list) -> int:
    _hypr_env()
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    return p.pid


def _heroic_installed() -> dict:
    """Juegos de Epic instalados en Heroic: titulo plano -> appName."""
    out = {}
    for raiz in (HOME / ".config/heroic", HOME / ".var/app/com.heroicgameslauncher.hgl/config/heroic"):
        try:
            data = json.loads((raiz / "legendaryConfig/legendary/installed.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for app_name, v in data.items():
            if isinstance(v, dict) and not v.get("is_dlc"):
                out[_plain(v.get("title", ""))] = app_name
    return out


def _launch_line(line: str) -> list:
    """Orden de juego que manda el cerebro: steam://...[|cuenta], epic:<accion>:<nombre>, una URL o una app."""
    line = line.strip()
    if line.startswith("steam://"):
        return ["steam", line.split("|", 1)[0]]   # "|cuenta" era el cambio de cuenta de Windows
    m = re.match(r"^epic:(?:(abrir|jugar|instalar|actualizar):)?(.+)$", line)
    if m:
        if m.group(1) in (None, "abrir", "jugar"):
            q = _plain(m.group(2))
            inst = _heroic_installed()
            app = inst.get(q) or next((a for t, a in inst.items() if q and (q in t or t in q)), None)
            if app:
                return ["xdg-open", f"heroic://launch?appName={app}&runner=legendary"]
        return ["heroic"]                         # instalar/actualizar o no instalado: abre Heroic
    if re.match(r"^[a-z]+://", line):
        return ["xdg-open", line]
    return []


async def apps_open(params: dict, ctx: dict) -> dict:
    app = str(params.get("app", "")).strip()
    if not app:
        return _err("missing_param", "falta app", app=app, owned=False, was_running=False, pids=[])
    if _plain(app) == "jarvis juego":           # orden de juego escrita antes con files.write
        for d in ("Documents", "Downloads", "JARVIS-backups", ""):
            f = HOME / d / JUEGO_TXT
            if f.exists() and time.time() - f.stat().st_mtime < 120:
                line = f.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0]
                cmd = _launch_line(line)
                if not cmd:
                    return _err("bad_order", f"orden de juego desconocida: {line[:80]}", app=app)
                pid = _launch(cmd)
                return {"status": "ok", "app": app, "owned": False, "was_running": False, "pids": [pid], "order": line[:120]}
        return _err("no_order", "no hay orden de juego reciente", app=app, owned=False, was_running=False, pids=[])
    if re.match(r"^(https?|steam|heroic)://", app):
        return {"status": "ok", "app": app, "owned": False, "was_running": False,
                "pids": [_launch(["steam", app] if app.startswith("steam://") else ["xdg-open", app])]}
    q = _plain(app)
    cands = []
    for e in _desktop_entries():
        n, i = _plain(e["name"]), _plain(e["id"].split(".")[-1])
        score = 3 if q in (n, i) else 2 if n.startswith(q) or i.startswith(q) else 1 if q in n or q in i else 0
        if score:
            cands.append((score, -len(n), e))
    for g in _steam_games():
        n = _plain(g["name"])
        score = 3 if q == n else 2 if n.startswith(q) else 1 if q in n else 0
        if score:
            cands.append((score, -len(n), {"steam": g["appid"], "name": g["name"]}))
    if not cands:
        return _err("app_not_allowed", f"no encuentro '{app}' en este PC", app=app, owned=False, was_running=False, pids=[])
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
    best = cands[0][2]
    if "steam" in best:
        pid = _launch(["steam", "steam://rungameid/" + best["steam"]])
    else:
        _hypr_env()
        p = subprocess.Popen(["gtk-launch", best["id"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, start_new_session=True)
        try:  # gtk-launch sale al momento: si falla, decirlo en vez de dar un «ok» falso
            if p.wait(timeout=5) != 0:
                return _err("launch_failed", (p.stderr.read() or b"").decode("utf-8", "replace")[:200] or "gtk-launch fallo",
                            app=app, owned=False, was_running=False, pids=[])
        except subprocess.TimeoutExpired:
            pass
        pid = p.pid
    return {"status": "ok", "app": app, "name": best["name"], "owned": False, "was_running": False, "pids": [pid]}


async def apps_close(params: dict, ctx: dict) -> dict:
    return await apps_close_window(params, ctx)


async def web_open(params: dict, ctx: dict) -> dict:
    url = str(params.get("url", ""))
    if not re.match(r"^https?://", url):
        return _err("bad_url", "url debe empezar por http(s)://")
    return {"status": "ok", "url": url, "pid": _launch(["xdg-open", url])}


def installed_apps() -> dict:
    """Allowlist de apps.open/close en Linux: lo instalado en este PC (nombre -> id)."""
    out = {"jarvis-juego": "jarvis-juego"}
    try:
        for e in _desktop_entries():
            for k in (e["name"].lower(), _plain(e["name"]), e["id"].lower(), e["id"].split(".")[-1].lower()):
                out.setdefault(k, e["id"])
        for g in _steam_games():
            for k in (g["name"].lower(), _plain(g["name"])):
                out.setdefault(k, "steam://rungameid/" + g["appid"])
    except Exception:
        pass
    return out


# --- Archivos: el cerebro manda rutas de Windows ---

def translate_paths(params: dict) -> dict:
    p = dict(params or {})
    for k in ("path", "src", "dst"):
        if k in p:
            p[k] = linux_path(p[k])
    return p


def wrap_paths(fn):
    """Crea la carpeta destino si falta (Documents, Downloads...) antes de escribir."""
    async def inner(params: dict, ctx: dict) -> dict:
        for k in ("path", "dst"):
            if (params or {}).get(k):
                try:
                    Path(params[k]).parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
        return await fn(params, ctx)
    return inner


# --- shell.exec: lo que el cerebro mandaba a PowerShell ---

def wrap_shell(fn):
    async def inner(params: dict, ctx: dict) -> dict:
        cmd = str((params or {}).get("cmd", "")).lower()
        if cmd in ("powershell", "powershell.exe", "pwsh"):
            body = " ".join((params or {}).get("args") or [])
            if "SetSuspendState" in body:  # igual que system.suspend: contesta antes de dormirse
                r = await system_suspend({}, ctx)
                return {"status": "ok", "stdout": r.get("mensaje", ""), "stderr": "", "exit_code": 0, "truncated": False}
            return _err("command_not_found", "PowerShell no existe en este PC (Linux)")
        return await fn(params, ctx)
    return inner


ESTADO_JUEGO = HOME / ".local/state/jarvis/modo_juego.json"


def _dnd(on: bool) -> None:
    _run(["omarchy-shell", "notifications", "setDnd", "on" if on else "off"])
    _run(["omarchy-shell", "-q", "omarchy.indicators", "refresh"])


async def game_mode(params: dict, ctx: dict) -> dict:
    """Modo juego del PC: avisos en silencio y perfil de rendimiento; al salir, todo como estaba."""
    on = bool(params.get("on"))
    if on:
        prev = {"volumen": _vol()[0], "perfil": _run(["powerprofilesctl", "get"]).stdout.strip()}
        if not ESTADO_JUEGO.exists():
            ESTADO_JUEGO.parent.mkdir(parents=True, exist_ok=True)
            ESTADO_JUEGO.write_text(json.dumps(prev), encoding="utf-8")
        _dnd(True)
        _run(["powerprofilesctl", "set", "performance"])
        return {"status": "ok", "on": True}
    try:
        prev = json.loads(ESTADO_JUEGO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prev = {}
    _dnd(False)
    if prev.get("perfil"):
        _run(["powerprofilesctl", "set", prev["perfil"]])
    if prev.get("volumen") is not None:
        _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{prev['volumen']}%"])
    ESTADO_JUEGO.unlink(missing_ok=True)
    return {"status": "ok", "on": False, "restaurado": prev}


# --- Habilidades de voz (dictado, clip, música, archivos) ---

async def ui_type(params: dict, ctx: dict) -> dict:
    """Dictado: escribe el texto en la ventana activa (wtype, sin permisos de administrador)."""
    text = str(params.get("text", ""))[:4000]
    if not text:
        return _err("missing_param", "falta text")
    r = _run(["wtype", "-d", "4", text], 60)
    return {"status": "ok", "chars": len(text)} if r.returncode == 0 else _err("type_failed", r.stderr or "wtype fallo")


async def clip_save(params: dict, ctx: dict) -> dict:
    """Guarda los últimos 30 s que graba en bucle gpu-screen-recorder (servicio jarvis-clip)."""
    r = _run(["pkill", "-SIGUSR1", "-f", "gpu-screen-recorder .*-r 30"])
    if r.returncode != 0:
        return _err("clip_off", "la grabación en bucle no está en marcha")
    return {"status": "ok", "carpeta": str(HOME / "Videos/Clips")}


def _spotify_uri(q: str):
    """Busca X en open.spotify.com (vía DuckDuckGo) y devuelve su URI: artista, lista, álbum o canción."""
    import urllib.parse
    import urllib.request
    datos = urllib.parse.urlencode({"q": "site:open.spotify.com " + q, "kl": "es-es"}).encode()
    req = urllib.request.Request("https://html.duckduckgo.com/html/", data=datos,
                                 headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) jarvis/1.0", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=12) as r:
        page = urllib.parse.unquote(r.read(600_000).decode("utf-8", "replace"))
    m = re.search(r"open\.spotify\.com(?:/intl-[a-z]+)?/(track|album|playlist|artist)/([A-Za-z0-9]{22})", page)
    return f"spotify:{m.group(1)}:{m.group(2)}" if m else None


async def music_play(params: dict, ctx: dict) -> dict:
    """«Pon X en Spotify»: busca X y lo pone en la app de Spotify del PC (con la sesión del señor, sin API)."""
    q = re.sub(r"\s+", " ", str(params.get("q", ""))).strip()[:100]
    if not q:
        return _player("play")
    try:
        uri = await asyncio.to_thread(_spotify_uri, q)
    except Exception:
        uri = None
    if not uri:
        from urllib.parse import quote
        return {"status": "ok", "pid": _launch(["xdg-open", "spotify:search:" + quote(q)]), "q": q, "exacto": False}
    if _run(["playerctl", "-p", "spotify", "status"]).returncode != 0:   # Spotify cerrado: abrirlo y esperar
        _launch(["gtk-launch", "spotify"] if shutil.which("gtk-launch") else ["spotify"])
        for _ in range(40):
            await asyncio.sleep(0.5)
            if _run(["playerctl", "-p", "spotify", "status"]).returncode == 0:
                break
        await asyncio.sleep(2)
    r = _run(["playerctl", "-p", "spotify", "open", uri])
    if r.returncode != 0:
        return _err("spotify_failed", r.stderr or "Spotify no responde")
    return {"status": "ok", "q": q, "uri": uri, "exacto": True}


BUSCAR_EN = ("Documents", "Downloads", "Pictures", "Desktop", "Videos", "Music")


async def files_find(params: dict, ctx: dict) -> dict:
    """Busca archivos por palabras del nombre en las carpetas del señor (más reciente primero)."""
    words = [w for w in _plain(params.get("q")).split() if len(w) > 2]
    if not words:
        return _err("missing_param", "falta q")
    hits = []
    for d in BUSCAR_EN:
        for root, dirs, files in os.walk(HOME / d):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for f in files:
                n = _plain(f)
                score = sum(w in n for w in words)
                if score:
                    p = os.path.join(root, f)
                    try:
                        st = os.stat(p)
                    except OSError:
                        continue
                    hits.append((score, st.st_mtime, p, st.st_size))
    hits.sort(reverse=True)
    return {"status": "ok", "files": [{"path": p, "bytes": s} for _, _, p, s in hits[:5]]}


async def files_send(params: dict, ctx: dict) -> dict:
    """Pasa un archivo al portátil para que JARVIS lo mande por Telegram (sin tope de 2 MB del canal)."""
    p = Path(str(params.get("path", "")))
    if not p.is_file() or not any(str(p.resolve()).startswith(str(HOME / d) + os.sep) for d in BUSCAR_EN):
        return _err("bad_path", "solo archivos de Documentos, Descargas, Imágenes, Escritorio, Vídeos o Música")
    if p.stat().st_size > 49 * 1024 * 1024:
        return _err("too_large", "Telegram no acepta más de 50 MB")
    dest = "jarvis-envio-" + re.sub(r"[^\w.-]", "_", p.name)
    r = _run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", str(p),
              f"{os.environ.get('HUB_HOST', '127.0.0.1')}:/tmp/{dest}"], 120)
    return {"status": "ok", "remote": "/tmp/" + dest, "name": p.name} if r.returncode == 0 else _err("send_failed", r.stderr)


async def selection_read(params: dict, ctx: dict) -> dict:
    """«Léemelo»: el texto seleccionado con el ratón; si no hay, lo copiado."""
    for cmd in (["wl-paste", "--primary", "--no-newline"], ["wl-paste", "--no-newline"]):
        r = _run(cmd + ["--type", "text"])
        if r.returncode == 0 and r.stdout.strip():
            return {"status": "ok", "text": r.stdout[:20000], "origen": "seleccion" if "--primary" in cmd else "copiado"}
    return {"status": "ok", "text": "", "origen": ""}


async def music_now(params: dict, ctx: dict) -> dict:
    """«¿Qué suena?»: canción y artista del reproductor activo (Spotify primero)."""
    for p in (["-p", "spotify"], []):
        r = _run(["playerctl"] + p + ["metadata", "--format", "{{status}}|{{artist}}|{{title}}|{{playerName}}"])
        if r.returncode == 0 and r.stdout.strip():
            st, artist, title, player = (r.stdout.strip().split("|") + ["", "", "", ""])[:4]
            return {"status": "ok", "estado": st, "artista": artist, "titulo": title, "reproductor": player}
    return {"status": "ok", "estado": "Stopped", "artista": "", "titulo": "", "reproductor": ""}


async def focus_mode(params: dict, ctx: dict) -> dict:
    """«Modo concentración X minutos»: silencia avisos y los devuelve solos al acabar (con un aviso)."""
    try:
        minutos = max(1, min(240, int(params.get("min", 25))))
    except Exception:
        return _err("bad_param", "min debe ser un número de minutos")
    _run(["systemctl", "--user", "stop", "jarvis-concentracion.timer"])
    _dnd(True)
    fin = ("omarchy-shell notifications setDnd off; omarchy-shell -q omarchy.indicators refresh; "
           f"notify-send -a JARVIS 'JARVIS' 'Fin del modo concentración ({minutos} min). Avisos de vuelta.'")
    r = _run(["systemd-run", "--user", "--unit", "jarvis-concentracion", f"--on-active={minutos}m",
              "--timer-property=AccuracySec=5s", "/bin/sh", "-c", fin])
    if r.returncode != 0:
        _dnd(False)
        return _err("timer_failed", r.stderr or "no pude programar el final")
    return {"status": "ok", "min": minutos}


def salud_pc() -> dict:
    """Temperaturas, memoria, disco y actualizaciones del PC (lo usan «¿cómo está el PC?» y los avisos)."""
    d = {}
    r = _run(["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total",
              "--format=csv,noheader,nounits"])
    if r.returncode == 0 and r.stdout.strip():
        t, u, mu, mt = [x.strip() for x in r.stdout.split(",")[:4]]
        d.update(gpu_temp=int(t), gpu_uso=int(u), gpu_mem=round(int(mu) / max(1, int(mt)) * 100))
    m = re.search(r"Tctl:\s*\+?([\d.]+)", _run(["sensors"]).stdout or "")
    if m:
        d["cpu_temp"] = round(float(m.group(1)))
    mem = dict(re.findall(r"^(\w+):\s+(\d+)", open("/proc/meminfo").read(), re.M))
    d["ram_uso"] = round(100 - int(mem["MemAvailable"]) / int(mem["MemTotal"]) * 100)
    st = os.statvfs(str(HOME))
    d["disco_uso"] = round(100 - st.f_bavail / st.f_blocks * 100)
    d["disco_libre_gb"] = round(st.f_bavail * st.f_frsize / 1e9)
    d["arrancado_h"] = round(float(open("/proc/uptime").read().split()[0]) / 3600, 1)
    return d


async def system_health(params: dict, ctx: dict) -> dict:
    d = await asyncio.to_thread(salud_pc)
    try:
        r = await asyncio.to_thread(_run, ["checkupdates"], 40)
        d["actualizaciones"] = len([x for x in r.stdout.splitlines() if x.strip()])
    except Exception:
        pass
    return {"status": "ok", **d}


JUEGO_LOG = HOME / ".local/state/jarvis/juego.jsonl"


async def games_time(params: dict, ctx: dict) -> dict:
    """«¿Cuánto he jugado?»: suma las partidas que anota la voz (modo juego) en los últimos N días."""
    dias = max(1, min(31, int(params.get("dias", 1))))
    desde = time.time() - dias * 86400 if dias > 1 else time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    total, por = 0.0, {}
    try:
        for ln in JUEGO_LOG.read_text(encoding="utf-8").splitlines():
            e = json.loads(ln)
            if re.search(r"wallpaper engine", e.get("juego", ""), re.I):
                continue
            ini, fin = max(e["ini"], desde), e.get("fin") or time.time()
            if fin > ini:
                total += fin - ini
                por[e.get("juego") or "?"] = por.get(e.get("juego") or "?", 0) + fin - ini
    except (OSError, ValueError):
        pass
    act = JUEGO_LOG.with_name("juego_actual.json")          # partida en curso (la voz la refresca cada minuto)
    try:
        if time.time() - act.stat().st_mtime < 180:
            e = json.loads(act.read_text(encoding="utf-8"))
            if re.search(r"wallpaper engine", e.get("juego", ""), re.I):
                raise ValueError("no es un juego")
            seg = time.time() - max(e["ini"], desde)
            if seg > 0:
                total += seg
                por[e.get("juego") or "?"] = por.get(e.get("juego") or "?", 0) + seg
    except (OSError, ValueError, KeyError):
        pass
    top = sorted(por.items(), key=lambda x: -x[1])[:3]
    return {"status": "ok", "minutos": round(total / 60), "juegos": [{"juego": j, "minutos": round(s / 60)} for j, s in top]}


async def screen_record(params: dict, ctx: dict) -> dict:
    """«Graba la pantalla» / «para de grabar» (con el sonido del PC). Se guarda en Vídeos."""
    if params.get("on"):
        r = _run(["omarchy", "screenrecord", "--fullscreen", "--with-desktop-audio"], 20)
        return {"status": "ok", "grabando": True} if r.returncode == 0 else _err("record_failed", r.stderr)
    r = _run(["omarchy", "screenrecord", "--stop-recording"], 30)
    ruta = (r.stdout or "").strip().splitlines()[-1:] or [""]
    if r.returncode != 0 or not ruta[0]:
        return _err("not_recording", "no había ninguna grabación en marcha")
    return {"status": "ok", "grabando": False, "archivo": ruta[0]}


async def night_light(params: dict, ctx: dict) -> dict:
    """«Activa/quita la luz nocturna» (pantalla más cálida)."""
    try:
        st = json.loads(_run(["omarchy", "toggle", "nightlight", "--status"]).stdout or "{}")
    except ValueError:
        st = {}
    on = bool(params.get("on"))
    if bool(st.get("enabled")) != on:
        _launch(["omarchy", "toggle", "nightlight"])      # deja hyprsunset en marcha: sin esperar su salida
        for _ in range(20):
            await asyncio.sleep(0.25)
            try:
                if bool(json.loads(_run(["omarchy", "toggle", "nightlight", "--status"]).stdout or "{}").get("enabled")) == on:
                    break
            except ValueError:
                pass
    return {"status": "ok", "on": on}


async def window_screen(params: dict, ctx: dict) -> dict:
    """La ventana de delante: a la otra pantalla, a pantalla completa o de vuelta a normal."""
    acc = str(params.get("accion", "otra"))
    if params.get("app"):  # «pasa Spotify a la otra pantalla»: primero al frente esa ventana
        w, e = _find({"title": params["app"]})
        if e:
            return e
        _lua("hl.dsp.focus({ %s })" % _w(w))
    if acc in ("otra", "izquierda", "derecha"):
        ok = _lua('hl.dsp.window.move({ monitor = "%s" })' % {"otra": "+1", "izquierda": "l", "derecha": "r"}[acc])
        if not ok and acc != "otra":  # ya estaba en la pantalla de ese lado
            xs = [m["x"] for m in (_hypr("monitors") or [])]
            mx = next((m["x"] for m in (_hypr("monitors") or []) if m["id"] == (_hypr("activewindow") or {}).get("monitor")), None)
            ok = mx is not None and mx == (min(xs) if acc == "izquierda" else max(xs))
    elif acc in ("completa", "normal"):
        w = _hypr("activewindow") or {}
        if bool(w.get("fullscreen")) == (acc == "completa"):
            return {"status": "ok", "accion": acc}
        ok = _lua('hl.dsp.window.fullscreen({ mode = "fullscreen" })')
    else:
        return _err("bad_param", "accion: otra|izquierda|derecha|completa|normal")
    return {"status": "ok" if ok else "error", "accion": acc}


async def files_latest(params: dict, ctx: dict) -> dict:
    """El archivo más reciente de una carpeta del señor (p. ej. el último clip o grabación)."""
    sub = str(params.get("dir", "Videos/Clips"))
    base = (HOME / sub).resolve()
    if not any(str(base).startswith(str(HOME / d)) for d in BUSCAR_EN):
        return _err("bad_path", "solo carpetas del señor")
    fs = [p for p in base.glob("*") if p.is_file() and not p.name.endswith("-preview.png")]
    if not fs:
        return _err("empty", "no hay archivos")
    p = max(fs, key=lambda x: x.stat().st_mtime)
    return {"status": "ok", "path": str(p), "bytes": p.stat().st_size}


CARPETAS = {"documentos": "Documents", "descargas": "Downloads", "imagenes": "Pictures", "fotos": "Pictures",
            "capturas": "Pictures", "videos": "Videos", "clips": "Videos/Clips", "grabaciones": "Videos", "musica": "Music",
            "proyectos": "Proyectos", "escritorio": "Desktop", "obsidian": "Obsidian", "trabajo": "Work", "inicio": ""}


async def folder_open(params: dict, ctx: dict) -> dict:
    """«Abre mis proyectos» / «abre la carpeta X»: busca la carpeta por nombre en su carpeta personal y la abre."""
    q = _plain(params.get("q"))
    rel = CARPETAS.get(q)
    if rel is None:
        cands = []
        for raiz in [HOME] + [HOME / d for d in ("Proyectos", "Documents", "Projects", "Work", "Downloads")]:
            try:
                for p in raiz.iterdir():
                    if p.is_dir() and not p.name.startswith(".") and q and q in _plain(p.name):
                        cands.append(p)
            except OSError:
                continue
        if not cands:
            return _err("not_found", f"no encuentro la carpeta «{params.get('q')}»")
        destino = min(cands, key=lambda p: (len(p.parts), len(p.name)))
    else:
        destino = HOME / rel
    if not destino.is_dir():
        return _err("not_found", f"no existe {destino.name}")
    return {"status": "ok", "carpeta": str(destino), "pid": _launch(["xdg-open", str(destino)])}


async def window_active(params: dict, ctx: dict) -> dict:
    """«Minimiza / cierra esta ventana»: la de delante. Cerrar es como pulsar su ✕ (la app pregunta si hay algo sin guardar)."""
    acc = str(params.get("accion", ""))
    w = _hypr("activewindow") or {}
    if not w.get("address"):
        return _err("no_window", "no hay ninguna ventana delante")
    dirw = 'window = "address:%s"' % w["address"]
    if acc == "minimizar":
        ok = _lua('hl.dsp.window.move({ workspace = "special:minimized", follow = false, %s })' % dirw)
    elif acc == "cerrar":
        ok = _lua("hl.dsp.window.close({ %s })" % dirw)
    else:
        return _err("bad_param", "accion: minimizar|cerrar")
    return {"status": "ok" if ok else "error", "ventana": w.get("title", "")[:60], "clase": w.get("class", "")}


async def jarvis_status(params: dict, ctx: dict) -> dict:
    """Panel de JARVIS: estado de las piezas del PC (servicios, última actividad de la voz)."""
    serv = {}
    for u in ("jarvis-voz", "jarvis-agente", "jarvis-clip", "jarvis-descargas.timer", "jarvis-noche.timer"):
        serv[u] = _run(["systemctl", "--user", "is-active", u]).stdout.strip()
    serv["jarvis-ydotoold"] = _run(["systemctl", "is-active", "jarvis-ydotoold"]).stdout.strip()
    voz = []
    try:
        lineas = (HOME / "jarvis-repo/pc-windows/voz/jarvis_voz.log").read_text(encoding="utf-8", errors="replace").splitlines()
        voz = [ln[11:19] + " " + ln[24:][:90] for ln in lineas[-400:]
               if re.search(r"audio enviado|me llamo|modo juego|control de voz|voz usada|conectado al cerebro|interrumpido", ln)][-6:]
    except OSError:
        pass
    clips = sorted((HOME / "Videos/Clips").glob("*.mp4"), key=lambda p: p.stat().st_mtime) if (HOME / "Videos/Clips").exists() else []
    return {"status": "ok", "servicios": serv, "voz": voz,
            "ultimo_clip": time.strftime("%d/%m %H:%M", time.localtime(clips[-1].stat().st_mtime)) if clips else "",
            "dnd": _run(["omarchy-shell", "notifications", "isDnd"]).stdout.strip()}


OVERRIDES = {
    "screen.capture": screen_capture, "window.list": window_list, "window.focus": window_focus,
    "window.minimize": window_minimize, "window.maximize": window_maximize, "window.move": window_move,
    "clipboard.read": clipboard_read, "clipboard.write": clipboard_write,
    "ui.click": ui_click, "ui.keypress": ui_keypress,
    "media.play_pause": media_play_pause, "media.next": media_next, "media.previous": media_previous,
    "volume.get": volume_get, "volume.set": volume_set, "volume.mute": volume_mute,
    "system.lock": system_lock, "system.shutdown": system_shutdown, "system.restart": system_restart,
    "system.suspend": system_suspend,
    "apps.open": apps_open, "apps.close": apps_close,
}

EXTRA = [
    {"name": "apps.close_window", "params": {"app": "str"}, "risk": "medium",
     "timeout": 25, "module": "apps", "scope": "apps", "fn": apps_close_window},
    {"name": "web.open", "params": {"url": "str"}, "risk": "medium",
     "timeout": 15, "module": "apps", "scope": "apps", "fn": web_open},
    # scope media: como volumen, no necesita allowlist (solo avisos, perfil de energia y volumen)
    {"name": "game.mode", "params": {"on": "bool"}, "risk": "medium",
     "timeout": 20, "module": "media", "scope": "media", "fn": game_mode},
    {"name": "window.screen", "params": {"accion": "str"}, "risk": "medium", "timeout": 10, "module": "media",
     "scope": "media", "fn": window_screen},
    {"name": "files.latest", "params": {"dir": "str?"}, "risk": "low", "timeout": 10, "module": "desktop", "scope": "",
     "fn": files_latest},
    {"name": "screen.record", "params": {"on": "bool"}, "risk": "medium", "timeout": 40, "module": "media", "scope": "media",
     "fn": screen_record},
    {"name": "night.light", "params": {"on": "bool"}, "risk": "medium", "timeout": 10, "module": "media", "scope": "media",
     "fn": night_light},
    {"name": "ui.point", "params": {"x": "int", "y": "int"}, "risk": "medium", "timeout": 15, "module": "media",
     "scope": "media", "fn": ui_point},
    {"name": "folder.open", "params": {"q": "str"}, "risk": "medium", "timeout": 15, "module": "media", "scope": "media",
     "fn": folder_open},
    {"name": "window.active", "params": {"accion": "str"}, "risk": "medium", "timeout": 10, "module": "media",
     "scope": "media", "fn": window_active},
    {"name": "jarvis.status", "params": {}, "risk": "low", "timeout": 15, "module": "system", "scope": "",
     "fn": jarvis_status},
    {"name": "system.health", "params": {}, "risk": "low", "timeout": 60, "module": "system", "scope": "", "fn": system_health},
    {"name": "games.time", "params": {"dias": "int?"}, "risk": "low", "timeout": 10, "module": "media", "scope": "",
     "fn": games_time},
    {"name": "music.now", "params": {}, "risk": "low", "timeout": 10, "module": "media", "scope": "", "fn": music_now},
    {"name": "focus.mode", "params": {"min": "int"}, "risk": "medium", "timeout": 15, "module": "media", "scope": "media",
     "fn": focus_mode},
    # leer lo seleccionado es como leer el portapapeles: HIGH (concesion firmada)
    {"name": "selection.read", "params": {}, "risk": "high", "timeout": 10, "module": "desktop", "scope": "",
     "fn": selection_read},
    {"name": "clip.save", "params": {}, "risk": "medium", "timeout": 10, "module": "media", "scope": "media", "fn": clip_save},
    {"name": "music.play", "params": {"q": "str?"}, "risk": "medium", "timeout": 10, "module": "media", "scope": "media",
     "fn": music_play},
    {"name": "files.find", "params": {"q": "str"}, "risk": "low", "timeout": 20, "module": "desktop", "scope": "",
     "fn": files_find},
    # escribir en la ventana y sacar archivos del PC: HIGH (concesion firmada del cerebro, como ui.keypress)
    {"name": "ui.type", "params": {"text": "str"}, "risk": "high", "timeout": 60, "module": "desktop", "scope": "",
     "fn": ui_type},
    {"name": "files.send", "params": {"path": "str"}, "risk": "high", "timeout": 120, "module": "desktop", "scope": "",
     "fn": files_send},
]
