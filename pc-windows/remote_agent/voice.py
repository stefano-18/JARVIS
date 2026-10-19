"""Voz del remote_agent (jarvis2): recepcion TTS + envio de texto de voz.

Reutiliza la logica probada de jarvis-v2-fijo/agent/playback.py
(_play_audio_bytes: sniff de magic bytes RIFF/ID3, extension por mime,
hilo daemon + playsound bloqueante + unlink, anti-solape por generacion).
Se copia adaptada aqui para mantener remote_agent autocontenido
(mismo criterio que protocol.py: sin dependencias entre proyectos).

Protocolo de voz jarvis2 (lado PC; el hub vive en la laptop):
  jr_tts (S->C, con sobre): {"audio": b64, "audio_mime": "audio/mp3|audio/wav",
                             "text": str-opcional, "trace_id": str-opcional}
  jr_tts_chunk (S->C, con sobre): {"stream_id": str, "idx": int,
                             "data": b64, "mime": str-opcional, "final": bool}
  jr_voice_result (C->S, con sobre): {"ok": bool, "played": bool, "bytes": int,
                             "mime": str, "trace_id": str, "error": str}
  jr_voice_text (C->S, con sobre): {"text": str, "source": "manual|stt"}

Equivalencia con el protocolo viejo (jarvis-v2-fijo):
  voice_result.audio/audio_mime -> jr_tts.audio/audio_mime
  tts_chunk.data/mime          -> jr_tts_chunk.data/mime (+stream_id/idx/final)
  (nuevo) confirmacion         -> jr_voice_result
  (nuevo) texto ya transcrito  -> jr_voice_text (la laptop NO empaqueta STT:
                                 espera texto, no audio)

Se aceptan alias liberales (audio/data/chunk, audio_mime/mime) para
tolerar variantes del hub.

Entrada de voz: por defecto SOLO texto manual via voice_outbox.txt
(una linea = un jr_voice_text). La captura de microfono + STT local
(faster-whisper, mismos parametros que stt_node/voice_in) existe en
este modulo pero esta DESACTIVADA por defecto (VOICE_IN=1 para
activarla): el microfono lo posee hoy mic_bridge.py del proyecto
viejo (pipeline antiguo, con su propio lock) y no se abre dos veces
el mismo dispositivo. Fase 2.
"""
import base64
import hashlib
import queue as _queue
import tempfile
import threading as _th
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
OUTBOX_PATH = PROJECT_ROOT / "voice_outbox.txt"

# --- reproduccion (adaptado de playback.py) ---
_STATE = "IDLE"
_TTS_LOCK = _th.Lock()
_TTS_GEN = 0
_MIN_BYTES = 100
_RECENT_PLAY_SECS = 30.0
_recent_played: dict = {}


def _stop_current_tts() -> None:
    """Cancela TTS en curso: sube generacion + cierra MCI."""
    global _TTS_GEN
    with _TTS_LOCK:
        _TTS_GEN += 1
    try:
        from ctypes import windll
        windll.winmm.mciSendStringW("close all", None, 0, None)
    except Exception:
        pass


def _sniff_suffix_mime(data: bytes, mime: str) -> tuple[str, str]:
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return ".wav", "audio/wav"
    if data[:3] == b"ID3" or data[:2] == b"\xff\xfb":
        return ".mp3", "audio/mp3"
    if "wav" in (mime or "").lower():
        return ".wav", "audio/wav"
    return ".mp3", "audio/mp3"


def play_audio_bytes(data: bytes, tag: str = "jrtts",
                     mime: str = "audio/mp3") -> dict:
    """Reproduce bytes de audio (bloqueante). Retorna {played, bytes, mime}."""
    raw = bytes(data or b"")
    if len(raw) < _MIN_BYTES:
        return {"played": False, "bytes": len(raw), "mime": mime or "",
                "error": f"audio demasiado corto ({len(raw)} bytes)"}
    suffix, mime_eff = _sniff_suffix_mime(raw, mime)
    try:
        tmp = Path(tempfile.gettempdir()) / f"jr_voice_{tag}_{int(time.time() * 1000)}{suffix}"
        tmp.write_bytes(raw)
    except Exception as e:
        return {"played": False, "bytes": len(raw), "mime": mime_eff,
                "error": f"no se pudo guardar temporal: {e}"}
    _stop_current_tts()  # el audio nuevo cancela el anterior, no solapa
    with _TTS_LOCK:
        global _TTS_GEN
        _TTS_GEN += 1
    try:
        import playsound
        playsound.playsound(str(tmp), block=True)
        return {"played": True, "bytes": len(raw), "mime": mime_eff, "error": ""}
    except Exception as e:
        return {"played": False, "bytes": len(raw), "mime": mime_eff,
                "error": f"reproduccion fallo: {e}"}
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass


def _played_key(key: str) -> bool:
    """Anti-doble voz (como _cine_reciente): True si ya sono hace <30s."""
    now = time.time()
    for k in [k for k, t in _recent_played.items() if now - t > _RECENT_PLAY_SECS]:
        _recent_played.pop(k, None)
    if key and key in _recent_played:
        return True
    if key:
        _recent_played[key] = now
    return False


def play_key(audio: bytes) -> str:
    """Clave anti-duplicado por contenido (da igual jr_tts o chunks)."""
    return "sha:" + hashlib.sha256(bytes(audio or b"")).hexdigest()[:16]


# --- extraccion tolerante de audio ---
def _b64_clean(s: str) -> bytes:
    s = (s or "").strip()
    if "," in s and "base64" in s[:80]:  # dataURL -> b64 puro
        s = s.split(",", 1)[1]
    s = "".join(s.split())  # sin whitespace intercalado
    s += "=" * (-len(s) % 4)  # tolera padding ausente (chunks)
    return base64.b64decode(s)


def extract_audio(payload: dict) -> tuple:
    """(audio_bytes|None, mime, text|None, trace_id). Alias liberales."""
    p = payload or {}
    raw_b64 = (p.get("audio") or p.get("data") or p.get("chunk")
               or p.get("audio_b64") or p.get("chunk_b64") or "")
    mime = str(p.get("audio_mime") or p.get("mime") or p.get("audioMime")
               or "audio/mp3")
    text = p.get("text") or p.get("reply")
    trace = str(p.get("trace_id") or p.get("traceId") or "-")
    if not raw_b64:
        return None, mime, text, trace
    try:
        return _b64_clean(str(raw_b64)), mime, text, trace
    except Exception:
        return None, mime, text, trace


# --- reensamblado de chunks ---
class ChunkAssembler:
    """Reensambla jr_tts_chunk por stream_id. Retorna bytes al llegar 'final'."""

    def __init__(self, ttl_s: float = 120.0):
        self._streams: dict = {}
        self._ttl = ttl_s

    def add(self, payload: dict) -> tuple:
        """(audio_bytes|None, mime, stream_id, is_final)."""
        p = payload or {}
        sid = str(p.get("stream_id") or p.get("streamId") or p.get("trace_id") or "-")
        try:
            idx = int(p.get("idx", p.get("index", 0)))
        except Exception:
            idx = 0
        mime = str(p.get("mime") or p.get("audio_mime") or "audio/mp3")
        final = bool(p.get("final", False))
        now = time.time()
        for k in [k for k, v in self._streams.items()
                  if now - v["seen"] > self._ttl]:
            self._streams.pop(k, None)
        st = self._streams.setdefault(sid, {"chunks": {}, "mime": mime, "seen": now})
        st["seen"] = now
        st["mime"] = mime or st["mime"]
        # Se guarda el TROZO DE TEXTO b64 sin decodificar: los cortes
        # arbitrarios casi nunca son multiplos de 4 (padding). Se decodifica
        # el concatenado una sola vez al llegar 'final'.
        part = str(p.get("data") or p.get("chunk") or "")
        if not part:
            return None, mime, sid, False
        st["chunks"][idx] = part
        if not final:
            return None, mime, sid, False
        parts = st["chunks"]
        if not parts or sorted(parts) != list(range(max(parts) + 1)):
            return None, mime, sid, True  # final con huecos: se descarta
        self._streams.pop(sid, None)
        try:
            return _b64_clean("".join(parts[i] for i in sorted(parts))), \
                mime, sid, True
        except Exception:
            return None, mime, sid, True


# --- constructores de payload (el sobre HMAC lo pone protocol.make_envelope) ---
def make_voice_text_payload(text: str, source: str = "manual") -> dict:
    return {"text": (text or "").strip()[:2000],
            "source": source if source in ("manual", "stt") else "manual"}


def make_voice_result_payload(ok: bool, played: bool, nbytes: int,
                              mime: str, trace_id: str,
                              error: str = "") -> dict:
    return {"ok": bool(ok), "played": bool(played), "bytes": int(nbytes),
            "mime": mime or "", "trace_id": trace_id or "-",
            "error": (error or "")[:300]}


# --- outbox de texto manual ---
def drain_outbox(path: Path = None) -> list:
    """Lee lineas de voice_outbox.txt y lo trunca. [] si no hay nada."""
    p = Path(path) if path else OUTBOX_PATH
    try:
        if not p.exists():
            return []
        lines = [ln.lstrip("﻿").strip() for ln in p.read_text(encoding="utf-8").splitlines()]
        p.write_text("", encoding="utf-8")
    except Exception:
        return []
    return [ln for ln in lines if ln]


def drain_queue(q) -> list:
    out = []
    if q is None:
        return out
    while True:
        try:
            out.append(q.get_nowait())
        except Exception:
            break
    return out


# --- STT local con microfono (FASE 2: desactivado por defecto) ---
# Mismos parametros que mic_bridge.py (captura) y stt_node.py / voice_in.py
# (transcripcion): 16 kHz mono int16, VAD por RMS, faster-whisper en espanol.
MIC_RATE = 16000
MIC_CHANNELS = 1
MIC_CHUNK = 1024
MIC_SILENCE_CHUNKS = 15
MIC_MAX_FRAMES = 75

_stt_model = None
_stt_desc = ""


def transcribe_wav_bytes(wav_bytes: bytes, model_name: str = "medium",
                         language: str = "es") -> str:
    """Transcribe bytes WAV (16kHz mono) con faster-whisper. Solo stdlib+fw."""
    global _stt_model, _stt_desc
    if _stt_model is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError(f"faster-whisper no instalado: {e}")
        # CPU/int8 siempre: el backend CUDA exige cublas64_12.dll (ausente
        # en este PC) y falla en cada encode; el modelo medium ya esta
        # cacheado (1.5GB, sin descarga).
        _stt_model = WhisperModel(model_name, device="cpu",
                                  compute_type="int8")
        _stt_desc = f"{model_name}/cpu/int8"
    import tempfile as _tf
    with _tf.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        tmp = f.name
    try:
        segments, _info = _stt_model.transcribe(tmp, language=language,
                                                vad_filter=True)
        return " ".join(s.text.strip() for s in segments if s.text.strip())
    finally:
        try:
            Path(tmp).unlink()
        except Exception:
            pass


def _rms(data: bytes) -> float:
    import struct
    if len(data) < 2:
        return 0.0
    n = len(data) // 2
    s = struct.unpack(f"<{n}h", data[:n * 2])
    return (sum(x * x for x in s) / len(s)) ** 0.5 if s else 0.0


def _find_mic(pyaudio_mod, prefer: str = "fifine"):
    """Indice del microfono preferido (FIFINE) o default. None si no hay."""
    try:
        pa = pyaudio_mod.PyAudio()
        try:
            n = pa.get_device_count()
            fallback = None
            for i in range(n):
                info = pa.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) < 1:
                    continue
                name = str(info.get("name", ""))
                if prefer.lower() in name.lower():
                    return pa, i
                if fallback is None:
                    fallback = i
            return pa, fallback
        except Exception:
            try:
                pa.terminate()
            except Exception:
                pass
            return None, None
    except Exception:
        return None, None


def live_should_arm(wake_on: bool, hit: bool) -> bool:
    """Wake-gated en vivo: sin wake requerido siempre armado; con wake
    solo se arma al detectar 'Hey Jarvis'."""
    if not wake_on:
        return True
    return bool(hit)


def live_next_armed(wake_on: bool) -> bool:
    """Tras enviar una frase en vivo, con wake se desarma (exige nuevo
    'Hey Jarvis'); sin wake sigue armado."""
    return not bool(wake_on)


def start_mic_stt(cfg: dict, out_q, log_fn=None):
    """Hilo de captura VAD + STT. Solo si VOICE_IN=1. Push texto a out_q.

    Con VOICE_WAKE=1: wake-gated en vivo (solo envia tras 'Hey Jarvis';
    stop_for_wake si hay reproduccion). Con VOICE_WAKE=0: VAD libre
    legacy (envia todo lo oido)."""
    import threading

    def _log(m):
        try:
            if log_fn:
                log_fn(m)
        except Exception:
            pass

    def _run():
        try:
            import pyaudio
        except ImportError as e:
            _log(f"VOICE_IN: sin pyaudio ({e}), captura desactivada")
            return
        pa, idx = _find_mic(pyaudio)
        if pa is None or idx is None:
            _log("VOICE_IN: sin microfono disponible, captura desactivada")
            return
        try:
            vad = float((cfg or {}).get("VOICE_VAD", 25))
        except Exception:
            vad = 25.0
        model = str((cfg or {}).get("VOICE_STT_MODEL", "medium"))
        wake_on = str((cfg or {}).get("VOICE_WAKE", "0")) == "1"
        try:
            thr = float((cfg or {}).get("VOICE_WAKE_THRESHOLD", 0.5))
        except Exception:
            thr = 0.5
        armed = live_should_arm(wake_on, False)
        if wake_on:
            _log(f"VOICE_IN vivo wake-gated: esperando 'Hey Jarvis' "
                 f"(thr={thr}) en dev={idx} VAD>={vad} STT={model}; "
                 f"solo se envia tras wake")
            try:
                _hit0, _s0 = wake_score(b"\x00\x00" * 1280, thr)
                _log(f"VOICE_IN: modelo wake onnx OK "
                     f"(silencio score={_s0})")
            except Exception as e:
                _log(f"VOICE_IN: modelo wake FALLO ({e}); "
                     f"sin wake no hay envios")
        else:
            _log(f"VOICE_IN: capturando en dispositivo {idx} (VAD>={vad}) + STT {model}")
        try:
            stream = pa.open(format=pyaudio.paInt16, channels=MIC_CHANNELS,
                             rate=MIC_RATE, input=True,
                             input_device_index=idx,
                             frames_per_buffer=MIC_CHUNK)
        except Exception as e:
            _log(f"VOICE_IN: no se pudo abrir microfono: {e}")
            try:
                pa.terminate()
            except Exception:
                pass
            return
        import io
        import wave
        buf, silent = [], 0
        try:
            while True:
                try:
                    data = stream.read(MIC_CHUNK, exception_on_overflow=False)
                except Exception:
                    continue
                if wake_on:
                    try:
                        hit, _s = wake_score(data, thr)
                    except Exception:
                        hit = False
                    if is_playing() and hit:
                        stop_for_wake()
                        _log("VOICE_IN: wake durante reproduccion, "
                             "audio detenido, esperando frase completa")
                        buf, silent, armed = [], 0, True
                        continue
                    if not armed:
                        if hit:
                            armed = True
                            buf, silent = [], 0
                            _log("VOICE_IN: 'Hey Jarvis' detectado, "
                                 "escuchando frase completa")
                        continue
                level = _rms(data)
                if level >= vad:
                    buf.append(data)
                    silent = 0
                elif buf:
                    buf.append(data)
                    silent += 1
                    if silent >= MIC_SILENCE_CHUNKS or len(buf) >= MIC_MAX_FRAMES:
                        pcm = b"".join(buf)
                        buf, silent = [], 0
                        bio = io.BytesIO()
                        with wave.open(bio, "wb") as wf:
                            wf.setnchannels(MIC_CHANNELS)
                            wf.setsampwidth(2)
                            wf.setframerate(MIC_RATE)
                            wf.writeframes(pcm)
                        try:
                            text = transcribe_wav_bytes(bio.getvalue(),
                                                        model_name=model)
                        except Exception as e:
                            _log(f"VOICE_IN: STT fallo: {e}")
                            armed = live_next_armed(wake_on)
                            continue
                        if text.strip():
                            try:
                                out_q.put(text.strip()[:2000])
                            except Exception:
                                pass
                        armed = live_next_armed(wake_on)
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            try:
                pa.terminate()
            except Exception:
                pass

    t = threading.Thread(target=_run, name="VoiceIn", daemon=True)
    t.start()
    return t


# --- FASE A: sombra + wake word + metricas + TTS con prioridad ---
# Todo APAGADO por defecto (flags VOICE_SHADOW/VOICE_WAKE/TTS_PRIORITY=0).
# Sombra: transcribe y REGISTRA localmente, SIN enviar nada y SIN guardar
# audio (solo texto + latencia + contadores en voice_shadow.jsonl).
import json as _json

_SHADOW_METRICS = {"n": 0, "lat_s": [], "wake_hits": 0,
                   "t0": None, "false_wake": 0}
_TTS_QUEUE: list = []
_TTS_WORKER_STARTED = False
_PLAYING = False


def is_playing() -> bool:
    return bool(_PLAYING)


def set_playing(v: bool) -> None:
    global _PLAYING
    _PLAYING = bool(v)


def describe_downloads() -> list:
    """Informa ANTES del tamano de lo que descargaria (sin descargar).

    Retorna [{name, size_bytes|None, present, url}]. No imprime secretos.
    """
    out = []
    try:
        import openwakeword as _oww
        models = getattr(_oww, "MODELS", {})
        for key in ("hey_jarvis",):
            info = (models or {}).get(key, {})
            p = str(info.get("model_path", ""))
            url = str(info.get("download_url", ""))
            try:
                present = bool(p and Path(p).exists())
                size = Path(p).stat().st_size if present else None
            except Exception:
                present, size = False, None
            if not present:
                size = 1278912  # tamano conocido hey_jarvis_v0.1.tflite (~1.2MB)
            out.append({"name": f"openWakeWord/{key}", "size_bytes": size,
                        "present": present, "url": url})
    except Exception:
        out.append({"name": "openWakeWord/hey_jarvis", "size_bytes": 1278912,
                    "present": False, "url": ""})
    try:
        from pathlib import Path as _P
        hub = _P.home() / ".cache" / "huggingface" / "hub"
        med = list(hub.glob("models--Systran--faster-whisper-medium*"))
        present = bool(med)
        size = None
        if present:
            try:
                size = sum(f.stat().st_size for f in med[0].rglob("*")
                           if f.is_file())
            except Exception:
                size = 1530571775
        else:
            size = 1530571775  # ~1.5GB medium ya cacheado en este PC
        out.append({"name": "faster-whisper/medium", "size_bytes": size,
                    "present": present, "url": "huggingface:Systran/faster-whisper-medium"})
    except Exception:
        pass
    return out


def shadow_log_path(cfg: dict) -> Path:
    name = str((cfg or {}).get("VOICE_SHADOW_LOG", "voice_shadow.jsonl"))
    p = Path(name)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def shadow_append(cfg: dict, text: str, latency_s: float,
                  wake: bool = False, stt_model: str = "") -> dict:
    """Registra transcripcion sombra local (solo texto, jamas audio)."""
    global _SHADOW_METRICS
    import time as _t
    now = _t.time()
    if _SHADOW_METRICS["t0"] is None:
        _SHADOW_METRICS["t0"] = now
    _SHADOW_METRICS["n"] += 1
    try:
        _SHADOW_METRICS["lat_s"].append(float(latency_s))
    except Exception:
        pass
    if wake:
        _SHADOW_METRICS["wake_hits"] += 1
    entry = {"ts": int(now), "text": (text or "")[:2000],
             "latency_s": round(float(latency_s), 3), "wake": bool(wake),
             "stt": stt_model or ""}
    try:
        p = shadow_log_path(cfg)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return entry


def shadow_metrics() -> dict:
    """{n, lat_p50, lat_p95, triggers_per_hour, false_wake} (solo local)."""
    import time as _t
    n = int(_SHADOW_METRICS.get("n", 0))
    lat = sorted(_SHADOW_METRICS.get("lat_s", []))
    def _pct(q: float) -> float:
        if not lat:
            return 0.0
        k = min(len(lat) - 1, max(0, int(q * len(lat))))
        return round(float(lat[k]), 3)
    t0 = _SHADOW_METRICS.get("t0") or _t.time()
    hours = max(1.0 / 3600.0, (_t.time() - t0) / 3600.0)
    return {"n": n, "lat_p50": _pct(0.5), "lat_p95": _pct(0.95),
            "triggers_per_hour": round(_SHADOW_METRICS.get("wake_hits", 0) / hours, 2),
            "wake_hits": int(_SHADOW_METRICS.get("wake_hits", 0)),
            "false_wake": int(_SHADOW_METRICS.get("false_wake", 0))}


def wake_onnx_path() -> str:
    """Ruta del modelo hey_jarvis .onnx local (sin descargas). '' si falta."""
    try:
        import openwakeword as _oww
        base = Path(str(getattr(_oww, "__file__", ""))).resolve().parent \
            / "resources" / "models"
        p = base / "hey_jarvis_v0.1.onnx"
        if p.exists():
            return str(p)
        info = (getattr(_oww, "MODELS", {}) or {}).get("hey_jarvis", {})
        mp = str(info.get("model_path", ""))
        if mp.endswith(".tflite"):
            mp = mp[:-len(".tflite")] + ".onnx"
            if mp and Path(mp).exists():
                return mp
    except Exception:
        pass
    return ""


def wake_score(pcm16: bytes, threshold: float = 0.5) -> tuple:
    """Score openWakeWord hey_jarvis sobre PCM 16kHz mono int16.

    Retorna (hit:bool, score:float). Si el modelo no esta, (False, 0.0).
    Sin cuentas ni claves (modelo pre-entrenado local).
    Usa el .onnx con inference_framework='onnx' (onnxruntime): el
    backend tflite no existe en Windows y jamas puntuaria.
    """
    try:
        from openwakeword import Model as _OWWModel
        import numpy as _np
        m = getattr(wake_score, "_m", None)
        if m is None:
            path = wake_onnx_path()
            try:
                if path:
                    m = _OWWModel(wakeword_models=[path],
                                  inference_framework="onnx")
                else:
                    m = _OWWModel(wake_models=["hey_jarvis"])
            except TypeError:
                # openWakeWord antiguo sin inference_framework
                m = _OWWModel(wake_models=["hey_jarvis"])
            wake_score._m = m  # type: ignore
        import struct as _st
        n = len(pcm16) // 2
        if n <= 0:
            return False, 0.0
        arr = _np.array(_st.unpack(f"<{n}h", pcm16[:n * 2]),
                        dtype=_np.int16)
        pred = m.predict(arr)
        s = 0.0
        try:
            for k, v in (pred or {}).items():
                if "jarvis" in str(k).lower():
                    s = max(s, float(v))
        except Exception:
            pass
        return bool(s >= float(threshold)), round(float(s), 4)
    except Exception:
        return False, 0.0


def stop_for_wake() -> None:
    """A2: al oir wake durante reproduccion, detiene audio y no envia
    nada hasta frase completa (el llamador suprime el envio)."""
    try:
        _stop_current_tts()
    except Exception:
        pass
    set_playing(False)


def tts_priority_of(payload: dict) -> str:
    p = str((payload or {}).get("priority", "")).upper().strip()
    return p if p in ("P0", "P1", "P2") else "P1"


def tts_enqueue(audio: bytes, mime: str, trace: str, priority: str) -> int:
    """Encola TTS (P0 interrumpe, resto FIFO). Retorna tamano de cola."""
    if str(priority).upper() == "P0":
        try:
            _stop_current_tts()
        except Exception:
            pass
        _TTS_QUEUE.insert(0, {"audio": bytes(audio or b""), "mime": mime,
                              "trace": trace, "priority": "P0"})
    else:
        _TTS_QUEUE.append({"audio": bytes(audio or b""), "mime": mime,
                           "trace": trace, "priority": priority or "P1"})
    return len(_TTS_QUEUE)


def tts_dequeue() -> dict | None:
    if not _TTS_QUEUE:
        return None
    return _TTS_QUEUE.pop(0)


def start_shadow_stt(cfg: dict, log_fn=None):
    """Sombra: VAD + wake + STT, SOLO registro local, NUNCA envia al hub,
    NUNCA guarda audio (solo texto+latencia). Microfono compartido con
    mic_bridge: si el microfono no abre (ocupado), se registra y se sale
    sin tumbar nada; el corte del pipeline viejo lo decide el usuario."""
    import threading as _th
    import time as _t

    def _log(m):
        try:
            if log_fn:
                log_fn(m)
        except Exception:
            pass

    for d in describe_downloads():
        _log(f"VOICE_SHADOW descarga: {d['name']} "
             f"{'presente' if d['present'] else 'AUSENTE'} "
             f"size={d['size_bytes']} url={d.get('url', '')}")

    def _run():
        try:
            import pyaudio
        except ImportError as e:
            _log(f"VOICE_SHADOW: sin pyaudio ({e}), sombra desactivada")
            return
        pa, idx = _find_mic(pyaudio)
        if pa is None or idx is None:
            _log("VOICE_SHADOW: sin microfono, sombra desactivada")
            return
        try:
            vad = float((cfg or {}).get("VOICE_VAD", 25))
        except Exception:
            vad = 25.0
        model = str((cfg or {}).get("VOICE_STT_MODEL", "medium"))
        wake_on = str((cfg or {}).get("VOICE_WAKE", "0")) == "1"
        try:
            thr = float((cfg or {}).get("VOICE_WAKE_THRESHOLD", 0.5))
        except Exception:
            thr = 0.5
        _log(f"VOICE_SHADOW: capturando dev={idx} VAD>={vad} STT={model} "
             f"wake={'on' if wake_on else 'off'} (SOLO local, sin envios)")
        try:
            stream = pa.open(format=pyaudio.paInt16, channels=MIC_CHANNELS,
                             rate=MIC_RATE, input=True,
                             input_device_index=idx,
                             frames_per_buffer=MIC_CHUNK)
        except Exception as e:
            _log(f"VOICE_SHADOW: microfono ocupado/no abre ({e}); "
                 f"mic_bridge sigue dueno, sombra sin capturar")
            try:
                pa.terminate()
            except Exception:
                pass
            return
        import io as _io
        import wave as _wv
        buf, silent = [], 0
        try:
            while True:
                try:
                    data = stream.read(MIC_CHUNK, exception_on_overflow=False)
                except Exception:
                    continue
                if wake_on and is_playing():
                    try:
                        hit, _s = wake_score(data, thr)
                    except Exception:
                        hit = False
                    if hit:
                        stop_for_wake()
                        _log("VOICE_SHADOW: wake durante reproduccion, "
                             "audio detenido, esperando frase completa")
                        buf, silent = [], 0
                        continue
                level = _rms(data)
                if level >= vad:
                    buf.append(data)
                    silent = 0
                elif buf:
                    buf.append(data)
                    silent += 1
                    if silent >= MIC_SILENCE_CHUNKS or len(buf) >= MIC_MAX_FRAMES:
                        pcm = b"".join(buf)
                        buf, silent = [], 0
                        if wake_on:
                            try:
                                hit, _s = wake_score(pcm, thr)
                            except Exception:
                                hit = False
                            if not hit:
                                _SHADOW_METRICS["false_wake"] = \
                                    int(_SHADOW_METRICS.get("false_wake", 0)) + 1
                                continue
                        bio = _io.BytesIO()
                        with _wv.open(bio, "wb") as wf:
                            wf.setnchannels(MIC_CHANNELS)
                            wf.setsampwidth(2)
                            wf.setframerate(MIC_RATE)
                            wf.writeframes(pcm)
                        t0 = _t.time()
                        try:
                            text = transcribe_wav_bytes(bio.getvalue(),
                                                        model_name=model)
                        except Exception as e:
                            _log(f"VOICE_SHADOW: STT fallo: {e}")
                            continue
                        dt = _t.time() - t0
                        if text.strip():
                            shadow_append(cfg, text.strip()[:2000], dt,
                                          wake=wake_on, stt_model=model)
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            try:
                pa.terminate()
            except Exception:
                pass

    t = _th.Thread(target=_run, name="VoiceShadow", daemon=True)
    t.start()
    return t
