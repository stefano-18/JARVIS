"""
JARVIS games.py generico (PC fijo).
Escanea Steam steamapps/*.acf + libraryfolders.vdf y Epic ProgramData/*.item.
Expone list_games() / open_game(query) con fuzzy + ALIASES + fallback IDs conocidos.
Destino PC fijo: {{WIN_HOME_ESC}}\\jarvis-ui\\agent\\games.py
Origen laptop: tools/games.py (misma logica).
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
from pathlib import Path

STEAM_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Steam"),
    Path(r"C:\Program Files\Steam"),
    Path(r"D:\Steam"),
    Path(r"E:\Steam"),
    Path(r"F:\Steam"),
]
EPIC_CANDIDATES = [
    Path(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"),
    Path(r"C:\ProgramData\Epic\UnrealEngineLauncher\Data\Manifests"),
]

# Alias -> nombre canonico instalado (o conocido)
ALIASES = {
    "cs2": "Counter-Strike 2",
    "csgo": "Counter-Strike 2",
    "cs": "Counter-Strike 2",
    "counter": "Counter-Strike 2",
    "counter-strike": "Counter-Strike 2",
    "dota": "Dota 2",
    "dota2": "Dota 2",
    "dota 2": "Dota 2",
    "r6": "Tom Clancy's Rainbow Six Siege",
    "siege": "Tom Clancy's Rainbow Six Siege",
    "rainbow": "Tom Clancy's Rainbow Six Siege",
    "rainbowsix": "Tom Clancy's Rainbow Six Siege",
    "tetris": "Tetris Effect: Connected",
    "wallpaper": "Wallpaper Engine",
    "fortnite": "Fortnite",
    "fn": "Fortnite",
    "fallguys": "Fall Guys",
    "fall guys": "Fall Guys",
    "rocket": "Rocket League",
    "rocketleague": "Rocket League",
    "rocket league": "Rocket League",
    "pubg": "PUBG: BATTLEGROUNDS",
}

# IDs Steam conocidos aunque no esten instalados -> permite lanzar via steam://
KNOWN_STEAM_IDS = {
    "counter-strike 2": "730",
    "dota 2": "570",
    "pubg: battlegrounds": "578080",
    "apex legends": "1172470",
    "team fortress 2": "440",
}

# Nombres bonitos para IDs conocidos
KNOWN_ID_NAMES = {v: k for k, v in KNOWN_STEAM_IDS.items()}
KNOWN_ID_NAMES.update({"730": "Counter-Strike 2", "570": "Dota 2"})


def _parse_acf(path: Path):
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        m_appid = re.search(r'"appid"\s+"(\d+)"', text)
        m_name = re.search(r'"name"\s+"([^"]+)"', text)
        if m_appid and m_name:
            return {"appid": m_appid.group(1), "name": m_name.group(1).strip()}
    except Exception:
        pass
    return None


def _scan_steam():
    games = []
    seen = set()
    roots = [p for p in STEAM_CANDIDATES if p.exists()]
    for root in list(roots):
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            try:
                txt = vdf.read_text(encoding="utf-8", errors="ignore")
                for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
                    p = Path(m.group(1).replace("\\\\", "\\"))
                    if p.exists() and p not in roots:
                        roots.append(p)
            except Exception:
                pass
    for root in roots:
        steamapps = root / "steamapps"
        if not steamapps.exists():
            continue
        for acf in steamapps.glob("*.acf"):
            info = _parse_acf(acf)
            if info and info["appid"] not in seen:
                # filtrar redistribuibles
                if info["appid"] == "228980":
                    continue
                games.append({
                    "id": info["appid"],
                    "name": info["name"],
                    "platform": "steam",
                    "launch_url": f"steam://rungameid/{info['appid']}",
                    "path": str(root),
                })
                seen.add(info["appid"])
    return games


def _scan_epic():
    games = []
    for base in EPIC_CANDIDATES:
        if not base.exists():
            continue
        for item in base.glob("*.item"):
            try:
                data = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
                display = data.get("DisplayName") or data.get("AppName") or item.stem
                ns = data.get("CatalogNamespace") or ""
                item_id = data.get("CatalogItemId") or ""
                app = data.get("AppName") or ""
                if ns and item_id and app:
                    url = f"com.epicgames.launcher://apps/{ns}%3A{item_id}%3A{app}?action=launch&silent=true"
                elif app:
                    url = f"com.epicgames.launcher://apps/{app}?action=launch"
                else:
                    url = f"com.epicgames.launcher://apps/{display}"
                games.append({"id": app or item_id or display, "name": display,
                              "platform": "epic", "launch_url": url, "path": str(item)})
            except Exception:
                continue
    return games


def list_games():
    """Devuelve lista de juegos reales instalados."""
    return _scan_steam() + _scan_epic()


def _fuzzy_match(query: str, games: list):
    if not query or not games:
        return None
    q = query.lower().strip()
    if q in ALIASES:
        target = ALIASES[q].lower()
        for g in games:
            if g["name"].lower() == target:
                return g
    for g in games:
        if str(g["id"]).lower() == q:
            return g
    for g in games:
        if q in g["name"].lower():
            return g
    if len(q) <= 4:
        def is_subseq(small, big):
            it = iter(big)
            return all(c in it for c in small)
        for g in games:
            if is_subseq(q, g["name"].lower().replace(" ", "").replace("-", "")):
                return g
    names = [g["name"] for g in games]
    lower_map = {n.lower(): n for n in names}
    matches = difflib.get_close_matches(q, [n.lower() for n in names], n=1, cutoff=0.5)
    if matches:
        t = lower_map[matches[0]]
        for g in games:
            if g["name"] == t:
                return g
    q_tokens = set(q.split())
    best, best_score = None, 0
    for g in games:
        score = len(q_tokens & set(g["name"].lower().split()))
        if score > best_score:
            best_score, best = score, g
    return best


def _launch_url(url: str) -> None:
    if os.name == "nt":
        try:
            os.startfile(url)  # type: ignore
        except Exception:
            subprocess.Popen(f'start "" "{url}"', shell=True)
    else:
        subprocess.Popen(["xdg-open", url])


def open_game(query: str) -> str:
    """Lanza un juego por nombre fuzzy. Devuelve string para bridge_executor."""
    game = (query or "").strip()
    if not game:
        return "ERROR: falta nombre del juego."
    games = list_games()
    match = _fuzzy_match(game, games)
    if match:
        url = match["launch_url"]
        try:
            _launch_url(url)
        except Exception as e:
            return f"ERROR al lanzar {match['name']}: {e} ({url})"
        return f"Lanzando {match['name']} ({match['platform']}:{match['id']}) via {url}"
    # Fallback: IDs Steam conocidos aunque no esten instalados
    q = game.lower().strip()
    canon = ALIASES.get(q, game)
    appid = KNOWN_STEAM_IDS.get(canon.lower(), KNOWN_STEAM_IDS.get(q))
    if appid:
        name = KNOWN_ID_NAMES.get(appid, canon)
        url = f"steam://rungameid/{appid}"
        try:
            _launch_url(url)
        except Exception as e:
            return f"ERROR al lanzar {name}: {e} ({url})"
        return f"Lanzando {name} (steam:{appid}) via {url}"
    avail = ", ".join([f"{g['name']} ({g['platform']}:{g['id']})" for g in games[:12]]) or "ninguno"
    return f"ERROR: juego '{game}' no encontrado. Disponibles: {avail}"


GAMES_TOOLS = ["list_games", "open_game"]
