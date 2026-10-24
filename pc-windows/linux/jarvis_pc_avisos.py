#!/usr/bin/env python3
"""JARVIS en el PC (Linux): avisos por Telegram a través del portátil.

  descargas  -> (cada 2 min) avisa cuando Steam o Heroic terminan de descargar o actualizar un juego
  noche      -> (cada mañana) resumen de actualizaciones pendientes de Omarchy y de juegos
El Telegram lo manda el cerebro (jx.tg en el portátil por ssh): en el PC no hay claves.
"""
import getpass
import glob
import json
import os
import re
import subprocess
import sys

def _hub_host():
    """IP del portátil: la misma que usa el agente (HUB_HOST en ~/.config/jarvis-pc/agent.env)."""
    try:
        for l in open(os.path.expanduser("~/.config/jarvis-pc/agent.env"), encoding="utf-8"):
            if l.startswith("HUB_HOST="):
                return l.split("=", 1)[1].strip()
    except OSError:
        pass
    return "127.0.0.1"


HOME = os.path.expanduser("~")
ESTADO = os.path.join(HOME, ".local/state/jarvis/descargas.json")
PORTATIL = os.environ.get("JARVIS_PORTATIL") or f"{getpass.getuser()}@{_hub_host()}"
TG = ('~/jarvis2/.venv/bin/python -c "import os, sys; sys.path.insert(0, os.path.expanduser(\'~/jarvis2/scripts\')); '
      'import jx; jx.tg(sys.stdin.read())"')


def telegram(texto):
    import time
    for intento in range(6):          # al encender el PC la red tarda un poco: reintentar hasta ~1 min
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", PORTATIL, TG],
                           input=texto, text=True, timeout=60, check=False)
        if r.returncode == 0:
            return True
        time.sleep(10)
    return False


def steam():
    """appid -> (nombre, descargando)"""
    out = {}
    for acf in glob.glob(os.path.join(HOME, ".local/share/Steam/steamapps/appmanifest_*.acf")):
        try:
            t = open(acf, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        g = lambda k: (re.search(rf'"{k}"\s+"([^"]*)"', t) or [None, ""])[1]
        bajando = g("StateFlags") not in ("4", "") or (g("BytesToDownload") not in ("", "0") and g("BytesDownloaded") != g("BytesToDownload"))
        out["steam:" + g("appid")] = (g("name"), bajando)
    return out


def heroic():
    """Descargas de Heroic en marcha (legendary / gogdl / nile instalando o actualizando)."""
    out = {}
    r = subprocess.run(["pgrep", "-af", r"(legendary|gogdl|nile).*(install|update|download)"], capture_output=True, text=True)
    for ln in r.stdout.splitlines():
        m = re.search(r"(?:install|update|download)\s+(\S+)", ln)
        if m:
            out["heroic:" + m.group(1)] = (m.group(1), True)
    return out


def nombre_heroic(app):
    try:
        d = json.load(open(os.path.join(HOME, ".config/heroic/legendaryConfig/legendary/installed.json"), encoding="utf-8"))
        return d.get(app, {}).get("title") or app
    except (OSError, ValueError):
        return app


def descargas():
    try:
        antes = json.load(open(ESTADO, encoding="utf-8"))
    except (OSError, ValueError):
        antes = {}
    ahora = {**steam(), **heroic()}
    for k, (nombre, bajaba) in antes.items():
        if not bajaba:
            continue
        sigue = ahora.get(k)
        if k.startswith("steam:") and sigue and not sigue[1]:
            telegram(f"🎮 Señor, Steam ha terminado de descargar {nombre}. Ya puede jugar.")
        elif k.startswith("heroic:") and not sigue:
            telegram(f"🎮 Señor, Heroic ha terminado con {nombre_heroic(nombre)}.")
    os.makedirs(os.path.dirname(ESTADO), exist_ok=True)
    json.dump({k: list(v) for k, v in ahora.items()}, open(ESTADO, "w", encoding="utf-8"))


AVISOS = os.path.join(HOME, ".local/state/jarvis/avisos_salud.json")
LIMITES = {"gpu": 85, "cpu": 90, "disco": 90}       # °C, °C y % de disco: por encima, aviso (una vez cada 6 h)


def salud():
    """Aviso por Telegram si la gráfica o el procesador se calientan de más o el disco se llena."""
    import time
    medidas = {}
    r = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip().isdigit():
        medidas["gpu"] = int(r.stdout.strip())
    m = re.search(r"Tctl:\s*\+?([\d.]+)", subprocess.run(["sensors"], capture_output=True, text=True).stdout or "")
    if m:
        medidas["cpu"] = round(float(m.group(1)))
    st = os.statvfs(HOME)
    medidas["disco"] = round(100 - st.f_bavail / st.f_blocks * 100)
    try:
        ya = json.load(open(AVISOS, encoding="utf-8"))
    except (OSError, ValueError):
        ya = {}
    texto = {"gpu": "la gráfica está a {} °C", "cpu": "el procesador está a {} °C", "disco": "el disco está al {} %"}
    for k, v in medidas.items():
        if v >= LIMITES[k] and time.time() - ya.get(k, 0) > 6 * 3600:
            if telegram(f"🌡️ Señor, {texto[k].format(v)}. Le aviso por si quiere revisarlo."):
                ya[k] = time.time()
    os.makedirs(os.path.dirname(AVISOS), exist_ok=True)
    json.dump(ya, open(AVISOS, "w", encoding="utf-8"))


def noche():
    r = subprocess.run(["checkupdates"], capture_output=True, text=True, timeout=300)
    paquetes = [ln.split()[0] for ln in r.stdout.splitlines() if ln.strip()]
    pend_steam = [n for n, b in steam().values() if b]
    partes = []
    if paquetes:
        partes.append(f"Omarchy tiene {len(paquetes)} " + ("actualización pendiente" if len(paquetes) == 1 else "actualizaciones pendientes")
                      + (" (entre ellas el núcleo del sistema)" if any(p.startswith("linux") for p in paquetes) else "")
                      + ". Para instalarlas hace falta su contraseña: cuando quiera, «omarchy update».")
    if pend_steam:
        partes.append("Steam tiene pendiente: " + ", ".join(pend_steam[:6]) + ".")
    if partes:
        telegram("☀️ Buenos días, señor. Actualizaciones del PC:\n" + "\n".join(partes))


if __name__ == "__main__":
    if (sys.argv[1:] or ["descargas"])[0] == "descargas":
        salud()
    {"descargas": descargas, "noche": noche}[sys.argv[1] if len(sys.argv) > 1 else "descargas"]()
