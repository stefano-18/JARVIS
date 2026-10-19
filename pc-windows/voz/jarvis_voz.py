"""
JARVIS voz (PC): oido + boca de JARVIS en el PC, sin ventanas.

- Escucha el microfono (FIFINE si esta) con la palabra "Hey JARVIS" (openWakeWord).
- Al oirla responde AL INSTANTE con una frase de mayordomo pregrabada (sin IA, sin coste).
- Graba lo que dice el usuario y lo manda al cerebro (jarvis-v2 en la laptop, ws :8765)
  con el mismo formato que el puente antiguo.
- Reproduce por los altavoces el audio de respuesta que manda la laptop.
- Publica el estado (reposo / escuchando / hablando + nivel) en ws://127.0.0.1:8770
  para que el fondo de Wallpaper Engine ilumine los bordes solo con voz real.
Uso extra:  pythonw jarvis_voz.py --send hablando|reposo|escuchando   (prueba del fondo)
            python  jarvis_voz.py --status                           (clientes del relay)
"""
import asyncio
import base64
import collections
import ctypes
import glob
import io
import json
import logging
import logging.handlers
import os
import queue
import random
import re
import unicodedata
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave

import numpy as np
import websockets

BASE = os.path.dirname(os.path.abspath(__file__))
WS_URL = os.getenv("JARVIS_WS_URL", "ws://{{PORTATIL_IP}}:8765")
RELAY_HOST, RELAY_PORT = "127.0.0.1", 8770
RATE, CHUNK = 16000, 1280            # 80 ms, lo que pide openWakeWord
VAD = float(os.getenv("JARVIS_VAD", "25"))   # mismo umbral RMS que el puente FIFINE
WAKE_TH = float(os.getenv("JARVIS_WAKE_TH", "0.5"))   # un poco mas sensible: tambien "ok jarvis"
PAUSE_ACK = 15                        # ~1.2 s de silencio tras "Hey JARVIS" -> "¿Si, senor?"
ONE_BREATH = 2                        # 2 trozos de voz tras el nombre -> orden en la misma frase, sin ack
WAKE_TAIL = 3                         # ~0.25 s: final de "...vis" que no cuenta como orden
POST_MAX = 30                         # ~2.4 s maximo esperando
PREROLL = 20                          # ~1.6 s antes del wake word (incluye "hey jarvis")
END_SILENCE = 11                      # ~0.9 s de silencio tras hablar cierra la frase
END_SHORT = 8                         # ~0.65 s si solo dijo una o dos palabras ("la hora")
KEEP_EDGE = 3                         # ~0.25 s de margen antes y despues de la voz
WAIT_SPEECH = 62                      # ~5 s esperando a que empiece a hablar
MAX_REC = 190                         # ~15 s maximo, para frases largas
CONV_WAIT = 75                        # ~6 s en conversacion esperando a que vuelva a hablar
BARGE = os.environ.get("JARVIS_BARGE", "1") != "0"   # callarse si le hablan encima
WAKE_SOFT = float(os.getenv("JARVIS_WAKE_SOFT", "0.15"))  # "Jarvis" a secas o mal dicho: lo confirma la transcripcion
GAME_DIRS = ("\\steamapps\\common\\", "\\epic games\\", "\\riot games\\", "\\xboxgames\\",
             "\\ubisoft game launcher\\games\\", "\\ea games\\", "\\gog galaxy\\games\\")
NOT_GAMES = ("explorer.exe", "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe",
             "vlc.exe", "spotify.exe", "wallpaper32.exe", "wallpaper64.exe", "discord.exe",
             "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "code.exe", "pythonw.exe")
GAME = {"on": False, "exe": ""}       # jugando: sin palabra de activacion, solo Ctrl+Alt+J
HOTKEY = {"hit": False}               # Ctrl+Alt+J = como decir "Hey JARVIS"
REPLY_WAIT = 150                      # s maximos esperando la respuesta del cerebro
DOWN_FOR = 20                        # s sin reintentar una voz online que fallo
END_WORDS = ("gracias", "esta bien asi", "eso es todo", "nada mas", "ya esta", "adios",
             "hasta luego", "puedes descansar", "nada jarvis", "eso seria todo")
FILLER = {"jarvis", "senor", "muchas", "muchisimas", "vale", "ok", "okay", "perfecto", "muy", "bien",
          "asi", "eso", "es", "todo", "por", "ahora", "de", "momento", "nada", "mas", "y", "pues",
          "genial", "estupendo", "listo", "entonces", "hey", "oye", "si", "no", "te", "lo"}
TTS_RATE = 22050                      # Piper medium, para audio crudo sin cabecera
ACKS = ["¿Sí, señor?", "Dígame, señor.", "Le escucho."]   # cortas: no tapan la orden
FILLS = ["Enseguida, señor.", "Ahora mismo, señor.", "En ello, señor."]
ACTION = re.compile(r"^(abre|abreme|abrir|cierra|cierrame|cerrar|pon|ponme|sube|baja|apaga|enciende|"
                    r"reinicia|suspende|silencia|quita|reproduce|busca|lanza|inicia|para|pausa)\b")
VERSION = "v27"
FILL_ON = os.getenv("JARVIS_FILL", "0") == "1"   # el cerebro ya contesta "Abriendo X, senor" al momento
TTS_CHAIN = ["edge"]   # solo Edge (Alvaro o la elegida en voz.txt); si falla, silencio
NO_WINDOW = 0x08000000
PLAY_VOLUME = int(os.getenv("JARVIS_VOLUME", "700"))   # 0..1000

h = logging.handlers.RotatingFileHandler(os.path.join(BASE, "jarvis_voz.log"),
                                         maxBytes=1_000_000, backupCount=1, encoding="utf-8")
logging.basicConfig(handlers=[h], level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.info


# ---------------------------------------------------------------- relay (fondo)
clients = set()
state = {"s": "reposo"}


async def relay_handler(ws):
    clients.add(ws)
    try:
        await ws.send(json.dumps({"state": state["s"]}))
        async for msg in ws:
            try:
                obj = json.loads(msg)
            except Exception:
                continue
            if obj.get("cmd") == "clients":
                await ws.send(json.dumps({"clients": len(clients) - 1}))
            elif "state" in obj or "level" in obj:
                if obj.get("state"):
                    state["s"] = obj["state"]
                await broadcast(obj, skip=ws)
    finally:
        clients.discard(ws)


async def broadcast(obj, skip=None):
    if not clients:
        return
    msg = json.dumps(obj)
    for c in list(clients):
        if c is skip:
            continue
        try:
            await c.send(msg)
        except Exception:
            clients.discard(c)


async def set_state(s):
    if state["s"] != s:
        state["s"] = s
        await broadcast({"state": s})


# ---------------------------------------------------------------- audio salida
def _mci(cmd):
    buf = ctypes.create_unicode_buffer(256)
    return ctypes.windll.winmm.mciSendStringW(cmd, buf, 255, 0)


def _mci_q(cmd):
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.winmm.mciSendStringW(cmd, buf, 255, 0)
    return buf.value


MAIN_LOOP = {"l": None}
PLAYER = {"stop": False}               # True = el senor le ha interrumpido: callarse ya


def play_file(path):
    alias = "jx%d" % random.randint(1000, 9999)
    err = _mci('open "%s" type mpegvideo alias %s' % (path, alias))
    if err:
        log("no se pudo abrir el audio (error %s)" % err)
        return
    _mci("setaudio %s volume to %d" % (alias, PLAY_VOLUME))
    _mci("set %s time format milliseconds" % alias)
    try:
        length = int(_mci_q("status %s length" % alias) or 0) / 1000.0
    except ValueError:
        length = 0.0
    if PLAYER["stop"]:
        _mci("close %s" % alias)
        return
    if MAIN_LOOP["l"]:                  # los bordes se encienden justo cuando empieza a sonar
        asyncio.run_coroutine_threadsafe(set_state("hablando"), MAIN_LOOP["l"])
    _mci("play %s" % alias)
    t0 = time.time()
    limit = min(60.0, length + 0.5) if length > 0 else 60.0
    while time.time() - t0 < limit:     # sin "wait": asi se puede cortar si le hablan encima
        time.sleep(0.04)
        if PLAYER["stop"]:
            _mci("stop %s" % alias)
            break
        if time.time() - t0 > 0.3 and _mci_q("status %s mode" % alias) in ("stopped", ""):
            break                       # termino de sonar
    _mci("close %s" % alias)


def play_bytes(data):
    if data[:4] == b"RIFF":
        ext = ".wav"
    elif data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        ext = ".mp3"
    elif data[:4] == b"OggS":
        ext = ".ogg"
    else:                              # PCM crudo: envolver en WAV
        ext = ".wav"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(TTS_RATE)
            w.writeframes(data)
        tmp.close()
        play_file(tmp.name)
        os.unlink(tmp.name)
        return
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp.write(data)
    tmp.close()
    play_file(tmp.name)
    try:
        os.unlink(tmp.name)
    except Exception:
        pass


def speak_sapi(text):
    safe = text.replace("'", "''")
    ps = ("Add-Type -AssemblyName System.Speech;"
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
          "try{$v=$s.GetInstalledVoices()|?{$_.VoiceInfo.Culture.Name -like 'es*'}|select -First 1;"
          "if($v){$s.SelectVoice($v.VoiceInfo.Name)}}catch{};$s.Speak('%s')" % safe)
    subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                   creationflags=NO_WINDOW, timeout=60)


VOICES = [os.path.join(BASE, "voices", v) for v in
          ("es_ES-davefx-medium.onnx",)]   # la voz masculina de antes: la unica que quiere el senor
VOICE_MODEL = VOICES[0]
_piper = {"v": None, "tried": False}


_piper_lock = threading.Lock()


def piper_voice():
    with _piper_lock:
        return _piper_load()


def _piper_load():
    if not _piper["tried"]:
        _piper["tried"] = True
        try:
            from piper import PiperVoice
            if os.path.exists(VOICE_MODEL):
                _piper["v"] = PiperVoice.load(VOICE_MODEL)
                log("voz local cargada: %s" % os.path.basename(VOICE_MODEL))
        except Exception as e:
            log("sin Piper (%s): voz de Windows" % e)
    return _piper["v"]


def piper_to_wav(text, path):
    v = piper_voice()
    if not v:
        return False
    with wave.open(path, "wb") as w:
        if hasattr(v, "synthesize_wav"):
            v.synthesize_wav(text, w)
        else:
            v.synthesize(text, w)
    soften_wav(path)
    return True


def soften_wav(path, peak=0.45):
    """Baja el volumen y evita que suene saturada (pico a ~-7 dB)."""
    try:
        with wave.open(path, "rb") as r:
            prm = r.getparams()
            a = np.frombuffer(r.readframes(prm.nframes), dtype=np.int16).astype(np.float32)
        m = float(np.max(np.abs(a))) if a.size else 0.0
        if m > 0:
            a = a * (peak * 32767.0 / m)
        with wave.open(path, "wb") as w:
            w.setparams(prm)
            w.writeframes(np.clip(a, -32767, 32767).astype(np.int16).tobytes())
    except Exception as e:
        log("volumen: %s" % e)


FISH_KEY_FILE = os.path.join(BASE, "fish.key")
_why = {}                               # ultimo motivo de fallo de cada voz online
FISH_REF = os.getenv("JARVIS_FISH_VOICE", "21adf3cda02a4aa88dc593353cc9d715")  # Jarvis (es latino)


def fish_to_wav(text, path):
    """Voz de JARVIS de Fish Audio (si hay clave guardada en el PC). Guarda MP3."""
    try:
        key = open(FISH_KEY_FILE, encoding="utf-8").read().strip()
    except Exception:
        return False
    if not key:
        return False
    body = json.dumps({"text": text, "reference_id": FISH_REF, "format": "mp3",
                       "latency": "balanced"}).encode("utf-8")
    for model in ("s2.1-pro-free", None):
        hdr = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
        if model:
            hdr["model"] = model
        try:
            req = urllib.request.Request("https://api.fish.audio/v1/tts", data=body, headers=hdr)
            data = urllib.request.urlopen(req, timeout=25).read()
            if len(data) > 1000:
                with open(path, "wb") as f:
                    f.write(data)
                return True
        except Exception as e:
            _why["fish"] = str(e)[:80]
            log("Fish Audio (%s): %s" % (model or "por defecto", str(e)[:120]))
    return False


# Voces masculinas de mayordomo; "JARVIS, cambia de voz" pasa a la siguiente y se recuerda
EDGE_VOICES = ["es-ES-AlvaroNeural", "es-MX-JorgeNeural", "es-US-AlonsoNeural",
               "es-CO-GonzaloNeural", "es-AR-TomasNeural"]
VOZ_FILE = os.path.join(BASE, "voz.txt")
CHANGE_VOICE = re.compile(r"\b(cambia|cambiar|cambiame|pon|prueba)\b.*\b(voz)\b|\b(otra|siguiente) voz\b")


def edge_voice():
    try:
        v = open(VOZ_FILE, encoding="utf-8").read().strip()
        if v:
            return v
    except Exception:
        pass
    return os.getenv("JARVIS_EDGE_VOICE", EDGE_VOICES[0])


def next_voice():
    cur = edge_voice()
    nxt = EDGE_VOICES[(EDGE_VOICES.index(cur) + 1) % len(EDGE_VOICES)] if cur in EDGE_VOICES else EDGE_VOICES[0]
    with open(VOZ_FILE, "w", encoding="utf-8") as f:
        f.write(nxt)
    log("voz cambiada a %s" % nxt)
    return nxt


def edge_to_file(text, path):
    """Voz gratuita de Microsoft Edge (sin clave). Guarda MP3."""
    try:
        import edge_tts
        try:
            asyncio.run(asyncio.wait_for(edge_tts.Communicate(text, edge_voice(), rate="-8%", pitch="-6Hz").save(path), 12))   # mas grave y pausada
        except Exception as e1:
            log("edge-tts 1er intento: %s" % str(e1)[:100])
            time.sleep(0.5)
            asyncio.run(asyncio.wait_for(edge_tts.Communicate(text, edge_voice()).save(path), 12))   # segundo intento, sin ajustes
        return os.path.exists(path) and os.path.getsize(path) > 1000
    except Exception as e:
        _why["edge"] = "%s %s" % (type(e).__name__, str(e)[:80])
        log("edge-tts: %s" % str(e)[:120])
        return False


_down = {}


def _try(name, fn, text, path):
    if time.time() - _down.get(name, 0) < DOWN_FOR:
        return False
    ok = False
    try:
        ok = fn(text, path)
    except Exception as e:
        log("error voz %s: %s" % (name, e))
    if not ok:
        _down[name] = time.time()       # no perder tiempo con ella en cada frase
    return ok


CACHE = os.path.join(BASE, "cache")


def synth(text):
    """Devuelve (ruta, motor). Las frases repetidas salen de la cache al instante."""
    import hashlib, shutil
    key = hashlib.md5((edge_voice() + "|" + text).encode("utf-8")).hexdigest()
    hit = os.path.join(CACHE, key + ".mp3")
    if os.path.exists(hit):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp.close()
        shutil.copyfile(hit, tmp.name)
        return tmp.name, "cache"
    t0 = time.time()
    path, eng = _synth(text)
    log("tts %.2f s (%s)" % (time.time() - t0, eng))
    if path and eng == "edge" and len(text) <= 120:
        try:
            os.makedirs(CACHE, exist_ok=True)
            shutil.copyfile(path, hit)
            old = sorted(glob.glob(os.path.join(CACHE, "*.mp3")), key=os.path.getmtime)
            for f in old[:-400]:
                os.unlink(f)
        except Exception:
            pass
    return path, eng


def _synth(text):
    for name, fn, ext in (("fish", fish_to_wav, ".mp3"), ("edge", edge_to_file, ".mp3"),
                          ("piper", piper_to_wav, ".wav")):
        if name not in TTS_CHAIN:
            continue
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tmp.close()
        if (fn(text, tmp.name) if len(TTS_CHAIN) == 1 else
                (_try(name, fn, text, tmp.name) if name != "piper" else piper_to_wav(text, tmp.name))):
            return tmp.name, name
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
    return None, None


def sentences(text):
    parts = [p.strip() for p in re.split(r"(?<=[.!?;:])\s+", text) if p.strip()]
    out = []
    for p in parts:                     # juntar trozos muy cortos para que suene natural
        if out and len(out[-1]) < 25:
            out[-1] += " " + p
        else:
            out.append(p)
    return out or [text]


def speak(text):
    """Habla frase a frase: la primera suena mientras se prepara la siguiente."""
    q = queue.Queue()

    def producer():
        for p in sentences(text):
            q.put((p,) + synth(p))
        q.put(None)

    threading.Thread(target=producer, daemon=True).start()
    first = True
    while True:
        item = q.get()
        if item is None:
            break
        p, path, eng = item
        if PLAYER["stop"]:              # interrumpido: no decir el resto
            if path:
                try:
                    os.unlink(path)
                except Exception:
                    pass
            continue
        if first:
            log("voz usada: %s" % (eng or "windows"))
            first = False
        if not path:
            log("sin voz local para: %s" % p[:60])   # nunca la voz de Microsoft
            continue
        try:
            play_file(path)
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass


def speak_local(text):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.close()
    try:
        if piper_to_wav(text, tmp.name):
            play_file(tmp.name)
            return
    except Exception as e:
        log("error Piper: %s" % e)
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
    speak_sapi(text)


def make_acks():
    d = os.path.join(BASE, "acks")
    os.makedirs(d, exist_ok=True)
    for f in glob.glob(os.path.join(d, "*.wav")) + glob.glob(os.path.join(d, "*.mp3")):
        os.unlink(f)
    n = {"fish": 0, "edge": 0, "piper": 0}
    for i, t in enumerate(ACKS + FILLS, 1):
        try:
            f = os.path.join(d, ("ack%d.wav" % i) if i <= len(ACKS) else ("fill%d.wav" % i))
            if "fish" in TTS_CHAIN and fish_to_wav(t, f[:-4] + ".mp3"):
                n["fish"] += 1
            elif "edge" in TTS_CHAIN and edge_to_file(t, f[:-4] + ".mp3"):
                n["edge"] += 1
            elif "piper" in TTS_CHAIN and piper_to_wav(t, f):
                n["piper"] += 1
        except Exception as e:
            log("ack %d: %s" % (i, e))
    with open(os.path.join(d, "motor.txt"), "w") as f:
        best = max(n, key=n.get) if any(n.values()) else "windows"
        f.write(best + (":" + edge_voice() if best == "edge" else ""))
    print("ACKS FISH=%d EDGE=%d PIPER=%d" % (n["fish"], n["edge"], n["piper"]))


def refresh_acks():
    """Rehace las frases instantaneas si no estan con la voz elegida."""
    try:
        cur = open(os.path.join(BASE, "acks", "motor.txt")).read().strip()
    except Exception:
        cur = "windows"
    want = TTS_CHAIN[0] + (":" + edge_voice() if TTS_CHAIN[0] == "edge" else "")
    if cur != want:
        log("rehaciendo frases instantaneas con la voz %s" % TTS_CHAIN[0])
        make_acks()


def voz_test():
    """Para el informe del instalador: que voz funciona y por que no las otras."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp.close()
    res = {}
    if not os.path.exists(FISH_KEY_FILE):
        res["fish"] = "sin clave"
    else:
        res["fish"] = "OK" if fish_to_wav("Prueba.", tmp.name) else "falla: " + _why.get("fish", "?")
    res["edge"] = "OK" if edge_to_file("Prueba.", tmp.name) else "falla: " + _why.get("edge", "?")
    try:
        import importlib.metadata as md
        res["edge"] += " (v%s)" % md.version("edge-tts")
    except Exception:
        res["edge"] += " (no instalado)"
    os.unlink(tmp.name)
    for k, v in res.items():
        print("VOZTEST %s=%s" % (k, v.replace("\n", " ")))


def play_fill():
    files = glob.glob(os.path.join(BASE, "acks", "fill*.*"))
    if files:
        play_file(random.choice(files))


def play_ack():
    files = glob.glob(os.path.join(BASE, "acks", "ack*.wav")) + glob.glob(os.path.join(BASE, "acks", "ack*.mp3"))
    if files:
        play_file(random.choice(files))
    else:
        speak(random.choice(ACKS))


# ---------------------------------------------------------------- respuestas
def find_audio(obj):
    """Busca audio en cualquier campo del mensaje: data URL, base64 o URL http."""
    out = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str):
            if v.startswith("data:audio"):
                try:
                    out.append(base64.b64decode(v.split(",", 1)[1]))
                except Exception:
                    pass
            elif len(v) > 2000 and " " not in v[:200]:
                try:
                    b = base64.b64decode(v, validate=False)
                    if b[:4] in (b"RIFF", b"OggS") or b[:3] == b"ID3" or b[:1] == b"\xff":
                        out.append(b)
                except Exception:
                    pass
            elif v.startswith("http") and v.split("?")[0].lower().endswith((".wav", ".mp3", ".ogg")):
                try:
                    out.append(urllib.request.urlopen(v, timeout=20).read())
                except Exception as e:
                    log("no pude bajar audio %s: %s" % (v[:80], e))
    walk(obj)
    return out


def reply_text(obj):
    for k in ("reply", "response", "respuesta", "answer", "text", "message"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip() and obj.get("type") not in ("transcript", "voice_result", "stt"):
            return v.strip()
    return None


class Voice:
    def __init__(self):
        self.playing = threading.Event()
        self.last_audio = 0.0
        self.loop = None
        self.awaiting = False           # esperando respuesta del cerebro
        self.sent_t = 0.0
        self.conv = False               # conversacion abierta tras "Hey JARVIS"
        self.end = False                # dijo "gracias" / "esta bien asi"
        self.need_name = False          # el ultimo audio era un "Jarvis" dudoso
        self.mute = False               # callar la respuesta a algo que no iba con el
        self.lock = asyncio.Lock()      # nunca dos voces a la vez

    async def play(self, fn, *a):
        async with self.lock:
            await self._play(fn, *a)

    async def _play(self, fn, *a):
        PLAYER["stop"] = False
        self.playing.set()
        try:
            await asyncio.wait_for(self.loop.run_in_executor(None, fn, *a), 60)
        except asyncio.TimeoutError:
            PLAYER["stop"] = True
            log("la voz se quedo colgada mas de 60 s; sigo escuchando")
        except Exception as e:
            log("error reproduciendo: %s" % e)
        finally:
            await asyncio.sleep(0.25)
            self.playing.clear()
            if not PLAYER["stop"]:          # si le interrumpieron ya esta "escuchando"
                await set_state("reposo")

    async def receiver(self, ws):
        async for msg in ws:
            if isinstance(msg, bytes):
                self.last_audio = time.time()
                await self.play(play_bytes, msg)
                continue
            try:
                obj = json.loads(msg)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            t = str(obj.get("type", ""))
            st = str(obj.get("state", obj.get("estado", ""))).lower()
            if t != "mic_level":
                log("<- %s" % json.dumps({k: (v[:60] if isinstance(v, str) else v)
                                          for k, v in obj.items()})[:300])
            if t == "reply" and self.sent_t:
                log("respuesta en %.1f s" % (time.time() - self.sent_t))
            if t in ("transcript", "stt", "voice_result"):
                heard = obj.get("text") or obj.get("transcript") or ""
                if self.need_name:              # "Jarvis" a secas / dudoso
                    self.need_name = False
                    if has_name(heard):
                        self.conv = True        # si era el: seguir la charla
                        if name_only(heard):
                            asyncio.ensure_future(self.play(play_ack))   # "¿Si, senor?"
                    else:
                        self.mute = True        # no decir lo que conteste el cerebro
                        log("no era mi nombre: %s" % heard[:40])
                if is_goodbye(heard):
                    self.end = True
                elif CHANGE_VOICE.search(" ".join(_norm(heard))):
                    next_voice()                          # la respuesta ya sale con la voz nueva
                    self.loop.run_in_executor(None, make_acks)
                elif FILL_ON and self.awaiting and is_action(heard):
                    asyncio.ensure_future(self.play(play_fill))   # "Enseguida, senor" mientras lo hace
                continue
            if obj.get("end") is True or obj.get("end_conversation") is True:
                self.end = True
            if self.mute and (t == "reply" or find_audio(obj)):
                self.mute, self.awaiting = False, False
                continue
            audios = find_audio(obj)
            if audios:
                self.last_audio = time.time()
                for a in audios:
                    await self.play(play_bytes, a)
                self.awaiting = False
                continue
            if st in ("online", "idle", "reposo", "ready") and not self.playing.is_set():
                await set_state("reposo")
            txt = reply_text(obj)
            if txt:
                asyncio.ensure_future(self.text_fallback(txt, time.time()))
            elif t == "reply":                  # respuesta vacia (ruido): no decir nada
                self.awaiting = False

    async def text_fallback(self, txt, t0):
        await asyncio.sleep(0.3)       # si no llega audio enseguida, lo dice el PC
        if self.last_audio < t0:
            await self.play(speak, txt)
        self.awaiting = False


def _norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z ]+", " ", t).split()


def zcr(a):
    """Cruces por cero: la voz tiene pocos, los golpes del teclado muchos."""
    if a.size < 2:
        return 1.0
    return float(np.mean(np.abs(np.diff(np.sign(a.astype(np.int32)))) > 0))


def normalize(pcm):
    """Sube la voz baja hasta un nivel claro para que el cerebro le entienda mejor."""
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if not a.size:
        return pcm
    a -= a.mean()                      # quitar el desnivel del micro
    peak = float(np.percentile(np.abs(a), 99.9)) or 1.0
    g = min(8.0, 0.7 * 32767.0 / peak)  # sin pasarse: como mucho x8
    return np.clip(a * g, -32767, 32767).astype(np.int16).tobytes()


def is_action(text):
    w = _norm(text)
    while w and w[0] in ("hey", "oye", "ok", "jarvis", "hejarvis", "harvis", "yarvis", "por", "favor"):
        w = w[1:]
    return bool(w) and bool(ACTION.match(" ".join(w)))


def is_goodbye(text):
    j = " ".join(_norm(text))
    if not any(e in j for e in END_WORDS):
        return False
    for e in END_WORDS:
        j = j.replace(e, " ")
    rest = [x for x in j.split() if x not in FILLER]
    return len(rest) <= 1               # "gracias, ahora abre Spotify" no cierra


def has_name(text):
    """Jarvis dicho o entendido regular: jarvis, yarvis, jarvi, harvis, ok jarvis..."""
    for w in _norm(text)[:5]:
        if 4 <= len(w) <= 8 and _lev(w, "jarvis") <= 2 and w not in ("travis", "jardin", "barbie", "parvis"):
            return True
    return False


def name_only(text):
    rest = [w for w in _norm(text) if w not in FILLER and not (4 <= len(w) <= 8 and _lev(w, "jarvis") <= 2)]
    return not rest


def _lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def game_thread():
    """Mira cada 1,5 s si hay un juego en primer plano (carpeta de juegos o pantalla completa)."""
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
    u32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    u32.MonitorFromWindow.restype = ctypes.c_void_p
    u32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]

    class MINFO(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("m", RECT), ("w", RECT), ("f", wintypes.DWORD)]

    while True:
        on, exe = False, ""
        try:
            h = u32.GetForegroundWindow()
            if h:
                pid = wintypes.DWORD()
                u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                hp = k32.OpenProcess(0x1000, False, pid.value)
                if hp:
                    buf, n = ctypes.create_unicode_buffer(520), wintypes.DWORD(520)
                    if k32.QueryFullProcessImageNameW(hp, 0, buf, ctypes.byref(n)):
                        exe = buf.value.lower()
                    k32.CloseHandle(hp)
                cls = ctypes.create_unicode_buffer(64)
                u32.GetClassNameW(h, cls, 64)
                name = os.path.basename(exe)
                if exe and name not in NOT_GAMES and cls.value not in ("Progman", "WorkerW", "Shell_TrayWnd"):
                    if any(d in exe for d in GAME_DIRS):
                        on = True
                    else:
                        r, mi = RECT(), MINFO()
                        mi.cb = ctypes.sizeof(MINFO)
                        u32.GetWindowRect(h, ctypes.byref(r))
                        mon = u32.MonitorFromWindow(h, 2)
                        if u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                            m = mi.m
                            on = r.l <= m.l and r.t <= m.t and r.r >= m.r and r.b >= m.b
        except Exception as e:
            log("modo juego: %s" % e)
        if on != GAME["on"]:
            GAME["on"], GAME["exe"] = on, exe
            log("modo juego %s%s" % ("ACTIVADO (%s): solo Ctrl+Alt+J" % os.path.basename(exe) if on else "desactivado",
                                     "" if on else ": vuelve Hey JARVIS"))
        time.sleep(1.5)


def hotkey_thread():
    """Ctrl+Alt+J en cualquier momento (tambien jugando) = "Hey JARVIS"."""
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    if not u32.RegisterHotKey(None, 1, 0x0002 | 0x0001 | 0x4000, ord("J")):
        log("no pude reservar Ctrl+Alt+J (otro programa lo usa)")
        return
    log("atajo Ctrl+Alt+J listo")
    msg = wintypes.MSG()
    while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == 0x0312:
            HOTKEY["hit"] = True


def beep():
    """Pitido corto al pulsar el atajo (jugando no se ve el fondo)."""
    f = os.path.join(BASE, "acks", "beep.wav")
    try:
        if not os.path.exists(f):
            t = np.arange(int(RATE * 0.09)) / RATE
            w8 = (np.sin(2 * np.pi * 880 * t) * np.hanning(t.size) * 9000).astype(np.int16)
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with wave.open(f, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(w8.tobytes())
        import winsound
        winsound.PlaySound(f, winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception as e:
        log("pitido: %s" % e)


# ---------------------------------------------------------------- microfono
def open_mic():
    import pyaudio
    p = pyaudio.PyAudio()
    idx = None
    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        if d.get("maxInputChannels", 0) > 0 and "fifine" in d.get("name", "").lower():
            idx = i
            break
    kw = dict(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK)
    try:
        return p.open(input_device_index=idx, **kw)
    except Exception:
        return p.open(**kw)


def load_wake():
    try:
        import openwakeword.utils
        from openwakeword.model import Model
        try:
            openwakeword.utils.download_models(["hey_jarvis"])
        except Exception:
            pass
        m = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        log("wake word activo: hey jarvis")
        return m
    except Exception as e:
        log("sin openWakeWord (%s): modo voz directa" % e)
        return None


def capture_thread(stream, loop, q):
    while True:
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
        except Exception as e:
            log("mic: %s" % e)
            time.sleep(1)
            continue
        loop.call_soon_threadsafe(q.put_nowait, data)


async def send_clip(ws, voice, frames, need_name):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(normalize(b"".join(frames)))
    b64 = base64.b64encode(buf.getvalue()).decode()
    voice.awaiting, voice.sent_t, voice.need_name = True, time.time(), need_name
    msg = {"type": "audio", "data": "data:audio/wav;base64," + b64}
    if need_name:
        msg["need_name"] = True         # el cerebro solo contesta si oye "Jarvis"
    await ws.send(json.dumps(msg))
    log("-> audio enviado (%.1f s%s)" % (len(frames) * CHUNK / RATE, ", hay que confirmar el nombre" if need_name else ""))


async def listener(ws, q, wake, voice):
    pre = collections.deque(maxlen=PREROLL)
    mode, frames, silence, spoke, n, lvl_t = "idle", [], 0, False, 0, 0.0
    floor, voiced, talk_lvl, follow = VAD / 2.0, 0, 0.0, False
    echo, play_n, over, barged = 0.0, 0, 0, False
    beat_t, beat_lvl, beat_wake = time.time(), 0.0, 0.0
    log("escuchando (microfono y palabra de activacion listos)")
    min_n = 0                           # "Hey JARVIS, abre X" de corrido: grabar al menos esto
    soft, talk = False, 0               # soft = quiza dijo "Jarvis" (falta confirmarlo)
    while True:
        data = await q.get()
        a = np.frombuffer(data, dtype=np.int16)
        rms = float(np.sqrt(np.mean(a.astype(np.float32) ** 2))) if a.size else 0.0
        if not voice.playing.is_set():
            play_n, over, barged = 0, 0, False
        elif not barged:                    # JARVIS hablando: solo mirar si el senor le habla encima
            play_n += 1
            pre.append(data)
            why = None
            if HOTKEY["hit"]:
                HOTKEY["hit"], why = False, "atajo"
            elif wake and not GAME["on"] and max(wake.predict(a).values() or [0]) >= WAKE_TH:
                why = "palabra"
            if play_n <= 5:                 # primeras 0.4 s: medir cuanto se oye a si mismo
                echo = rms if play_n == 1 else max(echo, rms)
            else:
                if BARGE and rms > max(VAD * 3, echo * 3.0) and zcr(a) < 0.3:
                    over += 1
                else:
                    over = 0
                    echo = 0.95 * echo + 0.05 * rms   # su propio eco (sin contar la voz del senor)
                if over >= 6:
                    why = "voz encima"
            if not why:
                continue
            barged = True
            PLAYER["stop"] = True
            log("interrumpido (%s): le escucho" % why)
            if wake:
                wake.reset()
            voice.awaiting, voice.conv, voice.end, follow, soft = False, True, False, False, False
            mode, frames, silence, spoke, n, voiced, talk_lvl = "rec", list(pre)[-(8 if why == "voz encima" else KEEP_EDGE):], 0, why == "voz encima", 0, 0, 0.0
            pre.clear()
            await set_state("escuchando")
            await ws.send(json.dumps({"type": "state", "state": "listening"}))
            continue
        if mode != "idle":
            HOTKEY["hit"] = False               # ya le esta escuchando o contestando
        if mode == "idle":
            floor = 0.97 * floor + 0.03 * min(rms, VAD * 2)   # ruido de fondo de la habitacion
        thr = max(VAD, floor * 2.5)
        if mode == "idle":
            pre.append(data)
            hit, soft = False, False
            if HOTKEY["hit"]:                   # Ctrl+Alt+J: escuchar ya, sin palabra
                HOTKEY["hit"] = False
                beep()
                log("atajo Ctrl+Alt+J: le escucho")
                voice.conv, voice.end, follow, talk_lvl, min_n = True, False, False, 0.0, 0
                mode, frames, silence, spoke, n, voiced = "rec", [], 0, False, 0, 0
                pre.clear()
                await set_state("escuchando")
                await ws.send(json.dumps({"type": "state", "state": "listening"}))
                continue
            if wake and not GAME["on"]:
                score = max(wake.predict(a).values() or [0])
                beat_wake = max(beat_wake, score)
                hit = score >= WAKE_TH
                if not hit and score >= WAKE_SOFT:
                    hit = soft = True           # quiza "Jarvis" a secas: lo confirma la transcripcion
                    log("quiza me llamo (%.2f)" % score)
            elif not wake and rms > VAD:
                hit = True
            beat_lvl = max(beat_lvl, rms)
            if time.time() - beat_t > 300:      # cada 5 min: prueba de que sigue oyendo
                log("sigo oyendo: nivel max %.0f, palabra max %.2f" % (beat_lvl, beat_wake))
                beat_t, beat_lvl, beat_wake = time.time(), 0.0, 0.0
            if hit:
                voice.conv, voice.end, follow = not soft, False, False
                talk_lvl = 0.0
                frames, silence, spoke, n, voiced = list(pre), 0, not wake, 0, 0   # desde "Hey JARVIS" (el cerebro quita el nombre)
                pre.clear()
                if wake:
                    if not soft:
                        wake.reset()
                    mode, talk = "post", 0      # esperar a que termine de decir "Hey JARVIS"
                else:
                    mode = "rec"
                    await set_state("escuchando")
                    await ws.send(json.dumps({"type": "state", "state": "listening"}))
            continue
        if mode == "post":
            frames.append(data)
            n += 1
            if soft and max(wake.predict(a).values() or [0]) >= WAKE_TH:
                soft, voice.conv = False, True  # ahora si: era "Hey JARVIS" claro
                wake.reset()
            if rms > thr:
                silence = 0
                if n > WAKE_TAIL:
                    talk += 1
            else:
                silence += 1
            if talk >= ONE_BREATH:              # lo dijo todo de corrido: sin ack, seguir grabando
                mode, spoke, n = "rec", True, 0
                voiced, min_n = talk + 2, 20    # ya hablo: no tomarlo por ruido; ~1.6 s minimo mas
                if not soft:
                    await set_state("escuchando")
                    await ws.send(json.dumps({"type": "state", "state": "listening"}))
            elif soft and (silence >= PAUSE_ACK or n >= POST_MAX):
                loud_pre = sum(1 for f in frames if float(np.sqrt(np.mean(np.frombuffer(f, np.int16).astype(np.float32) ** 2))) > thr)
                if loud_pre < 3:                # ni siquiera hablo: era ruido
                    mode, frames, soft = "idle", [], False
                    continue
                await send_clip(ws, voice, frames, True)   # dijo solo "Jarvis"? que lo confirme el cerebro
                mode, frames = "wait", []
            elif silence >= PAUSE_ACK or n >= POST_MAX:
                await voice.play(play_ack)      # "¿Si, senor?" cuando ya termino de llamarle
                while not q.empty():            # descartar lo grabado durante el ack
                    q.get_nowait()
                mode, spoke, silence, n, frames = "rec", False, 0, 0, []
                await set_state("escuchando")
                await ws.send(json.dumps({"type": "state", "state": "listening"}))
            continue
        if mode == "wait":                  # esperando la respuesta del cerebro
            if voice.awaiting and time.time() - voice.sent_t > REPLY_WAIT:
                voice.awaiting = False
                log("el cerebro no contesto a tiempo")
            if not voice.awaiting and not voice.playing.is_set():
                if voice.conv and not voice.end:   # seguir la conversacion sin "Hey JARVIS"
                    mode, frames, silence, spoke, n, voiced, talk_lvl = "rec", [], 0, False, 0, 0, 0.0
                    follow = True
                    if wake:
                        wake.reset()
                    await set_state("escuchando")
                    await ws.send(json.dumps({"type": "state", "state": "listening"}))
                else:
                    mode, voice.conv = "idle", False
                    log("conversacion cerrada")
                    await set_state("reposo")
            continue
        # grabando
        frames.append(data)
        n += 1
        if time.time() - lvl_t > 0.07:
            lvl_t = time.time()
            await broadcast({"level": round(min(1.0, rms / 150.0), 3)})
        loud = rms > max(thr * (1.6 if follow else 1.0), 0.25 * talk_lvl)
        if loud and (not follow or zcr(a) < 0.3):   # en la charla seguida, el teclado no cuenta como voz
            spoke, silence = True, 0
            voiced += 1
            talk_lvl = rms if voiced == 1 else 0.9 * talk_lvl + 0.1 * rms
        else:
            silence += 1
            if not spoke:
                frames = frames[-KEEP_EDGE:]    # no mandar el silencio de antes de hablar
        end = END_SILENCE + 2 if min_n else (END_SHORT if 0 < voiced <= 8 and n < 25 else END_SILENCE)
        if spoke and silence >= end and voiced < (4 if follow else 2):
            spoke, voiced, talk_lvl = False, 0, 0.0      # fue un ruido suelto: seguir esperando
            frames = frames[-KEEP_EDGE:]
        wait_max = CONV_WAIT if voice.conv else WAIT_SPEECH
        done = (spoke and silence >= end and n >= min_n) or n > MAX_REC or (not spoke and n > wait_max)
        if done:
            mode, min_n = "idle", 0
            if spoke and silence > KEEP_EDGE:
                frames = frames[:len(frames) - silence + KEEP_EDGE]   # recortar el silencio final
            if spoke:
                await send_clip(ws, voice, frames, soft)
                mode, soft = "wait", False
            elif voice.conv:
                voice.conv = False
                log("conversacion cerrada por silencio")
            frames = []
            await set_state("reposo")


async def main():
    try:
        await websockets.serve(relay_handler, RELAY_HOST, RELAY_PORT)
    except OSError:
        log("ya hay otra instancia corriendo; salgo")
        return
    loop = asyncio.get_running_loop()
    voice = Voice()
    voice.loop = loop
    MAIN_LOOP["l"] = loop
    q = asyncio.Queue()
    stream = open_mic()
    threading.Thread(target=capture_thread, args=(stream, loop, q), daemon=True).start()
    threading.Thread(target=game_thread, daemon=True).start()
    threading.Thread(target=hotkey_thread, daemon=True).start()
    wake = await loop.run_in_executor(None, load_wake)
    if "piper" in TTS_CHAIN:
        loop.run_in_executor(None, piper_voice)      # tener la voz local cargada de antemano
    loop.run_in_executor(None, refresh_acks)
    log("arrancado %s; cerebro en %s" % (VERSION, WS_URL))
    while True:
        try:
            async with websockets.connect(WS_URL, max_size=None, ping_interval=30, ping_timeout=180, close_timeout=5) as ws:
                log("conectado al cerebro")
                voice.awaiting, voice.conv, voice.end = False, False, False   # empezar limpio tras reconectar
                while not q.empty():
                    q.get_nowait()
                rt = asyncio.ensure_future(voice.receiver(ws))
                lt = asyncio.ensure_future(listener(ws, q, wake, voice))
                done, pend = await asyncio.wait([rt, lt], return_when=asyncio.FIRST_COMPLETED)
                for t in pend:
                    t.cancel()
                for t in done:
                    if t.exception():
                        raise t.exception()
        except Exception as e:
            log("conexion perdida (%s); reintento en 3 s" % e)
        await set_state("reposo")
        await asyncio.sleep(1)


async def tool(arg):
    async with websockets.connect("ws://%s:%d" % (RELAY_HOST, RELAY_PORT), open_timeout=5) as ws:
        await ws.recv()
        if arg == "--status":
            await ws.send(json.dumps({"cmd": "clients"}))
            print(await asyncio.wait_for(ws.recv(), 5))
        else:
            await ws.send(json.dumps({"state": arg}))
            await asyncio.sleep(0.3)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--send":
        asyncio.run(tool(sys.argv[2]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--status":
        asyncio.run(tool("--status"))
    elif len(sys.argv) > 1 and sys.argv[1] == "--make-acks":
        make_acks()
    elif len(sys.argv) > 1 and sys.argv[1] == "--voz-test":
        voz_test()
    elif len(sys.argv) > 1 and sys.argv[1] == "--ack":
        play_ack()
    else:
        asyncio.run(main())
