"""JARVIS (arreglo 27): filtro de seguridad dentro de Hermes. Nunca registra el texto de los mensajes."""
import json, logging, os, re, subprocess, time, unicodedata, urllib.parse, urllib.request

log = logging.getLogger("jarvis-filtro")
HOME = os.path.expanduser("~")
NODE = "/usr/bin/node"
PLUGIN = "{{HOME}}/jarvis-control/plugin-silencio/index.js"
PUENTE = os.path.join(HOME, "jarvis2/scripts/filtro_puente.mjs")
CTRL = os.path.join(HOME, "jarvis-control")
GATE = next((p for p in (os.path.join(CTRL, "jarvis_gate.py"), os.path.join(HOME, "jarvis2/scripts/jarvis_gate.py")) if os.path.exists(p)), None)
ENV = dict(os.environ, PATH=os.pathsep.join([os.path.dirname(NODE), os.environ.get("PATH", "/usr/bin:/bin")]))
SI = re.compile(r"^(si|vale|ok|okay|dale|adelante|de acuerdo|confirmo|confirmado|envialo|mandalo|hazlo|publicalo)\b")
PROHIBIDO = re.compile(r"clave\.hash|poner-clave|jarvis_gate(?!\.py\s+check-(?:high|low)\b)|jarvis-control/(?:LOCK|UNLOCKED|fail_count|clave)|\.visto-bueno"
                       r"|jarvis-filtro|plugin-silencio|filtro_puente|plugins\s+(?:disable|remove|uninstall)", re.I)
ALTO = re.compile(r"pc_do.*\b(shutdown|restart|suspend|reboot|poweroff|power|yes|powershell|shell|exec|cmd|winget|uninstall|desinstal\w*"
                  r"|delete|remove|borrar|kill|registry|regedit|format)\b", re.I | re.S)


CAPTURA = re.compile(r"\b(captura|capturas|pantallazo|screenshot|(mandame|ensename|pasame|muestrame|quiero ver|ver) (la|las|tus|sus)? ?pantallas?|como va el pc|como esta el pc)\b")
VENV_PY = os.path.join(HOME, "jarvis2/.venv/bin/python")
CAPTURA_PY = os.path.join(HOME, "jarvis2/scripts/captura_tg.py")


def _captura():
    try:
        r = subprocess.run([VENV_PY, CAPTURA_PY, "Así están sus pantallas, señor."], capture_output=True, text=True, timeout=90)
        out = ((r.stdout or "").strip().splitlines() or [""])[-1]
    except Exception as e:  # noqa: BLE001
        out = f"No he podido sacar la captura ({str(e)[:80]})."
    if out.startswith("Captura enviada"):
        return {"action": "handled"}  # la foto ya lleva su frase
    return {"action": "handled", "reply": out or "No he podido sacar la captura, señor."}


def _jx_local(text):
    # arreglo 75: respuestas sin IA (hora, cuentas, recordatorios, gasto, ayuda, equipo, tareas, webs...)
    try:
        import sys as _s
        d = os.path.join(HOME, "jarvis2/scripts")
        if d not in _s.path:
            _s.path.insert(0, d)
        import jx
        return jx.responde(text, "telegram")
    except Exception as e:  # noqa: BLE001
        log.warning("jarvis-filtro: jx fallo (%s)", str(e)[:80])
        return None


def _plano(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").strip()


def _firma_vb(ms):
    # arreglo 86: la señal de visto bueno va firmada; sin la firma, google_jx no la acepta
    import hashlib, hmac
    k = open(os.path.join(HOME, ".config/jarvis/firma.key"), encoding="utf-8").read().strip().encode()
    return hmac.new(k, ms.encode(), hashlib.sha256).hexdigest()


def _visto_bueno(t):
    p = _plano(t)
    if SI.match(p) and len(p) < 60:
        try:
            ms = str(int(time.time() * 1000))
            with open(os.path.join(CTRL, ".visto-bueno"), "w") as f:
                f.write(ms + ":" + _firma_vb(ms))
        except OSError:
            pass


def _gate(*args):
    if not GATE:
        return False
    try:
        r = subprocess.run(["python3", GATE, *args], capture_output=True, text=True, timeout=15)
        return bool(re.search(r"^\s*OK\b", (r.stdout or "") + (r.stderr or ""), re.M))
    except Exception:  # noqa: BLE001
        return False


def _candidato(t):
    t = t.strip()
    if re.fullmatch(r"\S{4,64}", t) and not t.startswith("/"):
        return t
    m = re.match(r"^jarvis[\s,:]+(.+)$", t, re.I | re.S)
    if m:
        return m.group(1).split()[-1].strip("()\"'«»“”.,;:!?") or None
    return None


def _token():
    tk = os.environ.get("TELEGRAM_BOT_TOKEN")
    if tk:
        return tk
    try:
        for line in open(os.path.join(HOME, ".hermes/.env"), encoding="utf-8"):
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return None


def _borrar(chat, msg):
    tk = _token()
    if not (tk and chat and msg):
        return
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "message_id": msg}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{tk}/deleteMessage", data=data, timeout=8).read()
    except Exception:  # noqa: BLE001
        log.warning("jarvis-filtro: no pude borrar el mensaje de la palabra clave")


def _puente(text, chat, msg):
    r = subprocess.run([NODE, PUENTE, PLUGIN], input=json.dumps({"text": text, "chatId": str(chat or ""), "messageId": str(msg or "")}),
                       capture_output=True, text=True, timeout=25, env=ENV)
    for line in reversed((r.stdout or "").splitlines()):
        if line.startswith("JXR "):
            res = json.loads(line[4:])
            if res.get("kind") == "error":
                raise RuntimeError(str(res.get("v"))[:120])
            return res
    raise RuntimeError("el puente no contesto")


def consume(session_key=None, platform=None, source=None, message_id=None, text=None, **kw):
    if platform != "telegram" or not text:
        return None
    chat = (source or {}).get("chat_id")
    _visto_bueno(text)
    cand = _candidato(text)
    clave = _gate("verify", cand) if cand else False
    if not clave and len(text) < 90 and CAPTURA.search(_plano(text)):
        return _captura()
    if not clave:
        r = _jx_local(text)
        if r:
            return {"action": "handled", "reply": r}
    try:
        res = _puente(text, chat, message_id)
    except Exception as e:  # noqa: BLE001
        log.warning("jarvis-filtro: puente fallo (%s)", e)
        if clave:  # la palabra clave nunca llega a la IA
            _borrar(chat, message_id)
            return {"action": "handled", "reply": "No he podido activar el modo seguro ahora mismo, señor. Inténtelo de nuevo en un momento."}
        return None
    if clave:
        _borrar(chat, message_id)
    v = res.get("v")
    if res.get("kind") == "string" and v.strip():
        if v.strip() == "Modo seguro desactivado, señor.":  # el candado ya lo manda por Telegram
            return {"action": "handled"}
        return {"action": "handled", "reply": v}
    if isinstance(v, dict) and isinstance(v.get("reply") or v.get("text"), str):
        return {"action": "handled", "reply": v.get("reply") or v.get("text")}
    if clave:
        return {"action": "handled"}
    return None


def guardia(tool_name=None, args=None, **kw):
    if tool_name == "computer_use":
        return {"action": "block", "message": "El portátil no tiene pantalla. Para capturas usa: python3 ~/jarvis2/scripts/captura_tg.py \"<frase corta>\". Para ratón y teclado del PC usa: ~/jarvis2/scripts/pantalla.py \"<objetivo>\"."}
    try:
        s = json.dumps(args, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        s = str(args)
    if PROHIBIDO.search(s):
        return {"action": "block", "message": "Bloqueado por seguridad de JARVIS: la palabra clave, los candados, el visto bueno y el propio filtro no se tocan."}
    if ALTO.search(s) and not _gate("check-high"):
        return {"action": "block", "message": "Acción protegida: el señor tiene que activar antes el modo seguro con su palabra clave. Díselo, pero nunca le pidas la palabra."}
    return None


def register(ctx):
    ctx.register_hook("post_gateway_admission", consume)
    ctx.register_hook("pre_tool_call", guardia)
