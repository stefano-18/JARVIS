#!/usr/bin/env python3
"""Pone los datos de ESTE equipo (de ~/.config/jarvis/config.toml) en los marcadores {{...}} del repositorio.
Lo usa install.sh sobre una copia; el repositorio nunca se toca. Uso: rellenar.py <carpeta>"""
import os
import sys
import tomllib


def main(carpeta):
    with open(os.path.expanduser("~/.config/jarvis/config.toml"), "rb") as f:
        c = tomllib.load(f)
    home = os.path.expanduser("~")
    win = c.get("win_usuario", "usuario")
    c1 = c.get("cuenta_steam_1", "cuenta1")
    pc = c.get("pc_ip", "192.168.1.60")
    valores = {
        "{{HOME}}": home, "{{USUARIO}}": os.path.basename(home), "{{WIN_USUARIO}}": win,
        "{{WIN_HOME_ESC}}": f"C:\\\\Users\\\\{win}", "{{WIN_HOME}}": f"C:\\Users\\{win}",
        "{{WIN_HOME_MIN}}": f"c:\\users\\{win.lower()}", "{{WIN_HOME_BARRA}}": f"C:/Users/{win}",
        "{{PC_IP}}": pc, "{{PORTATIL_IP}}": c.get("portatil_ip", "192.168.1.50"), "{{RED}}": pc.rsplit(".", 1)[0],
        "{{CHAT_TELEGRAM}}": str(c.get("chat_telegram", "")),
        "{{CUENTA_STEAM_1}}": c1, "{{CUENTA_STEAM_1_MIN}}": c1.lower(), "{{CUENTA_STEAM_1_NOMBRE}}": c1.split("_")[0],
        "{{CUENTA_STEAM_2}}": c.get("cuenta_steam_2", "cuenta2"), "{{NOMBRE_PC}}": c.get("nombre_pc", "MI-PC"), "{{NOMBRE}}": c.get("nombre", "señor"),
        "{{CHAT_GRUPO_TELEGRAM}}": str(c.get("chat_grupo_telegram", c.get("chat_telegram", ""))),
    }
    n = 0
    for raiz, dirs, archivos in os.walk(carpeta):
        dirs[:] = [d for d in dirs if d != ".git"]
        for a in archivos:
            p = os.path.join(raiz, a)
            try:
                s = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            if "{{" not in s:
                continue
            t = s
            for k in sorted(valores, key=len, reverse=True):
                t = t.replace(k, valores[k])
            if t != s:
                open(p, "w", encoding="utf-8").write(t)
                n += 1
    print(f"rellenados {n} archivos con los datos de este equipo")


if __name__ == "__main__":
    main(sys.argv[1])
