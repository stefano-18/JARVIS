"""
JARVIS Bridge Executor (ESTE PC / puente).
Conecta al WebSocket de la LAPTOP y ejecuta acciones LOCALES cuando el cerebro lo ordena.

Protocolo:
  Laptop → este PC : {"type": "pc_exec", "id": "<uuid>", "tool": "open_application", "args": {...}}
  Este PC → laptop : {"type": "pc_result", "id": "<uuid>", "ok": true, "result": "..."}

También acepta el legacy {"type": "pc_action", "action": "shutdown|restart|lock"}.

Arranque:
  .\\.venv-agent\\Scripts\\python.exe agent\\bridge_executor.py --ws ws://IP_LAPTOP:8765

No instala nada nuevo: solo stdlib + psutil/pillow/pyautogui (ya presentes).
Nada de IA aquí: el cerebro (OpenRouter) corre en la laptop.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from ws_client import DEFAULT_WS_URL, JarvisWsClient

try:
    from pc_control import execute_power_action  # reutiliza shutdown/restart/lock
except Exception:
    execute_power_action = None  # type: ignore

try:
    from games import list_games as _list_games, open_game as _open_game
except Exception:
    _list_games, _open_game = None, None  # type: ignore

logger = logging.getLogger(__name__)

ALLOWED_APPS = {
    "discord": "Discord.exe", "chrome": "chrome.exe", "firefox": "firefox.exe",
    "spotify": "Spotify.exe", "steam": "Steam.exe",
    "minecraft": "MinecraftLauncher.exe", "notepad": "notepad.exe",
    "calculator": "calc.exe", "calculadora": "calc.exe",
    "explorer": "explorer.exe", "explorador": "explorer.exe",
    "vscode": "Code.exe", "terminal": "wt.exe",
}
PROTECTED = {"explorer.exe", "wininit.exe", "csrss.exe", "smss.exe", "services.exe",
             "lsass.exe", "svchost.exe", "dwm.exe"}


def t_open_application(app: str) -> str:
    key = (app or "").strip().lower()
    exe = ALLOWED_APPS.get(key, f"{app}.exe" if not app.lower().endswith(".exe") else app)
    target = shutil.which(exe) or exe
    try:
        if os.name == "nt" and target.lower().endswith(".exe") and os.path.isabs(target):
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.Popen([target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return f"Abriendo {app}."
    except Exception as e:
        return f"ERROR: no pude abrir '{app}': {e}"


def t_close_application(app: str) -> str:
    key = (app or "").strip().lower()
    exe = ALLOWED_APPS.get(key, f"{app}.exe")
    if exe.lower() in PROTECTED:
        return f"BLOQUEADO: '{exe}' es crítico del sistema."
    try:
        r = subprocess.run(["taskkill", "/IM", exe], capture_output=True, text=True, timeout=15)
        return f"Cierre {app}: {((r.stdout or '') + (r.stderr or '')).strip() or 'ok'}"
    except Exception as e:
        return f"ERROR al cerrar '{app}': {e}"


def t_open_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return "ERROR: URL vacía."
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    webbrowser.open(u)
    return f"Abriendo {u}."


def t_search_web(query: str) -> str:
    from urllib.parse import quote_plus
    return t_open_url(f"https://www.google.com/search?q={quote_plus((query or '').strip())}")


def t_system_stats() -> str:
    import psutil
    import shutil as _sh
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    du = _sh.disk_usage("C:\\")
    gpu = "n/d"
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            gpu = r.stdout.strip()
    except Exception:
        pass
    return (f"CPU {cpu:.0f}% | RAM {ram.percent:.0f}% | "
            f"Disco C {du.used / 2**30:.0f}/{du.total / 2**30:.0f}GB | GPU {gpu}")


def t_set_volume(action: str) -> str:
    import ctypes
    MUTE, DOWN, UP = 0xAD, 0xAE, 0xAF

    def key(vk: int) -> None:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)

    a = (action or "mute").strip().lower()
    if a in ("mute", "unmute"):
        key(MUTE)
        return "Volumen: mute alternado."
    if a == "up":
        key(UP)
        return "Volumen: subido."
    if a == "down":
        key(DOWN)
        return "Volumen: bajado."
    return "ERROR: action debe ser mute|up|down."


def t_media() -> str:
    import ctypes
    ctypes.windll.user32.keybd_event(0xB3, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0xB3, 0, 2, 0)
    return "Play/pausa alternado."


def t_spotify_play(query: str = "") -> str:
    """Abre Spotify y reproduce: sin query = play (retoma lo último);
    con query = abre búsqueda spotify:search:query y da play (best effort)."""
    import time as _t
    from urllib.parse import quote as _q

    t_open_application("spotify")
    _t.sleep(1.5)
    q = (query or "").strip()
    if q:
        try:
            webbrowser.open("spotify:search:" + _q(q))
            _t.sleep(2.0)
        except Exception as e:
            return f"Spotify abierto, pero falló la búsqueda: {e}"
    t_media()
    return f"Reproduciendo {q or 'música'} en Spotify."


def t_screenshot() -> str:
    from PIL import ImageGrab
    p = Path.home() / "Pictures" / "jarvis_screenshot.png"
    ImageGrab.grab().save(p)
    return f"Captura guardada en {p}."


def t_type_text(text: str) -> str:
    import pyautogui
    pyautogui.typewrite(text or "", interval=0.01)
    return "Texto escrito."


def t_press_key(key: str) -> str:
    import pyautogui
    pyautogui.press((key or "enter").strip().lower())
    return f"Tecla '{key}' pulsada."


def t_list_apps() -> str:
    """Lista apps de usuario con ventana visible en el PC fijo (para 'qué apps tengo abiertas').

    Estrategia rápida (<1s): Get-Process con MainWindowTitle, sin psutil pesado.
    Retorna lista corta legible para el LLM/voz.
    """
    import subprocess as _sp
    try:
        ps = (
            "Get-Process | Where-Object { $_.MainWindowTitle -ne '' } | "
            "Select-Object -ExpandProperty ProcessName | Sort-Object -Unique"
        )
        r = _sp.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                     "-ExecutionPolicy", "Bypass", "-Command", ps],
                    capture_output=True, text=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        names = [n.strip() for n in (r.stdout or "").splitlines() if n.strip()]
        # Filtrar shell del sistema, quedarse con apps de usuario
        _hide = {"systemsettings", "shellexperiencehost", "startmenuexperiencehost",
                 "searchhost", "textinputhost", "applicationframehost"}
        apps = [n for n in names if n.lower() not in _hide][:30]
        if not apps:
            return "No se detectaron apps con ventana abierta."
        return f"Apps abiertas ({len(apps)}): " + ", ".join(apps)
    except Exception as e:
        return f"ERROR listando apps: {e}"


def t_media_next() -> str:
    import ctypes
    ctypes.windll.user32.keybd_event(0xB0, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0xB0, 0, 2, 0)
    return "Pista siguiente."


def t_media_prev() -> str:
    import ctypes
    ctypes.windll.user32.keybd_event(0xB1, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0xB1, 0, 2, 0)
    return "Pista anterior."


def t_list_games() -> str:
    if _list_games is None:
        return "ERROR: games.py no disponible."
    try:
        games = _list_games()
    except Exception as e:
        return f"ERROR listando juegos: {e}"
    if not games:
        return "No se encontraron juegos. Verifica Steam steamapps/*.acf y Epic ProgramData/Epic/*.item"
    lines = [f"- {g['name']} ({g['platform']}:{g['id']})" for g in games]
    return f"Juegos instalados ({len(games)}):\n" + "\n".join(lines)


def t_open_game(game: str) -> str:
    if _open_game is None:
        return "ERROR: games.py no disponible."
    return _open_game(game or "")


TOOLS = {
    "open_application": lambda a: t_open_application(a.get("app", "")),
    "close_application": lambda a: t_close_application(a.get("app", "")),
    "open_url": lambda a: t_open_url(a.get("url", "")),
    "search_web": lambda a: t_search_web(a.get("query", "")),
    "system_stats": lambda a: t_system_stats(),
    "set_volume": lambda a: t_set_volume(a.get("action", "mute")),
    "media_play_pause": lambda a: t_media(),
    "spotify_play": lambda a: t_spotify_play(a.get("query", "") or a.get("q", "") or ""),
    "media_next": lambda a: t_media_next(),
    "media_prev": lambda a: t_media_prev(),
    "list_open_apps": lambda a: t_list_apps(),
    "take_screenshot": lambda a: t_screenshot(),
    "type_text": lambda a: t_type_text(a.get("text", "")),
    "press_key": lambda a: t_press_key(a.get("key", "")),
    "list_games": lambda a: t_list_games(),
    "open_game": lambda a: t_open_game(a.get("game", "") or a.get("name", "") or a.get("app", "")),
}


def execute(tool: str, args: dict) -> str:
    fn = TOOLS.get(tool)
    if not fn:
        # power legacy por nombre de tool
        if tool in ("shutdown", "restart", "lock") and execute_power_action:
            return execute_power_action(tool)
        return f"ERROR: herramienta desconocida '{tool}'."
    try:
        return fn(args or {})
    except Exception as e:
        return f"ERROR en {tool}: {e}"


def main() -> None:
    ap = argparse.ArgumentParser(description="JARVIS bridge executor (este PC)")
    ap.add_argument("--ws", default=DEFAULT_WS_URL, help="WS de la laptop, ej. ws://{{RED}}.X:8765")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    client = JarvisWsClient(args.ws)

    def on_message(data: dict) -> None:
        if data.get("type") == "pc_exec" and data.get("id"):
            tool, margs = data.get("tool", ""), data.get("args", {}) or {}
            logger.info("pc_exec %s %s", tool, margs)
            result = execute(tool, margs)
            client.send_json({"type": "pc_result", "id": data["id"],
                              "ok": not result.startswith("ERROR"),
                              "result": result})
            client.send_subtitle(result)
        elif data.get("type") == "pc_action":
            action = str(data.get("action", "")).lower()
            if execute_power_action and action in ("shutdown", "restart", "lock"):
                client.send_subtitle(execute_power_action(action))

    client.on_message = on_message
    client.start()
    logger.info("Bridge executor conectado a %s. Esperando órdenes de la laptop...", args.ws)
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        client.stop()


if __name__ == "__main__":
    main()
