#!/usr/bin/env python3
"""Cambia los datos personales por marcadores {{...}} en una carpeta (para el repositorio).
Los valores reales se leen de ~/.config/jarvis/config.toml (nunca se guardan en el repo).
Uso: anonimizar.py <carpeta>"""
import os
import sys

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None


def mapa():
    c = {}
    if tomllib:
        with open(os.path.expanduser("~/.config/jarvis/config.toml"), "rb") as f:
            c = tomllib.load(f)
    home = os.path.expanduser("~")
    usuario = os.path.basename(home)
    win = c.get("win_usuario", "")
    pc, port = c.get("pc_ip", ""), c.get("portatil_ip", "")
    red = pc.rsplit(".", 1)[0] if pc else ""
    c1, c2 = c.get("cuenta_steam_1", ""), c.get("cuenta_steam_2", "")
    pares = [
        (home, "{{HOME}}"),
        (f"C:\\\\Users\\\\{win}", "{{WIN_HOME_ESC}}"), (f"C:\\Users\\{win}", "{{WIN_HOME}}"),
        (f"c:\\users\\{win.lower()}", "{{WIN_HOME_MIN}}"), (f"C:/Users/{win}", "{{WIN_HOME_BARRA}}"),
        (pc, "{{PC_IP}}"), (port, "{{PORTATIL_IP}}"), (red + ".", "{{RED}}."),
        (str(c.get("chat_telegram", "")), "{{CHAT_TELEGRAM}}"),
        (c1, "{{CUENTA_STEAM_1}}"), (c1.lower(), "{{CUENTA_STEAM_1_MIN}}"),
        (c1.split("_")[0], "{{CUENTA_STEAM_1_NOMBRE}}"), (c2, "{{CUENTA_STEAM_2}}"),
        (c.get("nombre_pc", ""), "{{NOMBRE_PC}}"),
        (str(c.get("chat_grupo_telegram", "")), "{{CHAT_GRUPO_TELEGRAM}}"),
    ]
    for u in c.get("otros_usuarios_win", []):  # usuarios de Windows antiguos que salen en scripts viejos
        pares += [(f"C:\\\\Users\\\\{u}", "{{WIN_HOME_ESC}}"), (f"C:\\Users\\{u}", "{{WIN_HOME}}"), (f"C:/Users/{u}", "{{WIN_HOME_BARRA}}")]
    pares += [(f"{usuario}@", "{{USUARIO}}@"), (usuario, "{{USUARIO}}"), (win, "{{WIN_USUARIO}}"),
              ("Homo" + "fobia", "Farmofobia"), ("homo" + "fobia", "farmofobia")]  # ejemplos de voz mal oída, en tono neutro
    pares += [(u, "{{WIN_USUARIO}}") for u in c.get("otros_usuarios_win", [])]  # restos sueltos, al final
    pares += [(x.upper(), "{{WIN_USUARIO}}") for x in [win] + c.get("otros_usuarios_win", []) if x]  # también en MAYÚSCULAS
    pares += [(usuario.upper(), "{{USUARIO}}")]
    if c.get("nombre"):  # el nombre del dueño (JARVIS le llama por su nombre)
        pares += [(c["nombre"], "{{NOMBRE}}")]
    return [(a, b) for a, b in pares if a and len(a) >= 3]


def main(carpeta):
    pares = mapa()
    n = 0
    for raiz, dirs, archivos in os.walk(carpeta):
        dirs[:] = [d for d in dirs if d not in (".git", "tools")]  # tools/ no se toca a sí mismo
        for a in archivos:
            p = os.path.join(raiz, a)
            try:
                s = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            t = s
            for real, marca in pares:
                t = t.replace(real, marca)
            if t != s:
                open(p, "w", encoding="utf-8").write(t)
                n += 1
    print(f"anonimizados {n} archivos")
    # tools/ no se reescribe, pero tampoco puede llevar datos reales: si los lleva, se para
    reales = [r for r, m in pares if not m.startswith("Farmo") and not m.startswith("farmo")]
    for raiz, dirs, archivos in os.walk(os.path.join(carpeta, "tools")):
        for a in archivos:
            p = os.path.join(raiz, a)
            try:
                s = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            if any(r in s for r in reales):
                print(f"{p} [dato personal dentro de tools/]")
                return 1
    return revisar([os.path.join(r, a) for r, ds, fs in os.walk(carpeta)
                    if ".git" not in r.split(os.sep) and f"{os.sep}tools" not in r for a in fs])


# --- comprobación "a prueba de fallos": datos personales que NO están en config.toml también paran la subida ---
import re  # noqa: E402

CORREO = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z.]{2,}")
CORREO_OK = re.compile(r"@(ejemplo|example)\.|@localhost|noreply|@github\.com|@users\.noreply|@anthropic\.com|@python\.org|^git@|@[0-9.]+$", re.I)
IP_PRIVADA = re.compile(r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b")
IP_OK = re.compile(r"^192\.168\.1\.(\d{1,3})$|^10\.0\.0\.\d+$|^192\.168\.0\.\d+$")
RUTA_WIN = re.compile(r"[Cc]:[\\/]+[Uu]sers[\\/]+([A-Za-z0-9._-]+)")
RUTA_OK = {"public", "default", "usuario", "user", "<usuario>", "nombre", "tu_usuario", "all users"}


def revisar(archivos):
    malos = 0
    for p in archivos:
        try:
            lineas = open(p, encoding="utf-8").read().splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, l in enumerate(lineas, 1):
            tipo = None
            for m in CORREO.finditer(l):
                if not CORREO_OK.search(m.group(0)) and not re.search(r"\.(png|jpg|svg|js|py|md)$", m.group(0)):
                    tipo = "correo"
            for m in IP_PRIVADA.finditer(l):
                if not IP_OK.match(m.group(0)):
                    tipo = "IP privada"
            for m in RUTA_WIN.finditer(l):
                if m.group(1).lower() not in RUTA_OK and "{{" not in l[m.start():m.end() + 2]:
                    tipo = "ruta de usuario de Windows"
            if tipo:
                print(f"{p}:{i} [{tipo}]")
                malos += 1
    if malos:
        print(f"PARO: {malos} dato(s) personal(es) sin anonimizar. Añádalos a config.toml o cámbielos por un ejemplo.")
    return 1 if malos else 0


if __name__ == "__main__":
    if sys.argv[1] == "--solo-comprobar":
        sys.exit(revisar(sys.argv[2:]))
    sys.exit(main(sys.argv[1]))
