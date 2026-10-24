#!/usr/bin/env python3
"""Cerebro de voz (arreglo 16): audio del PC -> texto -> JARVIS -> {"type":"reply","text":...}."""
import asyncio, base64, datetime, io, json, logging, os, re, subprocess, sys, time, urllib.request, wave

log = logging.getLogger("voz")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jx  # noqa: E402  arreglo 75
import random  # arreglo 80
HOME = os.path.expanduser("~")
OPENCLAW = "/usr/bin/openclaw"
NODE = "/usr/bin/node"
PLUGIN = "{{HOME}}/jarvis-control/plugin-silencio/index.js"
RAPIDO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voz_rapido.mjs")
MODELO = os.environ.get("VOZ_WHISPER", "base")
ENV = dict(os.environ, PATH=os.pathsep.join([os.path.dirname(NODE), os.path.dirname(OPENCLAW), os.environ.get("PATH", "/usr/bin:/bin")]))
_wh = None
ADIOS = re.compile(r"^\W*(?:muchas\s+)?(?:gracias|adi[oó]s|chao|hasta luego|est[aá] bien as[ií]|eso es todo|nada m[aá]s|vale gracias)\W*$", re.I)
_lock = None


def _whisper():
    global _wh
    if _wh is None:
        from faster_whisper import WhisperModel
        _wh = WhisperModel(MODELO, device="cpu", compute_type="int8", cpu_threads=4)
    return _wh


GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_ALUC = re.compile(r"amara\.org|^\W*(?:aplausos|risas|m[uú]sica)\W*$|subt[ií]tulos|gracias por ver|suscr[ií]bete|www\.", re.I)


def _groq_key():
    for f in (os.path.join(HOME, ".config/jarvis/groq.key"), os.path.join(HOME, ".hermes/.env")):
        try:
            for line in open(f, encoding="utf-8"):
                line = line.strip()
                if line.startswith("GROQ_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")
                if f.endswith(".key") and line:
                    return line
        except OSError:
            pass
    return None


def _wav(data):
    if isinstance(data, str) and data.startswith("data:"):
        data = data.split(",", 1)[1]
    raw = base64.b64decode(data or "")
    if raw[:4] == b"RIFF":
        return raw
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(raw)
    return b.getvalue()


def _nivel(wav):
    import numpy as np
    with wave.open(io.BytesIO(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(x * x))) if x.size else 0.0


def _groq(data):
    k = _groq_key()
    if not k:
        return None
    wav = _wav(data)
    nv = _nivel(wav)
    if nv < 250:
        return ""
    bnd = "jx" + str(int(time.time() * 1000))
    parts = [f'--{bnd}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'.encode()
             for n, v in (("model", "whisper-large-v3-turbo"), ("language", "es"), ("temperature", "0"), ("response_format", "json")) + ((("prompt", "{{CUENTA_STEAM_1_NOMBRE}}, {{CUENTA_STEAM_2}}, la primera, la segunda."),) if _esperando_cuenta() else ())]
    parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + wav + b"\r\n")
    parts.append(f"--{bnd}--\r\n".encode())
    req = urllib.request.Request(GROQ_URL, b"".join(parts), {"Authorization": "Bearer " + k, "User-Agent": "jarvis/1.0",
                                                             "Content-Type": "multipart/form-data; boundary=" + bnd})
    with urllib.request.urlopen(req, timeout=8) as r:
        t = (json.load(r).get("text") or "").strip()
    if _ALUC.search(t) or (nv < 900 and re.fullmatch(r"\W*(gracias|muchas gracias|adi[oó]s|chao)\W*", t, re.I)):
        return ""
    return t


def _reserva_caida(n):
    # arreglo 76: la prueba diaria marca los proveedores caidos y aqui se saltan hasta que vuelvan
    return jx.leer_json("proveedores.json", {}).get(n, {}).get("ok") is False


def transcribir(data):
    try:
        t = None if _reserva_caida("groq") else _groq(data)
        if t is not None:
            return t
    except Exception as e:
        log.warning("voz groq: %s", str(e)[:150])
    return _transcribir_local(data)


def _transcribir_local(data):
    import numpy as np
    if isinstance(data, str) and data.startswith("data:"):
        data = data.split(",", 1)[1]
    raw = base64.b64decode(data or "")
    if raw[:4] == b"RIFF":
        with wave.open(io.BytesIO(raw)) as w:
            sr, ch = w.getframerate(), w.getnchannels()
            pcm = w.readframes(w.getnframes())
    else:
        sr, ch, pcm = 16000, 1, raw
    a = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a[: len(a) // ch * ch].reshape(-1, ch).mean(axis=1)
    if sr != 16000 and len(a):
        a = np.interp(np.linspace(0, len(a) - 1, int(len(a) * 16000 / sr)), np.arange(len(a)), a).astype(np.float32)
    if len(a) < 1600:
        return ""
    segs, _ = _whisper().transcribe(a, language="es", beam_size=1, vad_filter=True, hotwords="JARVIS Steam Epic Games Dota Counter-Strike Fortnite {{CUENTA_STEAM_1_NOMBRE}} {{CUENTA_STEAM_2}} Spotify Discord Chrome Visual Studio Code", condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segs).strip()


def limpia_entrada(t):
    t = (t or "").strip()
    t = re.sub(r"^\W*(?:\w+\W+){0,2}?\w*[jhy][aáeé]?rv[ií]s\b\W*", "", t, flags=re.I)
    return t.strip().rstrip(".!?¡¿ ").strip()


def orden(t):
    m = re.search(r"\b(?:ábreme|abreme|ábrelo|abre|abras|abrir|abrirme|abro|abra|abri|abrí|avre|avro|avra|habre|habré|abré)\b\s*(.*)", t, re.I)
    if m:
        return "abre " + m.group(1)
    m = re.search(r"\b(?:ciérrame|cierrame|cierra|cierres|cerrar|cierro|cierre|sierra|siérrame)\b\s*(.*)", t, re.I)
    if m:
        return "cierra " + m.group(1)
    m = re.search(r"\b(?:pon|sube|baja|silencia|apaga|reinicia|suspende|enciende)\b.*", t, re.I)
    return m.group(0) if m else t


def limpia_salida(t):
    t = re.sub(r"<think>.*?</think>", "", t or "", flags=re.S)
    t = re.sub(r"[*_`#>|]+", "", t)
    return re.sub(r"\s+", " ", t).strip()


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def local(t):
    r = jx.responde(t, "voz")  # arreglo 75: hora, fecha, cuentas, temporizadores, recordatorios, gasto, rutinas, equipo...
    if r:
        return r
    l = t.lower()
    n = datetime.datetime.now()
    if re.search(r"\b(cambia(r)? (de |la )?voz|otra voz|prueba otra voz|pon otra voz)\b", l):
        return "Como desee, señor. ¿Qué tal esta voz?"
    if re.search(r"\b(cambia(r)? (de |la )?voz|otra voz|prueba otra voz|pon otra voz)\b", l):
        return "Como desee, señor. ¿Qué tal esta voz?"
    if re.search(r"\bqu[eé] hora\b", l):
        return f"Son las {n.hour}:{n.minute:02d}, señor."
    if re.search(r"\bqu[eé] d[ií]a\b|\bqu[eé] fecha\b", l):
        return f"Hoy es {DIAS[n.weekday()]} {n.day} de {MESES[n.month - 1]}, señor."
    return None


def rapido(t):
    try:
        p = subprocess.run([NODE, RAPIDO, PLUGIN, t], capture_output=True, text=True, timeout=90,
                           cwd=os.path.dirname(PLUGIN), env=ENV)
        for line in reversed(p.stdout.splitlines()):
            if line.startswith("JXR "):
                r = json.loads(line[4:])
                return r.strip() if isinstance(r, str) and r.strip() else None
    except Exception as e:
        log.warning("voz rapido: %s", e)
    return None


def _extrae(out):
    out = (out or "").strip()
    d = None
    try:
        d = json.loads(out)
    except Exception:
        i = out.find("{")
        if i >= 0:
            try:
                d = json.loads(out[i:])
            except Exception:
                d = None
    if d is None:
        return out or None
    hall = []

    def walk(x, k=None):
        if isinstance(x, dict):
            for kk, v in x.items():
                walk(v, kk)
        elif isinstance(x, list):
            for v in x:
                walk(v, k)
        elif isinstance(x, str) and k in ("final", "reply", "text", "content") and x.strip():
            hall.append((k, x.strip()))
    walk(d)
    for pref in ("final", "reply", "text", "content"):
        for k, v in hall:
            if k == pref:
                return v
    return None


def _contexto():
    if not _hist:
        return ""
    ult = _hist[-4:]
    return "[Conversación reciente: " + " | ".join(("{{NOMBRE}}: " if m["role"] == "user" else "JARVIS: ") + m["content"][:200] for m in ult) + "] Ahora dice: "


def _hermes_api(t):
    k = None
    for line in open(os.path.join(HOME, ".hermes/.env"), encoding="utf-8"):
        if line.startswith("API_SERVER_KEY="):
            k = line.split("=", 1)[1].strip().strip("\"'")
    if not k:
        return None
    msg = ("[Mensaje hablado desde el PC. Contesta en una o dos frases cortas para leerlas en voz alta, sin comandos, rutas, "
           "código ni listas. Las órdenes son para el PC salvo que diga portátil o laptop. Hazlo directamente, sin pedir confirmación.] " + t)
    body = json.dumps({"model": "hermes-agent", "messages": [{"role": "user", "content": msg}]}).encode()
    req = urllib.request.Request("http://127.0.0.1:8642/v1/chat/completions", body,
                                 {"Authorization": "Bearer " + k, "Content-Type": "application/json",
                                  "X-Hermes-Session-Id": "voz-pc-" + time.strftime("%Y%m%d")})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    return ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or None


def cerebro(t):
    try:
        r = _hermes_api(t)
        if r:
            return r
    except Exception as e:
        log.warning("voz hermes despierto: %s", str(e)[:150])
    return _cerebro_cli(t)


def _cerebro_cli(t):
    msg = ("[Mensaje hablado desde el PC. Contesta en una o dos frases cortas para leerlas en voz alta, "
           "sin comandos, rutas, código ni listas. Toda orden (abrir, cerrar, archivos, volumen...) es en el PC de {{NOMBRE}} salvo que diga portátil o laptop. Hazlo directamente, sin pedir confirmación.] " + _contexto() + t)
    for sel in (["--agent", "main", "--session-id", "voz-pc"], ["--agent", "main"]):
        try:
            p = subprocess.run([os.path.expanduser("~/.local/bin/hermes"), "-z", msg],
                               capture_output=True, text=True, timeout=110, env=ENV)
            r = _extrae(p.stdout) if p.returncode == 0 else None
            if r:
                return r
            log.warning("voz openclaw rc=%s %s", p.returncode, (p.stderr or p.stdout)[-300:])
        except Exception as e:
            log.warning("voz openclaw: %s", e)
    return None


def ollama(t):
    body = json.dumps({"model": "qwen3-jarvis-fast", "stream": False, "options": {"num_predict": 150},
                       "messages": [{"role": "system", "content": "Eres JARVIS, el mayordomo de {{NOMBRE}}. Responde en español, en una o dos frases, llamándole señor."},
                                    {"role": "user", "content": t}]}).encode()
    try:
        req = urllib.request.Request("http://{{PC_IP}}:11434/api/chat", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.load(r)["message"]["content"]
    except Exception as e:  # noqa: BLE001  arreglo 80: si el PC no responde, el Ollama del portatil
        log.warning("voz ollama pc: %s; pruebo el del portatil", str(e)[:80])
        b2 = json.loads(body); b2["model"] = "llama3.2:3b"
        req = urllib.request.Request("http://127.0.0.1:11434/api/chat", json.dumps(b2).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)["message"]["content"]


DIRECTO_SYS = ("Eres JARVIS, el mayordomo de {{NOMBRE}}. Hablas en español y le llamas señor. Tu respuesta se leerá en voz alta: "
               "una o dos frases cortas, naturales, sin listas, comandos, rutas ni código. "
               "Habla en español de España, cercano y natural como una persona de verdad; usa expresiones "
               "normales del día a día y nunca suenes a traducción literal del inglés ni a robot (arreglo 101). "
               "Si lo que pide requiere HACER algo (abrir o cerrar apps, archivos, volumen, apagar o encender, correo, calendario, "
               "buscar en internet, recordatorios, mensajes, cualquier acción en el PC o el portátil) o datos actuales que no sabes "
               "(tiempo, noticias, precios), responde solo la palabra ACCION. Nunca pidas confirmación para abrir o cerrar apps.")
_hist = []
_HIST_T = [0.0]


def _hist_reciente():
    # arreglo 80: memoria de conversacion: ultimos 12 turnos, y se olvida tras 15 min sin hablar
    if time.time() - _HIST_T[0] > 900:
        _hist.clear()
    _HIST_T[0] = time.time()
    return _hist[-24:]


def _contexto_momento():
    n = datetime.datetime.now()
    juego = ""
    try:
        juego = open(os.path.join(HOME, ".config/jarvis/ultimo_juego.txt"), encoding="utf-8").read().strip()
    except OSError:
        pass
    return (f"[Contexto, no lo repitas: son las {n.hour}:{n.minute:02d} del {DIAS[n.weekday()]}"
            + (f"; el último juego que abrió fue {juego}" if juego else "")
            + ". Habla como en una conversación natural con una persona: varía las frases, no repitas fórmulas, "
              "respuestas breves de 1 a 3 frases.]\n")


_VARIANTES = {"Abriendo": ["Abriendo {x}, señor.", "Enseguida, señor: abriendo {x}.", "Ahora mismo abro {x}, señor.", "Marchando {x}, señor."],
              "Cerrando": ["Cerrando {x}, señor.", "Hecho, señor: cierro {x}.", "Ahora mismo cierro {x}, señor.", "Fuera {x}, señor."]}


def _varia(r):
    m = re.fullmatch(r"(Abriendo|Cerrando) (.{1,60}?),? señor\.", r or "")
    return random.choice(_VARIANTES[m.group(1)]).format(x=m.group(2)) if m else r


DIRECTO_SYS += (" Si el mensaje parece ruido, una exclamación suelta, aplausos, música o palabras sin sentido que no van "
                "dirigidas a ti, responde solo la palabra RUIDO. Si es una orden de abrir o cerrar una aplicación, o de abrir, "
                "instalar o actualizar un juego, aunque esté mal oída deduce lo más probable (por ejemplo 'abre estím' o 'Avro "
                "Steam' es abre Steam; 'abre el escord' es abre Discord) y responde solo: ORDEN: seguido de la orden corregida, "
                "como 'abre Steam', 'cierra Spotify' o 'actualiza Dota 2 en Steam'.")


_JUEGOS_F = os.path.join(HOME, ".config/jarvis/juegos_ok.txt")
_BASE_SYS = DIRECTO_SYS + (
    " Si el señor pide hacer algo en la pantalla del PC con el ratón o el teclado (pulsar un botón, entrar en un menú, "
    "escribir algo, bajar la página, elegir una opción, etc.) y no es solo abrir o cerrar una app o un juego, responde "
    "solo: PANTALLA: seguido del objetivo claro en una frase."
    " Esta regla vale para CUALQUIER accion que no tenga ya una orden propia (arreglo 96): "
    "en vez de decir que no puedes o que algo no esta en tu lista, responde PANTALLA: y se hara "
    "con el raton y el teclado. Solo di que no has podido TRAS intentarlo, y entonces di que "
    "intentaste y que lo impidio (inicio de sesion, CAPTCHA, la app no responde, o que hace falta "
    "la palabra clave). Nunca des por hecho un resultado que no hayas comprobado."
    " Si el senor pide abrir una pagina o un sitio web, entrar a YouTube, o buscar algo en YouTube "
    "(arreglo 97), responde solo: WEB: seguido de la URL completa (https://...). YouTube: "
    "https://www.youtube.com ; buscar en YouTube: https://www.youtube.com/results?search_query=TERMINOS "
    "(los terminos separados por +). Se abre en el navegador que haya (Brave si no hay Chrome).")


def _juegos_ok():
    try:
        return [x for x in open(_JUEGOS_F, encoding="utf-8").read().split("\n") if x.strip()]
    except OSError:
        return []


def _apunta_juego(n):
    if n and n.lower() not in [x.lower() for x in _juegos_ok()]:
        try:
            with open(_JUEGOS_F, "a", encoding="utf-8") as f:
                f.write(n.strip() + "\n")
            _aprende_si_falta(n.strip())
        except OSError:
            pass


def _fon(s):
    # como suena en español: ph=f, h muda, v=b, y=i, z=s, k/q=c, "sm/rm/lm" se oyen "m", letras dobles una
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFD", str(s).lower()) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]", "", s)
    for x, y in (("ph", "f"), ("qu", "c"), ("ll", "i"), ("sh", "s"), ("ch", "c"), ("h", ""), ("k", "c"), ("q", "c"),
                 ("z", "s"), ("v", "b"), ("w", "u"), ("y", "i"), ("x", "s")):
        s = s.replace(x, y)
    s = re.sub(r"[srl]m", "m", s)
    return re.sub(r"(.)\1+", r"\1", s)


def _parecido_fon(q, nombres, umbral):
    import difflib
    a, fa = re.sub(r"[^a-z0-9]", "", str(q).lower()), _fon(q)
    mejor, r0 = None, 0.0
    for n in nombres:
        b, fb = re.sub(r"[^a-z0-9]", "", n.lower()), _fon(n)
        if not (a and b):
            continue
        if a == b or fa == fb or (len(a) >= 4 and a in b) or (len(fa) >= 4 and fa in fb):
            return n
        r = max(difflib.SequenceMatcher(None, a, b).ratio(), difflib.SequenceMatcher(None, fa, fb).ratio())
        if r >= umbral and r > r0:
            mejor, r0 = n, r
    return mejor


def _es_juego(q):
    return _parecido_fon(q, _juegos_ok(), 0.75)


def _refresca_sys():
    global DIRECTO_SYS
    js = ", ".join(_juegos_ok()[-40:])
    DIRECTO_SYS = _BASE_SYS + (
        (" Juegos que el señor tiene y usa: " + js + "." if js else "") +
        " Si el mensaje es solo un nombre, aunque esté mal oído, que se parece a uno de esos juegos, a un videojuego conocido "
        "o a un programa, es una orden de abrirlo: responde ORDEN: abre <nombre correcto> (por ejemplo 'Farmofobia' o 'fasmo' "
        "es ORDEN: abre Phasmophobia). Si pide descargar, instalar o actualizar un juego, aunque no diga la tienda, responde "
        "ORDEN: instala <juego> u ORDEN: actualiza <juego>, y añade 'en Epic' solo si lo dijo él o si el juego solo está en "
        "Epic Games (por ejemplo Fortnite).")


def _obsidian(t):
    """Solo las notas de Obsidian que vienen al caso, cortas (voz): nada si no hay ninguna."""
    try:
        import jx_obsidian
        c = jx_obsidian.contexto(t, max_chars=700, top_k=2)
        return (c + "\n\n") if c else ""
    except Exception:  # noqa: BLE001
        return ""


def directo(t):
    _refresca_sys()
    key = open(os.path.join(HOME, ".config/jarvis/anthropic.key"), encoding="utf-8").read().strip()
    body = json.dumps({"model": "claude-haiku-5-5", "max_tokens": jx.tope_tokens("voz", 220), "thinking": {"type": "disabled"}, "system": [{"type": "text", "text": DIRECTO_SYS, "cache_control": {"type": "ephemeral"}}],
                       "messages": _hist_reciente() + [{"role": "user", "content": _contexto_momento() + _obsidian(t) + t}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", body,
                                 {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    jx.apunta_gasto(d.get("usage"), "mayordomo")
    out = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text").strip()
    out = re.sub(r"^[\W_]+", "", out or "")
    if re.match(r"ORDEN\b", out, re.I):
        c = re.sub(r"^ORDEN\W*", "", out, flags=re.I).strip().rstrip(".")
        log.warning("voz: deduzco %r -> %r", t[:60], c[:60])
        for f in (juego_directo, lambda x: app_directa(orden(x)), juego_buscado):
            try:
                r = f(c)
            except Exception:  # noqa: BLE001
                r = None
            if r:
                return r
        return None
    if re.match(r"PANTALLA\b", out, re.I):
        obj = re.sub(r"^PANTALLA\W*", "", out, flags=re.I).strip()
        if obj:
            log.warning("voz: pantalla %r", obj[:80])
            subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pantalla.py"), obj,
                              "--pasos", "12"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV, start_new_session=True)
            return "Enseguida, señor."
    if re.match(r"WEB\b", out, re.I):  # arreglo 97
        url = re.sub(r"^WEB\W*", "", out, flags=re.I).strip()
        if url.startswith(("http://", "https://")):
            subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pc_do.py"), "web", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV, start_new_session=True)
            return "Abriendo la pagina en el navegador, senor."
    if out.upper().startswith("RUIDO"):
        return "__RUIDO__"
    if not out or out.upper().replace("Ó", "O").startswith("ACCION"):
        return None
    _hist.extend([{"role": "user", "content": t}, {"role": "assistant", "content": out}])
    del _hist[:-12]
    return out


import concurrent.futures as _cf
_POOL = _cf.ThreadPoolExecutor(4)
_OK_F = os.path.join(HOME, ".config/jarvis/apps_ok.txt")


def _apps_ok():
    try:
        return set(x for x in open(_OK_F, encoding="utf-8").read().split("\n") if x)
    except OSError:
        return set()


def app_directa(t):
    m = re.match(r"^(abre|cierra)\s+(?:el\s+|la\s+|los\s+|las\s+)?(.+?)(?:\s+(?:en|del)\s+(?:el\s+)?(?:pc|ordenador))?$", t.strip(), re.I)
    if not m or len(m.group(2)) > 40:
        return None
    abre, app = m.group(1).lower() == "abre", m.group(2).strip().lower()
    if re.search(r"\b(ajustes|configuraci[oó]n|opciones|men[uú]|pesta[ñn]a|perfil|carpeta|p[aá]gina|chat|canal|apartado|secci[oó]n)\b", app):
        return None
    if abre and _es_juego(app):
        return None
    if app not in _apps_ok() and len(app) >= 4:
        par = _parecido_fon(app, sorted(_apps_ok()), 0.8)
        if par:
            app, t = par, f"{m.group(1)} {par}"
    if app in _apps_ok():
        _POOL.submit(_app_directa_lenta, t)
        return f"{'Abriendo' if abre else 'Cerrando'} {app}, señor."
    r = _app_directa_lenta(t)
    if abre and r and re.search(r"no (?:he )?pod|no puedo|fuera de|allowlist|no est[aá]|no encuentro", r, re.I):
        return None  # no es una app de la lista: que lo intenten el buscador de juegos y la deduccion
    if r and abre:
        try:
            with open(_OK_F, "a", encoding="utf-8") as f:
                f.write(app + "\n")
            _aprende_si_falta(app)
        except OSError:
            pass
    return r


def _app_directa_lenta(t):
    m = re.match(r"^(abre|cierra)\s+(?:el\s+|la\s+|los\s+|las\s+)?(.+?)(?:\s+(?:en|del)\s+(?:el\s+)?(?:pc|ordenador))?$", t.strip(), re.I)
    if not m or len(m.group(2)) > 40:
        return None
    acc, app = ("open" if m.group(1).lower() == "abre" else "close"), m.group(2).strip().lower()
    p = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pc_do.py"), acc, app],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=ENV)
    try:
        out, _ = p.communicate(timeout=1.5)
    except subprocess.TimeoutExpired:
        return f"{'Abriendo' if acc == 'open' else 'Cerrando'} {app}, señor."
    if p.returncode != 0 or re.search(r"error|offline|denied|deneg|fail|no encontr|not found|no permitid", out or "", re.I):
        log.warning("voz app_directa %s %s: rc=%s %s", acc, app, p.returncode, (out or "")[-200:])
        return None
    return f"Listo, señor. He {'abierto' if acc == 'open' else 'cerrado'} {app}."


JUEGOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "juegos.py")
_pend = {}
_VJ = r"(instala|instálame|instalame|descarga|descárgame|descargame|actualiza|actualízame|actualizame|abre|ábreme|abreme|avro|abro|juega|jugar|pon)"


def _cuenta(t):
    p = t.lower()
    if re.search(r"fan|f[ao]nos|primer|principal|\buno\b", p):
        return "{{CUENTA_STEAM_1_MIN}}"
    if re.search(r"hid|idr|segund|secundari|\bdos\b", p):
        return "{{CUENTA_STEAM_2}}"
    return None


def _lanza_juego(tienda, acc, juego, cuenta):
    args = [sys.executable, JUEGOS, tienda, acc, juego] + (["--cuenta", cuenta] if cuenta else [])
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV, start_new_session=True)
    if acc != "cliente":
        _apunta_juego(juego)
    verbo = {"instalar": "Instalando", "actualizar": "Actualizando", "abrir": "Abriendo"}.get(acc, "Abriendo")
    quien = " con la cuenta secundaria, {{CUENTA_STEAM_2}}" if cuenta and cuenta != "{{CUENTA_STEAM_1_MIN}}" else ""
    if acc == "cliente":
        return f"Abriendo Steam{quien}, señor."
    return _chispa(f"{verbo} {juego} en {'Steam' if tienda == 'steam' else 'Epic'}{quien}, señor.", juego)


def _chispa(base, juego):
    import random
    if random.random() > 0.4:
        return base
    try:
        key = open(os.path.join(HOME, ".config/jarvis/anthropic.key"), encoding="utf-8").read().strip()
        body = json.dumps({"model": "claude-haiku-5-5", "max_tokens": jx.tope_tokens("voz_chispa", 80), "thinking": {"type": "disabled"},
                           "system": "Eres JARVIS, mayordomo británico con humor fino. Da UNA frase muy corta (máx. 12 palabras), "
                                     "ingeniosa y con relación al juego o programa, para añadir tras confirmar que lo abres. Sin comillas.",
                           "messages": [{"role": "user", "content": juego}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", body,
                                     {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=2.5) as r:
            d = json.load(r)
            jx.apunta_gasto(d.get("usage"), "mayordomo")
        f = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text").strip().strip('"')
        return base + " " + f if f and len(f) < 120 else base
    except Exception:  # noqa: BLE001
        return base


def _en_steam(q):
    try:
        p = subprocess.run([sys.executable, JUEGOS, "buscar", q], capture_output=True, text=True, timeout=8, env=ENV)
    except Exception:  # noqa: BLE001
        return None
    mm = re.match(r"Steam: (.+) \(id \d+\)", (p.stdout or "").strip())
    if not mm:
        return None
    import difflib
    a, b = re.sub(r"[^a-z0-9]", "", q.lower()), re.sub(r"[^a-z0-9]", "", mm.group(1).lower())
    if not a or not (a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.6):
        return None
    return mm.group(1)


def _steam_o_epic(q):
    n = _es_juego(q) or _en_steam(q)
    return ("steam", n) if n else ("epic", q)


def _juegos_otros():
    try:
        return [x.strip() for x in open(os.path.join(HOME, ".config/jarvis/juegos_otros.txt"), encoding="utf-8-sig") if x.strip()]
    except OSError:
        return []


def juego_buscado(t):
    t = re.split(r"\b[jhy][aáeé]?rv[ií]s\b[\s,.!¡]*", t.strip().rstrip(".!?¡¿ "), flags=re.I)[-1].strip() or t
    t, cta = _quita_cuenta(t)
    m = re.fullmatch(r"abre\s+(?:el\s+|la\s+)?(?:juego\s+)?(.{2,40})", orden(t).strip(), re.I)
    if not m or re.fullmatch(r"steam|epic(?:\s+games)?", m.group(1).strip(), re.I):
        return None
    q = m.group(1).strip()
    otro = _parecido_fon(q, _juegos_otros(), 0.8)  # arreglo 90: juego de otra tienda -> su acceso directo del PC
    if otro:
        r = _app_directa_lenta(f"abre {otro.lower()}")
        if r and not re.search(r"no (?:he )?pod|fuera de|allowlist", r, re.I):
            return r
        return f"{otro} es de otra tienda y no lo tengo en la lista de accesos directos del PC, señor. Ábralo desde su lanzador."
    n = _es_juego(q) or _en_steam(q)
    return _lanza_juego("steam", "abrir", n, cta or "{{CUENTA_STEAM_1_MIN}}") if n else None


def _esperando_cuenta():
    return bool(_pend) and time.time() - _pend.get("ts", 0) < 90


def _quita_cuenta(t):
    m = re.search(r"\s+(?:con|en)\s+(?:la\s+)?(?:cuenta\s+)?(?:de\s+)?({{USUARIO}}\w*|f[ao]nos\w*|hidr?y?c?k?\w*|idrick|principal|secundaria|primera|segunda)\s*$", t, re.I)
    if m:
        return t[:m.start()].strip(), _cuenta(m.group(1))
    return t, None


def juego_directo(t):
    t = t.strip().rstrip(".!?¡¿ ")
    t = re.split(r"\b[jhy][aáeé]?rv[ií]s\b[\s,.!¡]*", t, flags=re.I)[-1].strip() or t
    t, _cta = _quita_cuenta(t)
    t = re.sub(r"^(?:p[oó]n(?:me|te)?|ponga)\s+a\s+(actualiz|descarg|instal)ar\b", lambda x: x.group(1) + "a", t, flags=re.I)
    if _pend and time.time() - _pend.get("ts", 0) < 90:
        c = _cuenta(t)
        d = dict(_pend)
        _pend.clear()
        if c:
            return _lanza_juego(d["tienda"], d["acc"], d["juego"], c)
        if not d.get("otra") and len(t.split()) <= 4:
            d.update({"otra": 1, "ts": time.time()})
            _pend.update(d)
            return "Perdone, señor, ¿la primera, {{CUENTA_STEAM_1_NOMBRE}}, o la segunda, {{CUENTA_STEAM_2}}?"
    if re.fullmatch(r"abre\s+(?:el\s+)?(?:steam|e?st[ií][mn]|e?ste?am|stin)", orden(t).strip(), re.I):
        return _lanza_juego("steam", "cliente", "Steam", _cta or "{{CUENTA_STEAM_1_MIN}}")
    m = re.match(r"^(?:por favor\s+)?" + _VJ + r"\s+(?:el\s+|la\s+|a\s+|al\s+)?(?:juego\s+)?(.+?)(?:\s+(?:en|de|desde)\s+(steam|epic(?:\s+games)?))?$", t, re.I)
    if not m:
        return None
    v, juego, tienda = m.group(1).lower(), m.group(2).strip(), (m.group(3) or "").lower()
    if v.startswith(("instal", "descarg")):
        acc = "instalar"
    elif v.startswith("actualiz"):
        acc = "actualizar"
    elif tienda:
        acc = "abrir"
    else:
        return None
    if not juego or len(juego) > 50:
        return None
    if not tienda:
        tienda, juego = _steam_o_epic(juego)
    tienda = "epic" if tienda.startswith("epic") else "steam"
    if tienda == "epic":
        return _lanza_juego(tienda, acc, juego, None)
    return _lanza_juego(tienda, acc, juego, _cta or "{{CUENTA_STEAM_1_MIN}}")


# --- arreglo 72: pronunciacion de nombres (la voz del PC es española y lee "Phasmophobia" como "pasmopobia") ---
_PRON_F = os.path.join(HOME, ".config/jarvis/pronuncia.json")
_PRON_BASE = {"Phasmophobia": "Fasmofobia", "Steam": "Estim", "Spotify": "Espotifai", "Discord": "Díscord",
              "Epic Games": "Épic Geims", "Epic": "Épic", "{{CUENTA_STEAM_2}}": "Jídrik", "{{CUENTA_STEAM_1}}": "Fánost", "{{CUENTA_STEAM_1_NOMBRE}}": "Fánost",
              "Chrome": "Crom", "YouTube": "Yutub", "WhatsApp": "Guasap", "Counter-Strike": "Cáunter Estráik",
              "Fortnite": "Fórtnait", "Visual Studio Code": "Vísual Estudio Coud", "Telegram": "Télegram",
              "Minecraft": "Máincraft", "League of Legends": "Lig of Léyends", "Valorant": "Válorant",
              "Rocket League": "Róquet Lig", "Among Us": "Amóng As", "Call of Duty": "Col of Diúti", "Warzone": "Guorzón",
              "Grand Theft Auto": "Grand Zeft Óto", "Elden Ring": "Élden Ring", "Cyberpunk": "Sáiberpank", "Overwatch": "Overguatch",
              "Apex Legends": "Éipex Léyends", "Rust": "Rast", "Dead by Daylight": "Ded bai Déilait", "Lethal Company": "Lízal Cómpani",
              "Notion": "Nóushon", "Word": "Guord", "Excel": "Éxcel", "PowerPoint": "Páuer Póint", "Outlook": "Áutluc",
              "OBS": "O Be Ese", "Netflix": "Nétflix", "Twitch": "Tuich", "Zoom": "Zum", "Teams": "Tims"}
_PRON = {"d": None, "aprendiendo": set()}


_PRON_MT = [0.0]


def _pron_dic():
    try:
        mt = os.path.getmtime(_PRON_F)
    except OSError:
        mt = 0.0
    if mt != _PRON_MT[0]:  # la tarea diaria lo ha ampliado: lo vuelvo a leer
        _PRON_MT[0] = mt
        _PRON["d"] = None
    if _PRON["d"] is None:
        d = dict(_PRON_BASE)
        try:
            d.update(json.load(open(_PRON_F, encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
        _PRON["d"] = d
    return _PRON["d"]


def _pron_regla(n):
    # para nombres que aun no se ha aprendido: ph suena f, th suena z, "sh" suena "s"
    return re.sub(r"(?i)ph", lambda m: "F" if m.group(0)[0].isupper() else "f", n).replace("th", "z").replace("sh", "s")


def _pron_aprende(n):
    try:
        key = open(os.path.join(HOME, ".config/jarvis/anthropic.key"), encoding="utf-8").read().strip()
        body = json.dumps({"model": "claude-haiku-5-5", "max_tokens": jx.tope_tokens("pronuncia", 40), "thinking": {"type": "disabled"},
                           "system": "Devuelves SOLO cómo se escribiría un nombre en español para que una voz española lo lea "
                                     "como se pronuncia de verdad (normalmente en inglés). Ejemplos: Phasmophobia -> Fasmofobia, "
                                     "Spotify -> Espotifai, Fortnite -> Fórtnait, Steam -> Estim. Si ya se lee bien en español, "
                                     "devuélvelo igual. Sin comillas ni explicaciones.",
                           "messages": [{"role": "user", "content": n}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", body,
                                     {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
            jx.apunta_gasto(d.get("usage"), "mayordomo")
        out = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text").strip().strip("\"'«».")
        if out and len(out) <= 60 and "\n" not in out:
            dic = _pron_dic()
            dic[n] = out
            try:
                guardado = json.load(open(_PRON_F, encoding="utf-8"))
            except Exception:  # noqa: BLE001
                guardado = {}
            guardado[n] = out
            json.dump(guardado, open(_PRON_F, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            log.warning("voz: aprendo a pronunciar %r -> %r", n, out)
    except Exception as e:  # noqa: BLE001
        log.warning("voz: no pude aprender a pronunciar %r (%s)", n, str(e)[:80])
    finally:
        _PRON["aprendiendo"].discard(n)


def _aprende_si_falta(n):
    # juego o app nuevo: aprendo ya como se pronuncia, en segundo plano
    try:
        dic = _pron_dic()
        if n and len(n) >= 4 and n not in _PRON["aprendiendo"] and not any(k.lower() == n.lower() for k in dic):
            _PRON["aprendiendo"].add(n)
            _POOL.submit(_pron_aprende, n)
    except Exception:  # noqa: BLE001
        pass


def _pron_conocidos():
    ns = set(_juegos_ok()) | set(_apps_ok())
    try:
        ns.add(open(os.path.join(HOME, ".config/jarvis/ultimo_juego.txt"), encoding="utf-8").read().strip())
    except OSError:
        pass
    return {n for n in ns if n and len(n) <= 40}


def _pronuncia(texto):
    if not texto:
        return texto
    dic = _pron_dic()
    for n in _pron_conocidos():
        if n not in dic and not any(k.lower() == n.lower() for k in dic) and n not in _PRON["aprendiendo"] \
                and re.search(r"[a-z]", n, re.I) and re.search(re.escape(n), texto, re.I):
            _PRON["aprendiendo"].add(n)
            _POOL.submit(_pron_aprende, n)  # la proxima vez ya lo dice bien
            texto = re.sub(r"(?<![\w])" + re.escape(n) + r"(?![\w])", _pron_regla(n), texto, flags=re.I)
    for k in sorted(dic, key=len, reverse=True):
        texto = re.sub(r"(?<![\w])" + re.escape(k) + r"(?![\w])", dic[k], texto, flags=re.I)
    return texto


def responder(t):
    for nombre, f in (("local", local), ("juego", juego_directo), ("app", lambda x: app_directa(orden(x))), ("juego2", juego_buscado), ("rapido", lambda x: rapido(orden(x))), ("directo", directo), ("haiku", cerebro), ("pc", ollama)):
        if nombre == "pc" and _reserva_caida("ollama-pc"):
            continue
        try:
            r = limpia_salida(f(t) or "")
        except Exception as e:
            log.warning("voz %s: %s", nombre, e)
            r = ""
        if r:
            if nombre in ("app", "juego", "juego2"):
                r = _varia(r)
            if nombre != "directo":
                _hist.extend([{"role": "user", "content": t}, {"role": "assistant", "content": r}])
                del _hist[:-12]
            return r, nombre
    return "Ahora mismo estoy saturado, señor. Inténtelo en un momento.", "ninguno"


async def _send(ws, m):
    try:
        await ws.send(json.dumps(m, ensure_ascii=False))
    except Exception as e:
        log.warning("voz send: %s", e)


def _lev(a, b):
    f = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        g = [i]
        for j, y in enumerate(b, 1):
            g.append(min(f[j] + 1, g[j - 1] + 1, f[j - 1] + (x != y)))
        f = g
    return f[-1]


def _es_nombre(w):
    w = w.replace("á", "a").replace("í", "i").replace("é", "e")
    return len(w) >= 4 and w not in ("paris", "marvin", "martes", "harina") and _lev(w, "jarvis") <= 2


def nombre_en(texto):
    """'no' = no dijo Jarvis, 'solo' = solo dijo el nombre, 'si' = nombre + orden."""
    pal = re.findall(r"[a-záéíóúñü]+", texto.lower())
    if not any(_es_nombre(w) for w in pal):
        return "no"
    if all(_es_nombre(w) or w in ("hey", "ey", "ei", "ok", "okay", "oye", "hola", "jey", "eh") for w in pal):
        return "solo"
    return "si"


async def handle_audio(ws, data):
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    loop = asyncio.get_running_loop()
    async with _lock:
        t0 = time.time()
        try:
            texto = await loop.run_in_executor(None, transcribir, data.get("data") or data.get("audio") or "")
        except Exception:
            log.exception("voz stt")
            texto = ""
        t1 = time.time()
        texto = limpia_entrada(texto)
        if texto and data.get("need_name"):
            n = nombre_en(texto)
            if n == "no":
                log.warning("voz: sin nombre, ignoro %r", texto[:60])
                await _send(ws, {"type": "reply", "text": "", "end": True})
                return
            if n == "solo":
                await _send(ws, {"type": "transcript", "text": texto})
                await _send(ws, {"type": "reply", "text": ""})
                return
        if not texto:
            await _send(ws, {"type": "reply", "text": "", "end": True})
            return
        log.warning("voz: oyo %r", texto[:150])
        await _send(ws, {"type": "transcript", "text": texto})
        if ADIOS.match(texto) and not _esperando_cuenta():
            await _send(ws, {"type": "reply", "text": random.choice(["A su servicio, señor.", "Aquí estaré, señor.", "Cuando me necesite, señor.", "Hasta luego, señor."]), "end": True})
            return
        resp, ruta = await loop.run_in_executor(None, responder, texto)
        if resp == "__RUIDO__" or re.sub(r"[\W_]", "", str(resp or "")).upper() in ("RUIDO", "ORDEN"):
            await _send(ws, {"type": "reply", "text": "", "end": True})
        else:
            await _send(ws, {"type": "reply", "text": _pronuncia(resp)})
        log.warning("voz: oido %.1fs, total %.1fs via %s", t1 - t0, time.time() - t0, ruta)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    if sys.argv[1:2] == ["--oido"]:
        b = io.BytesIO()
        with wave.open(b, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0\0" * 16000)
        _whisper()
        print("oido: OK", repr(transcribir("data:audio/wav;base64," + base64.b64encode(b.getvalue()).decode())))
    elif sys.argv[1:2] == ["--prueba"]:
        t0 = time.time(); r, ruta = responder(" ".join(sys.argv[2:]))
        print(f"prueba [{ruta}, {time.time() - t0:.1f}s]: {r[:160]}")
