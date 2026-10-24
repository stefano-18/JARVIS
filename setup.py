#!/usr/bin/env python3
"""JARVIS: asistente de primera instalación. Pregunta los datos y las claves EN ESTE EQUIPO (las claves con entrada
oculta) y escribe ~/.config/jarvis/config.toml, ~/.config/jarvis/anthropic.key, ~/jarvis2/.env y ~/.hermes/.env con
permisos 600. Nunca manda nada a ningún sitio. Uso: python3 setup.py  (o  python3 setup.py --ayuda)
Instalación completa en un PC con Linux (cerebro + agente + voz en el mismo equipo):  python3 setup.py --completa"""
import getpass
import hashlib
import json
import os
import secrets
import sys
import urllib.error
import urllib.request

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
    # un valor vacío (Enter para saltar) conserva el que ya hubiera
    quedan = [l for l in lineas if not valores.get(l.split("=", 1)[0].strip())]
    escribe(ruta, "\n".join(quedan + [f"{k}={v}" for k, v in valores.items() if v]) + "\n")


def _secreto_actual():
    """El secreto del hub ya creado (volver a ejecutar setup.py no debe desconectar el PC)."""
    try:
        for l in open(os.path.join(H, "jarvis2/.env"), encoding="utf-8"):
            if l.startswith("JARVIS_REMOTE_SECRET="):
                return l.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def guia(titulo, pasos):
    print(f"\n== {titulo} ==")
    for i, p in enumerate(pasos, 1):
        print(f"  {i}. {p}")


def _api(url, cabeceras=None):
    """(código HTTP, json) de una petición GET; (0, None) si no hay red."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=cabeceras or {}), timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:  # noqa: BLE001
        return 0, None


def clave_probada(texto, prueba, intentos=3):
    """Pide una clave y la prueba en su servicio. Devuelve la clave ("" si se salta)."""
    for _ in range(intentos):
        k = secreto(texto)
        if not k:
            return ""
        codigo, info = prueba(k)
        if codigo == 200:
            print(f"  Comprobada: funciona{info or ''}.")
            return k
        if codigo == 0:
            print("  No he podido comprobarla (sin internet). La guardo igualmente.")
            return k
        print("  Esa clave no funciona (el servicio la rechaza). Revísala y pégala otra vez.")
    print("  La guardo sin comprobar; puede cambiarla luego volviendo a ejecutar setup.py.")
    return k


def _prueba_telegram(t):
    c, j = _api(f"https://api.telegram.org/bot{t}/getMe")
    return c, (f" (su bot es @{j['result']['username']})" if c == 200 and j else None)


def _prueba_anthropic(k):
    return _api("https://api.anthropic.com/v1/models", {"x-api-key": k, "anthropic-version": "2023-06-01"})[0], None


def _prueba_groq(k):
    return _api("https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {k}"})[0], None


def chat_de_telegram(token):
    """El id de chat del dueño: se saca solo del primer mensaje que le mande a su bot."""
    if token:
        c, j = _api(f"https://api.telegram.org/bot{token}/getMe")
        bot = j["result"]["username"] if c == 200 and j else "su bot"
        input(f"\nAbra Telegram, busque @{bot} (o entre en https://t.me/{bot}), pulse «Iniciar» y mándele «hola».\n"
              "Cuando lo haya mandado, pulse Enter aquí... ")
        c, j = _api(f"https://api.telegram.org/bot{token}/getUpdates")
        for u in reversed((j or {}).get("result", [])):
            chat = (u.get("message") or {}).get("chat") or {}
            if chat.get("id"):
                print(f"  Encontrado: su chat es {chat['id']} ({chat.get('first_name', '')}). Solo usted podrá hablar con JARVIS.")
                return str(chat["id"])
        print("  No he visto su mensaje.")
    return pregunta("Su id de chat de Telegram (se lo dice el bot @userinfobot al escribirle)")


def palabra_clave():
    """Palabra clave para lo delicado (apagar, borrar, instalar). Solo se guarda su huella, nunca la palabra."""
    guia("Palabra clave", ["Es la palabra que le dirá a JARVIS para dejarle apagar, borrar o instalar.",
                           "Elija una que no use en conversaciones normales. JARVIS nunca la guarda tal cual."])
    for _ in range(3):
        a = getpass.getpass("Palabra clave (no se verá; Enter para ponerla más tarde): ").strip()
        if not a:
            return
        if a == getpass.getpass("Repítala: ").strip():
            sal = secrets.token_hex(16)
            h = hashlib.pbkdf2_hmac("sha256", a.encode(), sal.encode(), 200000).hex()
            escribe(os.path.join(H, "jarvis-control/clave.hash"), f"pbkdf2:{sal}:{h}\n")
            print("  Guardada.")
            return
        print("  No coinciden. Otra vez.")


def main():
    if "--ayuda" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return
    print("== JARVIS: primera instalación ==\nPulse Enter para dejar el valor entre corchetes.\n")
    uno = bool({"--completa", "--todo-en-uno"} & set(sys.argv))  # cerebro, agente y voz en este mismo PC: todo por 127.0.0.1, nada abierto a la red
    c = {"nombre": pregunta("Su nombre (JARVIS le llamará así a veces)", "señor")}
    if uno:
        c.update({"pc_ip": "127.0.0.1", "portatil_ip": "127.0.0.1"})
    else:
        c.update({"pc_ip": pregunta("IP del PC que va a controlar", "192.168.1.60"),
                  "portatil_ip": pregunta("IP de este portátil", "192.168.1.50")})
    if not uno:
        c["win_usuario"] = pregunta("Su usuario de Windows en el PC (si es Linux, Enter)", "usuario")
    c.update({"cuenta_steam_1": pregunta("Cuenta principal de Steam (opcional)", "cuenta1"),
              "cuenta_steam_2": pregunta("Cuenta secundaria de Steam (opcional)", "cuenta2"),
              "zona": pregunta("Zona horaria", "Europe/Madrid")})
    pc_si = not uno and pregunta("¿El PC se conectará a este equipo por la red? (s/n)", "s").lower().startswith("s")
    # sin PC o todo en uno: los servicios solo escuchan en este equipo. Con PC: en la red de casa (limítelo con el cortafuegos, ver docs/PENDIENTE.md)
    c["escucha_ip"] = "0.0.0.0" if pc_si else "127.0.0.1"
    toml = "# JARVIS: configuración de este equipo (sin claves). Generado por setup.py\n" + "".join(
        f'{k} = "{v}"\n' for k, v in c.items()) + "silencio_desde = 23\nsilencio_hasta = 8\ntope_global_usd = 0.50\naviso_gasto_usd = 0.30\nsolo_claude = true\n"
    escribe(os.path.join(CFG, "config.toml"), toml)
    print("\nAhora las claves. Le explico cómo sacar cada una; se guardan solo en este equipo, con permisos 600.")
    guia("1/3 Su bot de Telegram (gratis)", [
        "Abra Telegram y busque @BotFather (el de la marca azul de verificado).",
        "Mándele /newbot, dele un nombre (p. ej. «Mi JARVIS») y un usuario que acabe en «bot» (p. ej. mijarvis_bot).",
        "Le contestará con un token largo del estilo 123456789:AAH... Cópielo y péguelo aquí."])
    tg = clave_probada("Token del bot de Telegram", _prueba_telegram)
    c["chat_telegram"] = chat_de_telegram(tg)
    guia("2/3 Claude, el cerebro (de pago, céntimos al día; JARVIS tiene tope de gasto)", [
        "Entre en https://console.anthropic.com y cree una cuenta.",
        "En «Billing» añada un poco de saldo (con 5 $ hay para mucho).",
        "En «API Keys» pulse «Create Key», copie la clave (empieza por sk-ant-) y péguela aquí."])
    anth = clave_probada("Clave de Anthropic", _prueba_anthropic)
    guia("3/3 Groq, para que JARVIS le oiga (gratis)", [
        "Entre en https://console.groq.com y cree una cuenta (vale con Google).",
        "En «API Keys» pulse «Create API Key», copie la clave (empieza por gsk_) y péguela aquí."])
    groq = clave_probada("Clave de Groq", _prueba_groq)
    mac = "" if uno else pregunta("MAC del PC para encenderlo a distancia (opcional, p. ej. 00:11:22:33:44:55)")
    if anth:
        escribe(os.path.join(CFG, "anthropic.key"), anth + "\n")
    pon_env(os.path.join(H, "jarvis2/.env"), {"GROQ_API_KEY": groq, "TELEGRAM_BOT_TOKEN": tg, "TELEGRAM_ALLOWED_CHAT_IDS": c["chat_telegram"],
                                             "PC_IP": c["pc_ip"], "JARVIS_PC_MAC": mac, "PC_OLLAMA_URL": f"http://{c['pc_ip']}:11434",
                                             "JARVIS_REMOTE_SECRET": _secreto_actual() or secrets.token_hex(24)})
    pon_env(os.path.join(H, ".hermes/.env"), {"ANTHROPIC_API_KEY": anth, "TELEGRAM_BOT_TOKEN": tg, "GROQ_API_KEY": groq,
                                             "TELEGRAM_ALLOWED_USERS": c["chat_telegram"], "TELEGRAM_HOME_CHANNEL": c["chat_telegram"]})
    if tg:  # el candado de la palabra clave borra con él el mensaje donde se escribe
        escribe(os.path.join(H, ".openclaw/telegram-token"), tg + "\n")
    if not os.path.exists(os.path.join(CFG, "firma.key")):
        escribe(os.path.join(CFG, "firma.key"), secrets.token_hex(32))
    palabra_clave()
    guia("Opcional: Google (calendario y Gmail, solo lectura). Puede saltárselo y hacerlo cuando quiera", [
        "Entre en https://console.cloud.google.com y cree un proyecto (p. ej. «JARVIS»).",
        "En «APIs y servicios» > «Biblioteca», active «Gmail API» y «Google Calendar API».",
        "En «Pantalla de consentimiento de OAuth» elija «Externo» y añádase usted mismo como usuario de prueba.",
        "En «Credenciales» > «Crear credenciales» > «ID de cliente de OAuth», tipo «App de escritorio», y descargue el JSON.",
        "Guárdelo como ~/.config/jarvis/google-credentials.json",
        "Después de ./install.sh ejecute: ~/jarvis-control/gvenv/bin/python ~/jarvis2/scripts/google_jx.py auth (se abre el navegador para dar permiso)."])
    print("\nListo. Siguiente paso: ./install.sh")
    if uno:
        print("Y para el control del PC y la voz:  bash pc-windows/linux/instalar-pc-linux.sh 127.0.0.1")


if __name__ == "__main__":
    main()
