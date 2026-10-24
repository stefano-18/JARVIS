#!/usr/bin/env python3
"""JARVIS: asistente de primera instalación. Pregunta los datos y las claves EN ESTE EQUIPO (las claves con entrada
oculta) y escribe ~/.config/jarvis/config.toml, ~/.config/jarvis/anthropic.key, ~/jarvis2/.env y ~/.hermes/.env con
permisos 600. Nunca manda nada a ningún sitio. Uso: python3 setup.py  (o  python3 setup.py --ayuda)"""
import getpass
import os
import secrets
import sys

H = os.path.expanduser("~")
CFG = os.path.join(H, ".config/jarvis")


def pregunta(texto, defecto=""):
    r = input(f"{texto}{f' [{defecto}]' if defecto else ''}: ").strip()
    return r or defecto


def secreto(texto):
    return getpass.getpass(f"{texto} (no se verá al escribir; Enter para saltar): ").strip()


def escribe(ruta, contenido, modo="w"):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    viejo = os.umask(0o077)
    try:
        with open(ruta, modo, encoding="utf-8") as f:
            f.write(contenido)
    finally:
        os.umask(viejo)
    os.chmod(ruta, 0o600)


def pon_env(ruta, valores):
    lineas = open(ruta, encoding="utf-8").read().splitlines() if os.path.exists(ruta) else []
    quedan = [l for l in lineas if l.split("=", 1)[0].strip() not in valores]
    escribe(ruta, "\n".join(quedan + [f"{k}={v}" for k, v in valores.items() if v]) + "\n")


def main():
    if "--ayuda" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return
    print("== JARVIS: primera instalación ==\nPulse Enter para dejar el valor entre corchetes.\n")
    c = {
        "nombre": pregunta("Su nombre (JARVIS le llamará así a veces)", "señor"),
        "pc_ip": pregunta("IP del PC con Windows", "192.168.1.60"),
        "portatil_ip": pregunta("IP de este portátil", "192.168.1.50"),
        "chat_telegram": pregunta("Su id de chat de Telegram (se lo dice @userinfobot)"),
        "win_usuario": pregunta("Su usuario de Windows en el PC", "usuario"),
        "cuenta_steam_1": pregunta("Cuenta principal de Steam (opcional)", "cuenta1"),
        "cuenta_steam_2": pregunta("Cuenta secundaria de Steam (opcional)", "cuenta2"),
        "zona": pregunta("Zona horaria", "Europe/Madrid"),
    }
    pc_si = pregunta("¿El PC con Windows se conectará a este equipo por la red? (s/n)", "s").lower().startswith("s")
    # sin PC: los servicios solo escuchan en este equipo. Con PC: en la red de casa (limítelo con el cortafuegos, ver docs/PENDIENTE.md)
    c["escucha_ip"] = "0.0.0.0" if pc_si else "127.0.0.1"
    toml = "# JARVIS: configuración de este equipo (sin claves). Generado por setup.py\n" + "".join(
        f'{k} = "{v}"\n' for k, v in c.items()) + "silencio_desde = 23\nsilencio_hasta = 8\ntope_global_usd = 0.50\naviso_gasto_usd = 0.30\nsolo_claude = true\n"
    escribe(os.path.join(CFG, "config.toml"), toml)
    print("\nAhora las claves. Se guardan solo en este equipo, con permisos 600.")
    anth = secreto("Clave de Anthropic (Claude)")
    tg = secreto("Token del bot de Telegram (de @BotFather)")
    groq = secreto("Clave de Groq (para oír la voz)")
    mac = pregunta("MAC del PC para encenderlo a distancia (opcional, p. ej. 00:11:22:33:44:55)")
    if anth:
        escribe(os.path.join(CFG, "anthropic.key"), anth + "\n")
    pon_env(os.path.join(H, "jarvis2/.env"), {"GROQ_API_KEY": groq, "TELEGRAM_BOT_TOKEN": tg, "TELEGRAM_ALLOWED_CHAT_IDS": c["chat_telegram"],
                                             "PC_IP": c["pc_ip"], "JARVIS_PC_MAC": mac, "PC_OLLAMA_URL": f"http://{c['pc_ip']}:11434",
                                             "JARVIS_REMOTE_SECRET": secrets.token_hex(24)})
    pon_env(os.path.join(H, ".hermes/.env"), {"ANTHROPIC_API_KEY": anth, "TELEGRAM_BOT_TOKEN": tg, "GROQ_API_KEY": groq,
                                             "TELEGRAM_ALLOWED_USERS": c["chat_telegram"], "TELEGRAM_HOME_CHANNEL": c["chat_telegram"]})
    if not os.path.exists(os.path.join(CFG, "firma.key")):
        escribe(os.path.join(CFG, "firma.key"), secrets.token_hex(32))
    print("\nListo. Siguiente paso: ./install.sh  (y después ponga su palabra clave con jarvis_gate.py).")


if __name__ == "__main__":
    main()
