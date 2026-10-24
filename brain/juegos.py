import sys
import os
#!/usr/bin/env python3
"""JARVIS (arreglo 31): juegos de Steam y Epic en el PC.

Uso: juegos.py steam|epic instalar|actualizar|abrir "<juego>" [--cuenta {{CUENTA_STEAM_1_MIN}}|{{CUENTA_STEAM_2}}]
     juegos.py buscar "<juego>"   (solo busca en Steam)
     juegos.py prueba             (abre las descargas de Steam en el PC)
"""
import re
import json, os, re, sys, unicodedata, urllib.parse, urllib.request

sys.path.insert(0, os.path.expanduser("~/jarvis2/scripts"))
import pc_do  # noqa: E402

# PC con Linux (Omarchy) primero; las rutas de Windows quedan por si vuelve Windows
DESTINOS = ["{{HOME}}/Documents/jarvis-juego.txt"] + ["{{WIN_HOME_ESC}}\\" + c + "jarvis-juego.txt" for c in ("Documents\\", "Downloads\\", "Desktop\\", "JARVIS-backups\\", "OneDrive\\Documents\\", "")]


def plano(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", "".join(c for c in t if unicodedata.category(c) != "Mn"))).strip()


def steam_buscar(q):
    url = "https://store.steampowered.com/api/storesearch/?" + urllib.parse.urlencode({"term": q, "l": "spanish", "cc": "ES"})
    items = json.load(urllib.request.urlopen(url, timeout=10)).get("items", [])
    pq = plano(q)
    for it in items:
        if plano(it.get("name")) == pq:
            return it
    for it in items:
        if pq and pq in plano(it.get("name")):
            return it
    return items[0] if items else None


def ok(r):
    return isinstance(r, dict) and r.get("status") == "ok"


def _vent_juego():
    try:
        n = open(os.path.expanduser("~/.config/jarvis/ultimo_juego.txt"), encoding="utf-8").read().strip()
    except OSError:
        return []
    return ["--ventana", re.escape(n), "--hasta", re.escape(n)] if n else []


def mandar(linea):
    for dest in DESTINOS:
        r = pc_do.run("files.write", {"path": dest, "content": linea}, timeout=20)
        if ok(r):
            break
    if not ok(r):
        return f"No he podido enviar la orden al PC ({str((r or {}).get('error', r))[:120]})."
    r = pc_do.run("apps.open", {"app": "jarvis-juego"}, timeout=20)
    if not ok(r):
        return f"No he podido lanzar la orden en el PC ({str((r or {}).get('error', r))[:120]})."
    if linea.startswith("steam://rungameid/"):
        import subprocess
        obj = ("Si aparece el cuadro de Steam 'Seleccionar opción de inicio', haz clic en la opción que dice solo 'Jugar a «nombre del juego»' "
               "(normalmente la SEGUNDA; NUNCA la que contiene VR o SteamVR) y después pulsa el botón azul Jugar. Si todavía no ves ese cuadro ni el juego, "
               "responde esperar; si lo que ves es la ventana '¿Quién va a jugar?' de Steam, responde esperar también. Haz las dos cosas juntas: clic en la opción normal y clic en el botón azul Jugar de abajo a la "
               "derecha. Mientras ese cuadro se vea, NO respondas hecho: pulsa Jugar. Responde hecho solo cuando el cuadro ya no "
               "se vea, o si el juego se abre sin que salga.")
        subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pantalla.py"), obj,
                          ] + _vent_juego() + ["--unico", "inicio", "--evitar", r"\bVR\b|SteamVR", "--espera", "1", "--pasos", "8"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    if re.match(r"steam://install/|epic:(instalar|actualizar):", linea):
        import subprocess
        if linea.startswith("steam://"):
            obj = ("Si se ve el cuadro de Steam para instalar un juego, pulsa el botón Instalar (o Siguiente / Aceptar si sale "
                   "un acuerdo de licencia). Responde hecho cuando el cuadro ya no se vea o haya empezado la descarga.")
            extra = ["--ventana", "steam", "--hasta", "Instalar|Install"]
        else:
            nom = linea.split(":", 2)[2]
            obj = ("En Epic Games Launcher, para el juego " + nom + ": si ves el botón Instalar o Actualizar, púlsalo, y en el "
                   "cuadro de instalación pulsa Instalar. Si solo ves Obtener o un precio, no pulses nada y responde imposible. "
                   "Responde hecho cuando empiece la descarga o la actualización.")
            extra = ["--ventana", "epic", "--hasta", "Epic Games"]
        subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pantalla.py"), obj] + extra +
                         ["--espera", "2", "--pasos", "6"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    if linea.startswith("steam://") and "|" in linea:
        import subprocess
        quien = {"{{CUENTA_STEAM_1_MIN}}": "{{CUENTA_STEAM_1}}", "{{CUENTA_STEAM_2}}": "{{CUENTA_STEAM_2}}"}.get(linea.split("|", 1)[1], linea.split("|", 1)[1])
        subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pantalla.py"),
                          "Si se ve la ventana de Steam \"¿Quién va a jugar?\" (cada cuenta es un cuadro con su nombre en grande debajo, por ejemplo {{CUENTA_STEAM_1}} o {{CUENTA_STEAM_2}}), haz clic en el cuadro de la cuenta " + quien + {"{{CUENTA_STEAM_1}}": " (foto de una estatua en blanco y negro, el cuadro de la izquierda; NO pulses {{CUENTA_STEAM_2}})", "{{CUENTA_STEAM_2}}": " (foto con un signo de interrogación, el cuadro a la derecha de {{CUENTA_STEAM_1}}; NO pulses {{CUENTA_STEAM_1}})"}.get(quien, "") +
                          ". Responde hecho solo cuando veas Steam abierto con la sesión iniciada (tienda o biblioteca); si no ves ninguna ventana de Steam, responde esperar.",
                          "--luego", (linea.split("|", 1)[0] if re.match(r"steam://(rungameid|install|validate)/", linea) else ""), "--unico", "cuenta", "--ventana", "steam", "--hasta", "Iniciar sesi|Sign in|Qui.n va a jugar", "--espera", "2", "--pasos", "10"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return None


def main(a):
    if a[:2] == ["steam", "cliente"]:
        c = re.sub(r"[^a-z0-9_]", "", (a[a.index("--cuenta") + 1] if "--cuenta" in a[:-1] else "").lower())[:32]
        e = mandar("steam://open/main" + (f"|{c}" if c else ""))
        print(e or "Abriendo Steam, señor.")
        return 1 if e else 0
    cuenta = None
    if "--cuenta" in a:
        i = a.index("--cuenta")
        cuenta = re.sub(r"[^a-z0-9_]", "", (a[i + 1] if i + 1 < len(a) else "").lower())[:32] or None
        a = a[:i] + a[i + 2:]
    if a[:1] == ["buscar"]:
        it = steam_buscar(" ".join(a[1:]))
        print(f"Steam: {it['name']} (id {it['id']})" if it else "No lo encuentro en Steam.")
        return 0
    if a[:1] == ["prueba"]:
        e = mandar("steam://open/downloads")
        print(e or "OK: descargas de Steam abiertas en el PC.")
        return 1 if e else 0
    if len(a) < 3 or a[0] not in ("steam", "epic") or a[1] not in ("instalar", "actualizar", "abrir"):
        print(__doc__)
        return 2
    tienda, acc, juego = a[0], a[1], " ".join(a[2:]).strip()
    if tienda == "steam":
        it = steam_buscar(juego)
        if not it:
            print(f"No encuentro «{juego}» en Steam, señor.")
            return 1
        uri = {"instalar": "steam://install/", "actualizar": "steam://validate/", "abrir": "steam://rungameid/"}[acc] + str(int(it["id"]))
        try:
            open(os.path.expanduser("~/.config/jarvis/ultimo_juego.txt"), "w", encoding="utf-8").write(it["name"])
        except OSError:
            pass
        e = mandar(uri + (f"|{cuenta}" if cuenta else ""))
        nombre = it["name"]
        hecho = {"instalar": f"He empezado la instalación de {nombre} en Steam, señor.",
                 "actualizar": f"Steam está comprobando y actualizando {nombre}, señor.",
                 "abrir": f"Abriendo {nombre}, señor."}[acc]
    else:
        nombre = plano(juego)[:60]
        if not nombre:
            print("Dígame el nombre del juego, señor.")
            return 1
        e = mandar(f"epic:{acc}:{nombre}")
        hecho = {"instalar": f"Le he abierto {juego} en Epic Games, señor: si ya lo tiene instalado se abre, si no, verá su página para instalarlo.",
                 "actualizar": "He abierto la biblioteca de Epic Games, señor; ahí se actualizan sus juegos.",
                 "abrir": f"Abriendo {juego} en Epic Games, señor."}[acc]
    print(e or hecho)
    return 1 if e else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
