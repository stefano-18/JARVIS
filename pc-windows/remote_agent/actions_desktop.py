"""Acciones desktop avanzadas (computer use): captura, ventanas, portapapeles.

Riesgos (ver actions.py / policy.py):
  screen.capture    HIGH (expone informacion visual sensible)
  window.list       LOW  (solo enumeracion, como process.list)
  window.focus/minimize/maximize HIGH (alteran estado / pueden robar foco)
  clipboard.read/write   HIGH (puede contener contrasenas; siempre con
    concesion firmada, sin excepcion)

Todas fluyen por execute_action -> AuditLog igual que el resto de
acciones (hash-chain en audit.jsonl). Retornan status ok SOLO si el SO
hizo de verdad lo pedido; si no, status error honesto.
"""
import asyncio
import base64
import io
import time

try:
    import mss as _mss
    import mss.tools as _mss_tools
except Exception:
    _mss = None
    _mss_tools = None

try:
    from PIL import Image as _PILImage, ImageGrab as _ImageGrab
except Exception:
    _PILImage = None
    _ImageGrab = None

try:
    import win32gui as _gui
    import win32con as _con
    import win32process as _wproc
    import win32clipboard as _clip
    import win32api as _api
except Exception:
    _gui = _con = _wproc = _clip = _api = None

try:
    import psutil as _psutil
except Exception:
    _psutil = None


def _err(code: str, msg: str, **extra) -> dict:
    """Error honesto: texto nunca vacio + codigo estable."""
    msg = (msg or "").strip() or f"error desconocido ({code})"
    d = {"status": "error", "error": msg[:200], "code": code}
    d.update(extra)
    return d


def _need_gui():
    if _gui is None or _con is None:
        return _err("gui_unavailable",
                    "API Win32 no disponible (pywin32 ausente o SO no Windows)",
                    executed=False)
    return None


# --- Captura de pantalla ---

def _shot_mss(monitor: int):
    """Retorna (rgb_bytes, (w, h)). monitor: 1=primario (mss[0]=todo)."""
    with _mss.mss() as sct:
        mons = sct.monitors
        if monitor < 0 or monitor >= len(mons):
            raise ValueError(f"monitor {monitor} fuera de rango (0..{len(mons) - 1})")
        shot = sct.grab(mons[monitor])
        return shot.rgb, shot.size


def _shot_pil():
    if _ImageGrab is None:
        raise RuntimeError("ni mss ni PIL disponibles para captura")
    img = _ImageGrab.grab()
    return img.tobytes(), img.size, img.mode


async def screen_capture(params: dict, ctx: dict) -> dict:
    """Captura pantalla -> PNG/JPEG base64. Solo llega aqui con concesion.

    FASE C1 (detras de SCREEN_C1=1): monitor + max_width (defecto 1280) +
    JPEG quality (defecto 70) con tope 1MB. Retorna
    {data_b64, width, height, mime} (+status/bytes). HIGH ya auditada.
    """
    c1 = str((ctx or {}).get("screen_c1", "0")) == "1"
    fmt = str(params.get("format", "jpeg" if c1 else "png")).lower()
    if fmt not in ("png", "jpeg", "jpg"):
        return {"status": "error", "code": "bad_format", "executed": False,
                "error": f"format debe ser png|jpeg, no '{fmt}'"}
    if fmt == "jpg":
        fmt = "jpeg"
    monitor = params.get("monitor", 1)
    try:
        monitor = int(monitor)
    except Exception:
        return {"status": "error", "code": "bad_monitor", "executed": False,
                "error": f"monitor debe ser int, no {monitor!r}"}
    max_w = params.get("max_width", 1280 if c1 else None)
    if max_w is not None:
        try:
            max_w = int(max_w)
        except Exception:
            return {"status": "error", "code": "bad_param", "executed": False,
                    "error": f"max_width debe ser int, no {max_w!r}"}
    try:
        quality = int(params.get("quality", 70 if c1 else 75))
    except Exception:
        return {"status": "error", "code": "bad_param", "executed": False,
                "error": "quality debe ser int"}
    quality = max(10, min(95, quality))
    CAP = 1024 * 1024 if c1 else None
    try:
        if _mss is not None:
            rgb, (w, h) = await asyncio.to_thread(_shot_mss, monitor)
            if _PILImage is None:
                if fmt != "png" or (max_w is not None and w > max_w):
                    return {"status": "error", "code": "no_backend", "executed": False,
                            "error": "se necesita Pillow para jpeg/resize (solo mss presente)"}
                raw = _mss_tools.to_png(rgb, (w, h))
            else:
                img = _PILImage.frombytes("RGB", (w, h), rgb)
                if max_w is not None and w > max_w:
                    img = img.resize((max_w, int(h * max_w / w)), _PILImage.LANCZOS)
                    w, h = img.size
                buf = io.BytesIO()
                if fmt == "jpeg":
                    img.save(buf, "JPEG", quality=quality)
                else:
                    img.save(buf, "PNG")
                raw = buf.getvalue()
        elif _PILImage is not None:
            if monitor not in (0, 1):
                return {"status": "error", "code": "bad_monitor", "executed": False,
                        "error": "PIL solo captura el primario (monitor 0|1)"}
            rgb, (w, h), mode = await asyncio.to_thread(_shot_pil)
            img = _PILImage.frombytes(mode, (w, h), rgb).convert("RGB")
            if max_w is not None and w > max_w:
                img = img.resize((max_w, int(h * max_w / w)), _PILImage.LANCZOS)
                w, h = img.size
            buf = io.BytesIO()
            img.save(buf, "JPEG" if fmt == "jpeg" else "PNG",
                     quality=quality)
            raw = buf.getvalue()
        else:
            return {"status": "error", "code": "no_backend", "executed": False,
                    "error": "sin backend de captura (instala mss o pillow)"}
    except ValueError as e:
        msg = str(e)[:200]
        low = msg.lower()
        if "monitor" in low or "rango" in low or "fuera" in low:
            return {"status": "error", "code": "bad_monitor", "executed": False, "error": msg}
        return {"status": "error", "code": "action_failed", "executed": False, "error": msg}
    except Exception as e:
        return {"status": "error", "code": "capture_failed", "executed": False,
                "error": f"captura fallo: {type(e).__name__}: {str(e)[:200]}"}
    if CAP is not None and fmt == "jpeg" and len(raw) > CAP and _PILImage is not None:
        try:
            img = _PILImage.open(io.BytesIO(raw)).convert("RGB")
            w0, h0 = img.size
            for q in (quality, 60, 50, 40):
                for ww in (w0, 1280, 960, 640):
                    if ww < w0:
                        ih = _PILImage.frombytes(
                            "RGB", img.size,
                            img.tobytes()).resize(
                            (ww, int(h0 * ww / w0)), _PILImage.LANCZOS)
                    else:
                        ih = img
                    b = io.BytesIO()
                    ih.save(b, "JPEG", quality=int(q))
                    raw = b.getvalue()
                    w, h = ih.size
                    if len(raw) <= CAP:
                        break
                if len(raw) <= CAP:
                    break
        except Exception:
            pass
        if len(raw) > CAP:
            return {"status": "error", "code": "too_large",
                    "executed": False,
                    "error": f"captura supera tope 1MB ({len(raw)} bytes)"}
    return {"status": "ok", "mime": f"image/{fmt}", "width": w, "height": h,
            "bytes": len(raw),
            "data_b64": base64.b64encode(raw).decode("ascii")}


# --- Ventanas ---

def _enum_windows():
    out = []

    def cb(hwnd, _):
        try:
            title = _gui.GetWindowText(hwnd)
        except Exception:
            title = ""
        try:
            vis = bool(_gui.IsWindowVisible(hwnd))
        except Exception:
            vis = False
        try:
            _, pid = _wproc.GetWindowThreadProcessId(hwnd)
        except Exception:
            pid = -1
        exe = None
        if _psutil is not None and pid > 0:
            try:
                exe = _psutil.Process(pid).name()
            except Exception:
                exe = None
        out.append({"hwnd": hwnd, "title": title, "pid": pid,
                    "process": exe, "visible": vis})
        return True

    _gui.EnumWindows(cb, None)
    return out


async def window_list(params: dict, ctx: dict) -> dict:
    miss = _need_gui()
    if miss:
        return miss
    try:
        wins = await asyncio.to_thread(_enum_windows)
    except Exception as e:
        return {"status": "error", "code": "enumerate_failed",
                "error": f"enumerar fallo: {type(e).__name__}: {str(e)[:200]}"}
    vis = [w for w in wins if w["visible"] and w["title"]]
    return {"status": "ok", "count_total": len(wins),
            "count_visible_titled": len(vis), "windows": vis}


def _find_window(params: dict):
    """Busca por hwnd exacto o subcadena de titulo. Retorna (hwnd, error)."""
    wins = _enum_windows()
    if "hwnd" in params and params["hwnd"] is not None:
        try:
            hwnd = int(params["hwnd"])
        except Exception:
            return None, f"hwnd debe ser int, no {params['hwnd']!r}"
        if not _gui.IsWindow(hwnd):
            return None, f"hwnd {hwnd} no existe"
        return hwnd, None
    if "title" in params and params["title"]:
        needle = str(params["title"]).lower()
        for w in wins:
            if w["visible"] and needle in (w["title"] or "").lower():
                return w["hwnd"], None
        return None, f"ninguna ventana visible contiene '{params['title']}'"
    return None, "pasa hwnd (int) o title (subcadena)"


async def window_focus(params: dict, ctx: dict) -> dict:
    """Restaura y da foco. HIGH: solo con concesion. ok SOLO si queda en primer plano."""
    miss = _need_gui()
    if miss:
        return miss
    try:
        found = await asyncio.to_thread(_find_window, params)
    except Exception as e:
        return {"status": "error", "code": "lookup_failed", "executed": False,
                "error": f"buscar fallo: {type(e).__name__}: {str(e)[:200]}"}
    hwnd, err = found
    if err:
        return {"status": "error", "code": "window_not_found", "executed": False, "error": err}
    try:
        def _do():
            if _gui.IsIconic(hwnd):
                _gui.ShowWindow(hwnd, _con.SW_RESTORE)
            _gui.SetForegroundWindow(hwnd)
            _gui.BringWindowToTop(hwnd)
            return _gui.GetForegroundWindow() == hwnd
        fg_ok = await asyncio.to_thread(_do)
    except Exception as e:
        return {"status": "error", "code": "focus_failed", "executed": False,
                "error": f"foco fallo: {type(e).__name__}: {str(e)[:200]}"}
    if not fg_ok:
        return {"status": "error", "code": "focus_failed", "executed": False, "hwnd": hwnd,
                "error": "el SO no cedio el primer plano (politica de foreground de Windows). "
                         "La ventana pudo restaurarse pero NO tiene el foco."}
    return {"status": "ok", "hwnd": hwnd, "foreground": True}


async def window_minimize(params: dict, ctx: dict) -> dict:
    miss = _need_gui()
    if miss:
        return miss
    try:
        found = await asyncio.to_thread(_find_window, params)
    except Exception as e:
        return {"status": "error", "code": "lookup_failed", "executed": False,
                "error": f"buscar fallo: {type(e).__name__}: {str(e)[:200]}"}
    hwnd, err = found
    if err:
        return {"status": "error", "code": "window_not_found", "executed": False, "error": err}
    try:
        await asyncio.to_thread(_gui.ShowWindow, hwnd, _con.SW_MINIMIZE)
        iconic = await asyncio.to_thread(_gui.IsIconic, hwnd)
    except Exception as e:
        return {"status": "error", "code": "minimize_failed", "executed": False,
                "error": f"minimizar fallo: {type(e).__name__}: {str(e)[:200]}"}
    if not iconic:
        return {"status": "error", "code": "minimize_failed", "executed": False, "hwnd": hwnd,
                "error": "ShowWindow no minimizo la ventana"}
    return {"status": "ok", "hwnd": hwnd, "minimized": True}


async def window_maximize(params: dict, ctx: dict) -> dict:
    miss = _need_gui()
    if miss:
        return miss
    try:
        found = await asyncio.to_thread(_find_window, params)
    except Exception as e:
        return {"status": "error", "code": "lookup_failed", "executed": False,
                "error": f"buscar fallo: {type(e).__name__}: {str(e)[:200]}"}
    hwnd, err = found
    if err:
        return {"status": "error", "code": "window_not_found", "executed": False, "error": err}
    try:
        await asyncio.to_thread(_gui.ShowWindow, hwnd, _con.SW_MAXIMIZE)
        placed = await asyncio.to_thread(_gui.GetWindowPlacement, hwnd)
        zoomed = placed[1] == _con.SW_SHOWMAXIMIZED
    except Exception as e:
        return {"status": "error", "code": "maximize_failed", "executed": False,
                "error": f"maximizar fallo: {type(e).__name__}: {str(e)[:200]}"}
    if not zoomed:
        return {"status": "error", "code": "maximize_failed", "executed": False, "hwnd": hwnd,
                "error": "ShowWindow no maximizo la ventana"}
    return {"status": "ok", "hwnd": hwnd, "maximized": True}


# --- Portapapeles (HIGH siempre) ---

def _clip_open():
    last = None
    for _ in range(6):
        try:
            _clip.OpenClipboard(None)
            return
        except Exception as e:
            last = e
            time.sleep(0.05)
    raise RuntimeError(f"portapapeles bloqueado: {last}")


async def clipboard_read(params: dict, ctx: dict) -> dict:
    """Lee texto. HIGH: solo con concesion. Nunca loguea el contenido aqui
    (el audit del agente solo guarda el resultado ok/error, no el texto)."""
    miss = _need_gui()
    if miss:
        return miss
    if _clip is None:
        return {"status": "error", "code": "clipboard_unavailable", "executed": False,
                "error": "win32clipboard no disponible"}
    try:
        def _do():
            _clip_open()
            try:
                if not _clip.IsClipboardFormatAvailable(_con.CF_UNICODETEXT):
                    return None
                return _clip.GetClipboardData(_con.CF_UNICODETEXT)
            finally:
                _clip.CloseClipboard()
        text = await asyncio.to_thread(_do)
    except Exception as e:
        return {"status": "error", "code": "clipboard_failed", "executed": False,
                "error": f"leer fallo: {type(e).__name__}: {str(e)[:200]}"}
    if text is None:
        return {"status": "error", "code": "clipboard_empty", "executed": False,
                "error": "portapapeles sin texto (vacio o formato no textual)"}
    return {"status": "ok", "chars": len(text), "text": text}


async def clipboard_write(params: dict, ctx: dict) -> dict:
    miss = _need_gui()
    if miss:
        return miss
    if _clip is None:
        return {"status": "error", "code": "clipboard_unavailable", "executed": False,
                "error": "win32clipboard no disponible"}
    if "text" not in params or params["text"] is None:
        return {"status": "error", "code": "missing_text", "executed": False,
                "error": "falta param text (str)"}
    text = str(params["text"])
    try:
        def _do():
            _clip_open()
            try:
                _clip.EmptyClipboard()
                _clip.SetClipboardData(_con.CF_UNICODETEXT, text)
            finally:
                _clip.CloseClipboard()
        await asyncio.to_thread(_do)
    except Exception as e:
        return {"status": "error", "code": "clipboard_failed", "executed": False,
                "error": f"escribir fallo: {type(e).__name__}: {str(e)[:200]}"}
    return {"status": "ok", "chars": len(text)}


# --- Mover ventanas (HIGH) ---

async def window_move(params: dict, ctx: dict) -> dict:
    """Mueve (y opcionalmente redimensiona). HIGH: solo con concesion.
    Params: {hwnd|title, x, y, w?, h?}. Sin w/h se conserva el tamano."""
    miss = _need_gui()
    if miss:
        return miss
    for k in ("x", "y"):
        if k not in params or params[k] is None:
            return {"status": "error", "code": "missing_param", "executed": False,
                    "error": f"falta param {k} (int)"}
    try:
        x, y = int(params["x"]), int(params["y"])
    except Exception:
        return {"status": "error", "code": "bad_param", "executed": False,
                "error": "x/y deben ser int"}
    w = h = None
    if params.get("w") is not None or params.get("h") is not None:
        if params.get("w") is None or params.get("h") is None:
            return {"status": "error", "code": "bad_param", "executed": False,
                    "error": "w y h van juntos (o ninguno)"}
        try:
            w, h = int(params["w"]), int(params["h"])
        except Exception:
            return {"status": "error", "code": "bad_param", "executed": False,
                    "error": "w/h deben ser int"}
        if w <= 0 or h <= 0:
            return {"status": "error", "code": "bad_param", "executed": False,
                    "error": "w/h deben ser > 0"}
    try:
        found = await asyncio.to_thread(_find_window, params)
    except Exception as e:
        return {"status": "error", "code": "lookup_failed", "executed": False,
                "error": f"buscar fallo: {type(e).__name__}: {str(e)[:200]}"}
    hwnd, err = found
    if err:
        return {"status": "error", "code": "window_not_found", "executed": False, "error": err}
    try:
        def _do():
            if w is None:
                l, t, r, b = _gui.GetWindowRect(hwnd)
                ww, hh = r - l, b - t
            else:
                ww, hh = w, h
            _gui.SetWindowPos(hwnd, 0, x, y, ww, hh,
                              _con.SWP_NOZORDER | _con.SWP_NOACTIVATE)
            return _gui.GetWindowRect(hwnd)
        l, t, r, b = await asyncio.to_thread(_do)
    except Exception as e:
        return {"status": "error", "code": "move_failed", "executed": False,
                "error": f"mover fallo: {type(e).__name__}: {str(e)[:200]}"}
    if (l, t) != (x, y) or (w is not None and (r - l, b - t) != (w, h)):
        return {"status": "error", "code": "move_failed", "executed": False, "hwnd": hwnd,
                "rect": [l, t, r, b],
                "error": "SetWindowPos no dejo la ventana donde se pidio"}
    return {"status": "ok", "hwnd": hwnd, "rect": [l, t, r, b]}


# --- Clic de mouse (HIGH) ---

_MOUSE_BTN = {
    "left": ("MOUSEEVENTF_LEFTDOWN", "MOUSEEVENTF_LEFTUP"),
    "right": ("MOUSEEVENTF_RIGHTDOWN", "MOUSEEVENTF_RIGHTUP"),
    "middle": ("MOUSEEVENTF_MIDDLEDOWN", "MOUSEEVENTF_MIDDLEUP"),
}


async def ui_click(params: dict, ctx: dict) -> dict:
    """Clic en coordenadas de pantalla. HIGH: solo con concesion.
    Params: {x, y, button?} button=left|right|middle (default left).
    Fuera de pantalla virtual -> error (no se ejecuta nada)."""
    miss = _need_gui()
    if miss:
        return miss
    if _api is None:
        return {"status": "error", "code": "gui_unavailable", "executed": False,
                "error": "win32api no disponible"}
    for k in ("x", "y"):
        if k not in params or params[k] is None:
            return {"status": "error", "code": "missing_param", "executed": False,
                    "error": f"falta param {k} (int)"}
    try:
        x, y = int(params["x"]), int(params["y"])
    except Exception:
        return {"status": "error", "code": "bad_param", "executed": False,
                "error": "x/y deben ser int"}
    button = str(params.get("button", "left")).lower()
    if button not in _MOUSE_BTN:
        return {"status": "error", "code": "bad_button", "executed": False,
                "error": f"button debe ser left|right|middle, no '{button}'"}
    try:
        def _do():
            vx = _api.GetSystemMetrics(_con.SM_XVIRTUALSCREEN)
            vy = _api.GetSystemMetrics(_con.SM_YVIRTUALSCREEN)
            vw = _api.GetSystemMetrics(_con.SM_CXVIRTUALSCREEN)
            vh = _api.GetSystemMetrics(_con.SM_CYVIRTUALSCREEN)
            if not (vx <= x < vx + vw and vy <= y < vy + vh):
                return False
            dn, up = (getattr(_con, n) for n in _MOUSE_BTN[button])
            _api.SetCursorPos((x, y))
            _api.mouse_event(dn, 0, 0, 0, 0)
            time.sleep(0.05)
            _api.mouse_event(up, 0, 0, 0, 0)
            return True
        inside = await asyncio.to_thread(_do)
    except Exception as e:
        return {"status": "error", "code": "click_failed", "executed": False,
                "error": f"clic fallo: {type(e).__name__}: {str(e)[:200]}"}
    if not inside:
        return {"status": "error", "code": "out_of_bounds", "executed": False,
                "error": f"({x},{y}) fuera de la pantalla virtual: no se hizo clic"}
    return {"status": "ok", "x": x, "y": y, "button": button}


# --- Pulsacion de teclas (HIGH) ---
#
# Formato EXACTO de `keys` (contrato para la laptop):
#   "<tecla>"               ej. "a", "A", "5", "Enter", "F5", "Esc"
#   "<mod>+...+<tecla>"     ej. "ctrl+s", "ctrl+shift+t", "alt+F4", "win+r"
# Reglas:
#   - Tokens separados por "+". El ULTIMO es la tecla principal; los
#     anteriores deben ser modificadores (ctrl/alt/shift/win).
#   - Un token de 1 caracter = esa tecla (layout via VkKeyScan).
#   - Nombres (case-insensitive): enter tab esc space backspace delete
#     insert home end pgup pgdn up down left right f1..f24 capslock
#     printscreen pause apps, mas modificadores ctrl alt shift win
#     (alias: control=ctrl, escape=esc, del=delete, ins=insert,
#     super=win, menu=apps).
#   - Para ESCRIBIR TEXTO literal: una llamada por caracter (o la laptop
#     trocea). Un token multicaracter desconocido es ERROR, no se adivina.

_VK_MODS = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10,
            "win": 0x5B, "super": 0x5B, "meta": 0x5B}
_VK_NAMES = {
    "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D, "ins": 0x2D, "home": 0x24, "end": 0x23,
    "pgup": 0x21, "pgdn": 0x22, "up": 0x26, "down": 0x28,
    "left": 0x25, "right": 0x27, "capslock": 0x14,
    "printscreen": 0x2C, "pause": 0x13, "apps": 0x5D, "menu": 0x5D,
}
_VK_MODS_NORM = {"control": "ctrl", "super": "win", "meta": "win",
                 "escape": "esc", "del": "delete", "ins": "insert",
                 "menu": "apps"}
_KEYEVENTF_KEYUP = 0x0002


def _resolve_key(name: str):
    """Retorna (vk, need_shift) o (None, motivo_error)."""
    if len(name) == 1:
        try:
            scan = _api.VkKeyScan(name)
        except Exception as e:
            return None, f"VkKeyScan fallo: {e}"
        if scan == -1:
            return None, f"caracter '{name}' no mapeable en este layout"
        return scan & 0xFF, bool((scan >> 8) & 1)
    low = name.lower()
    if low in _VK_MODS:
        return _VK_MODS[low], False
    if low in _VK_NAMES:
        return _VK_NAMES[low], False
    if low.startswith("f") and low[1:].isdigit():
        n = int(low[1:])
        if 1 <= n <= 24:
            return 0x6F + n, False
    return None, (f"tecla '{name}' desconocida. Formato: "
                  "'<tecla>' o '<mod>+...+<tecla>' (ver docstring)")


async def ui_keypress(params: dict, ctx: dict) -> dict:
    """Simula pulsacion. HIGH: solo con concesion. Ver formato en docstring."""
    miss = _need_gui()
    if miss:
        return miss
    if _api is None:
        return {"status": "error", "code": "gui_unavailable", "executed": False,
                "error": "win32api no disponible"}
    keys = params.get("keys")
    if not keys or not str(keys).strip():
        return {"status": "error", "code": "missing_param", "executed": False,
                "error": "falta param keys (ver formato en docstring)"}
    tokens = [t for t in str(keys).split("+") if t]
    if not tokens:
        return {"status": "error", "code": "missing_param", "executed": False,
                "error": "keys vacio tras partir por '+'"}
    *mod_names, main_name = tokens
    mods = []
    for m in mod_names:
        if m.lower() not in _VK_MODS:
            return {"status": "error", "code": "bad_modifier", "executed": False,
                    "error": f"modificador invalido '{m}': usa solo "
                             "ctrl/alt/shift/win antes de la tecla final"}
        mods.append((_VK_MODS_NORM.get(m.lower(), m.lower()), _VK_MODS[m.lower()]))
    vk_main, shift_needed = _resolve_key(main_name)
    if vk_main is None:
        return {"status": "error", "code": "unknown_key", "executed": False, "error": shift_needed}
    pressed = [n for n, _ in mods] + [main_name]
    try:
        def _do():
            seq = []
            for _, vk in mods:
                _api.keybd_event(vk, 0, 0, 0)
                seq.append((vk, "down"))
            if shift_needed and all(v != 0x10 for _, v in mods):
                _api.keybd_event(0x10, 0, 0, 0)
                seq.append((0x10, "down(auto)"))
            _api.keybd_event(vk_main, 0, 0, 0)
            seq.append((vk_main, "down"))
            time.sleep(0.03)
            _api.keybd_event(vk_main, 0, _KEYEVENTF_KEYUP, 0)
            seq.append((vk_main, "up"))
            if shift_needed and all(v != 0x10 for _, v in mods):
                _api.keybd_event(0x10, 0, _KEYEVENTF_KEYUP, 0)
                seq.append((0x10, "up(auto)"))
            for _, vk in reversed(mods):
                _api.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)
                seq.append((vk, "up"))
            return seq
        seq = await asyncio.to_thread(_do)
    except Exception as e:
        return {"status": "error", "code": "keypress_failed", "executed": False,
                "error": f"keypress fallo: {type(e).__name__}: {str(e)[:200]}"}
    return {"status": "ok", "keys": str(keys), "pressed": pressed,
            "events": len(seq)}
