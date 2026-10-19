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
              ("Farmofobia", "Farmofobia"), ("farmofobia", "farmofobia")]  # ejemplos de voz mal oída, en tono neutro
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
        dirs[:] = [d for d in dirs if d != ".git"]
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


if __name__ == "__main__":
    main(sys.argv[1])
