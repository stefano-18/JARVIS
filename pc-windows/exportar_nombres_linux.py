#!/usr/bin/env python3
"""JARVIS (Linux/Omarchy): versión de exportar_nombres.ps1.

Junta los juegos instalados (Steam y Heroic: Epic, GOG y Amazon) y los nombres de
las apps del PC para que el cerebro los reconozca por voz y aprenda a pronunciarlos.
Escribe juegos_pc.txt y nombres_pc.txt (mismo formato que en Windows: un nombre por
línea, UTF-8) en --salida. Con --enviar los copia además al portátil por scp.
Solo lee nombres; no toca nada del PC.
"""
import argparse
import glob
import json
import getpass
import os
import re
import subprocess

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
STEAM = [os.path.join(HOME, ".local/share/Steam"), os.path.join(HOME, ".steam/steam"),
         os.path.join(HOME, ".var/app/com.valvesoftware.Steam/.local/share/Steam")]
HEROIC = [os.path.join(HOME, ".config/heroic"), os.path.join(HOME, ".var/app/com.heroicgameslauncher.hgl/config/heroic")]
APPS = [os.path.join(HOME, ".local/share/applications"), "/usr/share/applications",
        "/var/lib/flatpak/exports/share/applications", os.path.join(HOME, ".local/share/flatpak/exports/share/applications")]
NO_JUEGO = re.compile(r"^appid_|Redistributable|Steamworks|Proton|Steam Linux Runtime|SteamVR", re.I)
DESTINO = f"{getpass.getuser()}@{_hub_host()}:.config/jarvis/"


def limpia(n):
    return re.sub(r"\s*\((x64|x86|wow)\)", "", re.sub(r"[®™©]", "", n or "")).strip()


def _leer_json(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def juegos_steam():
    out = []
    for raiz in STEAM:
        vdf = os.path.join(raiz, "steamapps", "libraryfolders.vdf")
        libs = {os.path.join(raiz, "steamapps")}
        try:
            libs |= {os.path.join(p, "steamapps") for p in re.findall(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf-8").read())}
        except OSError:
            pass
        for lib in libs:
            for acf in glob.glob(os.path.join(lib, "appmanifest_*.acf")):
                try:
                    m = re.search(r'"name"\s+"([^"]+)"', open(acf, encoding="utf-8", errors="replace").read())
                except OSError:
                    continue
                if m:
                    out.append(m.group(1))
        if out:
            break
    return out


def juegos_heroic():
    out = []
    for raiz in HEROIC:
        epic = _leer_json(os.path.join(raiz, "legendaryConfig/legendary/installed.json")) or {}
        out += [v.get("title", "") for v in epic.values() if isinstance(v, dict) and not v.get("is_dlc")]
        gog = _leer_json(os.path.join(raiz, "gog_store/installed.json")) or {}
        ids = {g.get("appName") for g in gog.get("installed", []) if isinstance(g, dict)}
        lib = _leer_json(os.path.join(raiz, "store_cache/gog_library.json")) or {}
        out += [g.get("title", "") for g in (lib.get("games") or []) if isinstance(g, dict) and g.get("app_name") in ids]
        nile = _leer_json(os.path.join(raiz, "nile_config/nile/installed.json")) or []
        lib = _leer_json(os.path.join(raiz, "store_cache/nile_library.json")) or {}
        ids = {g.get("id") for g in nile if isinstance(g, dict)}
        out += [g.get("title", "") for g in (lib.get("library") or []) if isinstance(g, dict) and g.get("app_name") in ids]
    return out


def apps():
    out = []
    for d in APPS:
        for f in glob.glob(os.path.join(d, "*.desktop")):
            nombre, oculto = "", False
            try:
                for ln in open(f, encoding="utf-8", errors="replace"):
                    if ln.startswith("[") and ln.strip() != "[Desktop Entry]":
                        break
                    if ln.startswith("Name=") and not nombre:
                        nombre = ln[5:].strip()
                    elif ln.strip() in ("NoDisplay=true", "Hidden=true"):
                        oculto = True
            except OSError:
                continue
            if nombre and not oculto:
                out.append(nombre)
    return out


def unicos(nombres, minimo=1, maximo=200):
    vistos, out = set(), []
    for n in nombres:
        n = limpia(n)
        if minimo <= len(n) <= maximo and not NO_JUEGO.search(n) and n.lower() not in vistos:
            vistos.add(n.lower())
            out.append(n)
    return sorted(out, key=str.lower)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--salida", default=os.path.join(HOME, ".local/share/jarvis/nombres"))
    ap.add_argument("--enviar", action="store_true", help="copiar al portátil (sobrescribe sus listas)")
    a = ap.parse_args()
    juegos = unicos(juegos_steam() + juegos_heroic())
    nombres = unicos(apps() + juegos, 2, 40)
    os.makedirs(a.salida, exist_ok=True)
    rutas = []
    for fich, lista in (("juegos_pc.txt", juegos), ("nombres_pc.txt", nombres)):
        r = os.path.join(a.salida, fich)
        with open(r, "w", encoding="utf-8") as f:
            f.write("\n".join(lista) + ("\n" if lista else ""))
        rutas.append(r)
    print(f"juegos={len(juegos)} nombres={len(nombres)} en {a.salida}")
    if a.enviar:
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"] + rutas + [DESTINO], check=True)
        print("enviado al portátil")


if __name__ == "__main__":
    main()
