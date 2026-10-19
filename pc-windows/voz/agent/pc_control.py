"""
Control de energía del PC fijo por voz (Windows 11).

Escucha la frase de activación, graba el comando y lo reconoce con el motor
de voz de Windows (SAPI). Si coincide con apagado, reinicio o bloqueo, lo
ejecuta localmente; si no, reenvía el audio al servidor Jarvis en la laptop.

Comandos soportados (español, variantes):
  - Apagar: "apaga el pc", "apaga el ordenador", "shutdown"
  - Reiniciar: "reinicia el pc", "reinicia el ordenador", "restart"
  - Bloquear: "bloquea la pantalla", "bloquea el pc", "lock"
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Optional

import numpy as np
import pyaudio

_last_cine = 0.0  # último mp3 cinematográfico reproducido (epoch). SAPI solo si no hay audio.

# --- P0-2 mutex IDLE/LISTENING/SPEAKING + anti-solape (ligero, single-thread) ---
import threading as _th
_STATE = "IDLE"
_SPEAKING = _th.Event()
_TTS_LOCK = _th.Lock()
_TTS_GEN = 0
_SAPI_VOICE = None


def _set_state(s: str) -> None:
    global _STATE
    _STATE = s


def _stop_current_tts() -> None:
    """Cancela TTS en curso: sube generación + cierra MCI (mp3) + purga SAPI."""
    global _TTS_GEN
    with _TTS_LOCK:
        _TTS_GEN += 1
    try:
        from ctypes import windll
        windll.winmm.mciSendStringW("close all", None, 0, None)
    except Exception:
        pass
    try:
        if _SAPI_VOICE is not None:
            try:
                _SAPI_VOICE.Skip("Sentence", 2 ** 31 - 1)
            except Exception:
                pass
    except Exception:
        pass


def _play_audio_bytes(data: bytes, tag: str = "tts", mime: str = "audio/mp3") -> None:
    """Reproduce MP3 o WAV sin abrir ninguna app (playsound). Marca tiempo para callar a SAPI.
    Mime-aware: el sufijo sigue al formato real (Piper WAV 22050 Hz -> .wav, MP3 -> .mp3),
    con sniff de magic bytes como respaldo. Sin dependencia de sample rate (MCI lo resuelve)."""
    global _last_cine
    import tempfile
    import threading
    from pathlib import Path as _P

    raw = bytes(data or b"")
    if len(raw) < 100:
        return
    m = (mime or "").lower()
    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
        suffix, mime_eff = ".wav", "audio/wav"
    elif raw[:3] == b"ID3" or raw[:2] == b"\xff\xfb":
        suffix, mime_eff = ".mp3", "audio/mp3"
    elif "wav" in m:
        suffix, mime_eff = ".wav", "audio/wav"
    else:
        suffix, mime_eff = ".mp3", "audio/mp3"
    try:
        tmp = _P(tempfile.gettempdir()) / f"jarvis_{tag}_{int(__import__('time').time() * 1000)}{suffix}"
        tmp.write_bytes(raw)
    except Exception as e:
        logger.debug("TTS audio guardado fallo: %s", e)
        return

    _stop_current_tts()  # wake nuevo cancela TTS en curso, no solapa
    with _TTS_LOCK:
        my_gen = _TTS_GEN + 1
        _TTS_GEN = my_gen
    _SPEAKING.set()
    _set_state("SPEAKING")

    def _run():
        global _last_cine
        try:
            import playsound
            _last_cine = __import__('time').time()
            playsound.playsound(str(tmp), block=True)
        except Exception as e:
            logger.info("TTS audio play fallo (%s %d bytes): %s", mime_eff, len(raw), e)
        finally:
            try:
                tmp.unlink()
            except Exception:
                pass
            with _TTS_LOCK:
                if my_gen == _TTS_GEN:
                    _SPEAKING.clear()
                    _set_state("IDLE")

    threading.Thread(target=_run, name="JarvisCine", daemon=True).start()


def _play_mp3_bytes(data: bytes, tag: str = "tts") -> None:
    """Compat: wrapper MP3 del reproductor mime-aware."""
    _play_audio_bytes(data, tag=tag, mime="audio/mp3")


def _cine_reciente(segs: float = 20.0) -> bool:
    import time
    return (time.time() - _last_cine) < segs


def _on_tts_chunk(chunk: bytes, mime: str) -> None:
    logger.info("TTS cinematografico %d bytes (%s)", len(chunk or b""), mime)
    if chunk:
        _play_mp3_bytes(bytes(chunk))

try:
    from kws_vosk import VoskKWS  # offline ES, sin tflite ni claves
except Exception:
    VoskKWS = None  # type: ignore
try:
    from kws_sherpa import SherpaKWS  # reserva (no compone 'jarvis' bien)
except Exception:
    SherpaKWS = None  # type: ignore
try:
    from openwakeword.model import Model
except Exception:
    Model = None  # type: ignore

AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from ws_client import DEFAULT_WS_URL, JarvisWsClient

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK = 1280
FORMAT = pyaudio.paInt16
WAKE_THRESHOLD = float(os.environ.get("JARVIS_WAKE_THRESHOLD", "0.55"))
RECORD_SECONDS = float(os.environ.get("JARVIS_RECORD_SECONDS", "6"))
COOLDOWN_SEC = float(os.environ.get("JARVIS_WAKE_COOLDOWN", "2.5"))
WAKE_MODELS = os.environ.get("JARVIS_WAKE_MODELS", "hey_jarvis").split(",")

SHUTDOWN_DELAY_SEC = int(os.environ.get("JARVIS_SHUTDOWN_DELAY", "5"))

_POWER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(apaga|apagar|shutdown|cierra)\b.*\b(pc|ordenador|equipo|computadora)\b", re.I), "shutdown"),
    (re.compile(r"\b(reinicia|reiniciar|restart)\b.*\b(pc|ordenador|equipo|computadora)\b", re.I), "restart"),
    (re.compile(r"\b(reinicia|reiniciar|restart)\b", re.I), "restart"),
    (re.compile(r"\b(bloquea|bloquear|lock)\b.*\b(pantalla|pc|ordenador|sesi[oó]n)\b", re.I), "lock"),
    (re.compile(r"\b(bloquea la pantalla|lock screen|lock workstation)\b", re.I), "lock"),
]

def _sapi_powershell_command(wav_path: str) -> str:
    escaped = wav_path.replace("'", "''")
    return (
        f"Add-Type -AssemblyName System.Speech; "
        f"$e = New-Object System.Speech.Recognition.SpeechRecognitionEngine("
        f"[System.Globalization.CultureInfo]::GetCultureInfo('es-ES')); "
        f"$e.SetInputToWaveFile('{escaped}'); "
        f"$r = $e.Recognize(); "
        f"if ($null -eq $r) {{ exit 2 }}; "
        f"Write-Output $r.Text"
    )


def _speak_local(text: str) -> None:
    """Voz local SAPI (sin laptop, sin latencia). Quita el (modelo) final."""
    global _SAPI_VOICE
    import re
    import threading
    t = (text or "").strip()
    t = re.sub(r"\s*\([^()]*\)\s*$", "", t).strip()
    if not t:
        return
    t = t[:280]
    _stop_current_tts()
    with _TTS_LOCK:
        my_gen = _TTS_GEN + 1
        _TTS_GEN = my_gen
    _SPEAKING.set()
    _set_state("SPEAKING")

    def _run():
        try:
            import comtypes
            comtypes.CoInitialize()  # obligatorio en hilos no principales
            try:
                from comtypes.client import CreateObject
                v = CreateObject("SAPI.SpVoice")
                global _SAPI_VOICE
                _SAPI_VOICE = v
                # prefiere voz española
                try:
                    best, fallback = None, None
                    for voice in v.GetVoices():
                        desc = str(voice.GetDescription()).lower()
                        lang = None
                        try:
                            lang = str(voice.GetAttribute("Language")).lower()
                        except Exception:
                            pass
                        if "es-es" in desc or (lang and lang.startswith("409")):
                            best = voice
                            break
                        if "sabina" in desc or (lang and lang.startswith("80a")):
                            fallback = fallback or voice
                    v.Voice = best or fallback or v.Voice
                except Exception:
                    pass
                try:
                    v.Volume = 100
                    v.Rate = 0
                except Exception:
                    pass
                v.Speak(t, 0)  # 0 = sincronico: garantiza que suena entero
            finally:
                with _TTS_LOCK:
                    if my_gen == _TTS_GEN:
                        _SPEAKING.clear()
                        _set_state("IDLE")
                        _SAPI_VOICE = None
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass
        except Exception as e:
            logger.info("TTS local fallo: %s", e)

    threading.Thread(target=_run, name="JarvisTTS", daemon=True).start()


def _beep(freq: int = 880, ms: int = 150) -> None:
    try:
        import winsound
        winsound.Beep(freq, ms)
    except Exception:
        pass
def pcm_frames_to_wav(frames: list[bytes], sample_rate: int = SAMPLE_RATE, channels: int = CHANNELS) -> bytes:
    pcm = b"".join(frames)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def int16_frame_to_float32(frame: bytes) -> np.ndarray:
    count = len(frame) // 2
    ints = struct.unpack(f"<{count}h", frame)
    return np.array(ints, dtype=np.float32) / 32768.0


def match_power_command(text: str) -> Optional[str]:
    """Devuelve 'shutdown', 'restart', 'lock' o None."""
    normalized = " ".join(text.strip().split())
    if not normalized:
        return None
    for pattern, action in _POWER_PATTERNS:
        if pattern.search(normalized):
            return action
    return None


def execute_power_action(action: str) -> str:
    """Ejecuta la acción nativa de Windows 11."""
    action = action.lower().strip()
    if action == "shutdown":
        cmd = ["shutdown", "/s", "/t", str(SHUTDOWN_DELAY_SEC), "/c", "Jarvis: apagado por voz"]
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return f"Apagando el PC en {SHUTDOWN_DELAY_SEC} segundos."

    if action == "restart":
        cmd = ["shutdown", "/r", "/t", str(SHUTDOWN_DELAY_SEC), "/c", "Jarvis: reinicio por voz"]
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return f"Reiniciando el PC en {SHUTDOWN_DELAY_SEC} segundos."

    if action == "lock":
        subprocess.Popen(
            ["rundll32.exe", "user32.dll,LockWorkStation"],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return "Pantalla bloqueada."

    return f"Acción desconocida: {action}"


def try_handle_power_command(text: str) -> tuple[bool, str]:
    """
    Si el texto es un comando de energía, lo ejecuta.
    Devuelve (handled, mensaje).
    """
    action = match_power_command(text)
    if not action:
        return False, ""
    message = execute_power_action(action)
    logger.info("Comando de energía local: %s → %s", text, action)
    return True, message


def transcribe_wav_windows_sapi(wav_bytes: bytes) -> Optional[str]:
    """
    Reconocimiento offline/locale con System.Speech (es-ES).
    Devuelve None si no hay reconocimiento o falla el motor.
    """
    if os.name != "nt":
        return None

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes)
        wav_path = tmp.name

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _sapi_powershell_command(wav_path),
            ],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 2:
            return None
        if result.returncode != 0:
            logger.debug("SAPI stderr: %s", (result.stderr or "").strip())
            return None
        text = (result.stdout or "").strip()
        return text or None
    except subprocess.TimeoutExpired:
        logger.warning("Reconocimiento de voz SAPI agotó el tiempo.")
        return None
    except Exception as exc:
        logger.debug("SAPI no disponible: %s", exc)
        return None
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass


def handle_ws_pc_action(data: dict) -> Optional[str]:
    """Procesa mensajes WebSocket remotos type=pc_action (desde la laptop)."""
    if data.get("type") != "pc_action":
        return None
    action = str(data.get("action") or "").lower().strip()
    if action not in ("shutdown", "restart", "lock"):
        logger.warning("pc_action desconocida: %s", action)
        return None
    msg = execute_power_action(action)
    logger.info("pc_action remota: %s", msg)
    return msg


class PcControlVoiceAgent:
    """Wake word + reconocimiento local de comandos de energía + fallback Jarvis."""

    def __init__(self, ws_url: str = DEFAULT_WS_URL) -> None:
        # on_tts_chunk=None activaría autoplay por defecto en ws_client -> doble voz.
        # Lo anulamos: todo TTS se gestiona en _on_ws_message (voice_result.audio preferido).
        self.ws = JarvisWsClient(ws_url, on_message=self._on_ws_message, on_tts_chunk=lambda _c, _m: None)
        self.audio = pyaudio.PyAudio()
        if VoskKWS is not None:
            self.model = VoskKWS()
            logger.info("KWS: vosk-es offline")
        elif SherpaKWS is not None:
            self.model = SherpaKWS()
            logger.info("KWS: sherpa-onnx offline")
        elif Model is not None:
            self.model = Model(wakeword_models=[m.strip() for m in WAKE_MODELS if m.strip()])
            logger.info("KWS: openwakeword")
        else:
            raise RuntimeError("Sin motor KWS (sherpa-onnx ni openwakeword disponibles)")
        self._last_wake = 0.0

    def _on_ws_message(self, data: dict) -> None:
        msg = handle_ws_pc_action(data)
        if msg:
            self.ws.send_subtitle(msg)
            return
        # Respuesta de voz de la laptop: prefiere audio cinematográfico (Piper MP3 o edge MP3).
        # SAPI solo si no hay audio (respaldo). Evita doble voz voice_result.audio + tts_chunk.
        if os.environ.get("JARVIS_VOICE_REPLY", "1") == "1":
            t = str(data.get("type") or "")
            if t == "voice_result":
                b64 = data.get("audio")
                if b64:
                    try:
                        import base64 as _b64
                        _play_audio_bytes(_b64.b64decode(b64), tag="cine",
                                          mime=str(data.get("audio_mime") or "audio/mp3"))
                        return
                    except Exception as e:
                        logger.debug("voice_result audio fallo, SAPI: %s", e)
                if _cine_reciente():
                    return
                _speak_local(str(data.get("reply") or data.get("text") or ""))
            elif t == "tts_chunk" and data.get("data"):
                # Ya reproducido vía voice_result.audio; ignorar duplicado si cine reciente
                if _cine_reciente(30.0):
                    return
                try:
                    import base64 as _b64
                    _play_audio_bytes(_b64.b64decode(data["data"]), tag="cine",
                                      mime=str(data.get("mime") or "audio/mp3"))
                except Exception:
                    pass
            elif t == "subtitle":
                txt = str(data.get("text") or "")
                # solo habla subtitulos-respuesta, no estados ("Te escucho…")
                if txt and not txt.startswith(("Te escucho", "Tú:")):
                    if _cine_reciente():
                        return
                    _speak_local(txt)

    def _open_stream(self):
        want = os.environ.get("JARVIS_MIC_NAME", "fifine").strip().lower()
        idx = None
        try:
            for i in range(self.audio.get_device_count()):
                di = self.audio.get_device_info_by_index(i)
                if di.get("maxInputChannels", 0) > 0 and want and want in str(di.get("name", "")).lower():
                    idx = i
                    logger.info("Micro seleccionado [%d]: %s", i, di.get("name"))
                    break
        except Exception as e:
            logger.debug("Listado de micros fallo: %s", e)
        if idx is None:
            try:
                idx = int(os.environ.get("JARVIS_MIC_INDEX", "-1"))
                if idx < 0:
                    idx = None
            except Exception:
                idx = None
        return self.audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=idx,
            frames_per_buffer=CHUNK,
        )

    def _wake_detected(self, scores: dict) -> bool:
        for _name, score in scores.items():
            if score >= WAKE_THRESHOLD:
                return True
        return False

    def _record_utterance(self, stream) -> bytes:
        """Graba hasta fin de habla (VAD por energía), no los RECORD_SECONDS fijos.

        Corta a los ~0.8s de silencio tras detectar voz (máx RECORD_SECONDS).
        'Abre spotify' hablado en 1.5s deja de grabar en ~2.3s en vez de 6s.
        Umbrales por env: JARVIS_VAD_THRESHOLD (def 0.02), JARVIS_END_SILENCE (def 0.8s).
        """
        import numpy as _np

        try:
            _vad_thr = float(os.environ.get("JARVIS_VAD_THRESHOLD", "0.02"))
        except Exception:
            _vad_thr = 0.02
        try:
            _end_sil = float(os.environ.get("JARVIS_END_SILENCE", "0.8"))
        except Exception:
            _end_sil = 0.8
        max_chunks = int(RECORD_SECONDS * SAMPLE_RATE / CHUNK)
        min_chunks = int(0.5 * SAMPLE_RATE / CHUNK)  # mínimo 0.5s aunque haya silencio
        sil_chunks = int(_end_sil * SAMPLE_RATE / CHUNK)
        frames: list[bytes] = []
        speech_seen, silent_run = False, 0
        for _ in range(max_chunks):
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
            try:
                rms = float(_np.sqrt(_np.mean(_np.frombuffer(data, dtype=_np.int16).astype(_np.float32) ** 2)) / 32768.0)
            except Exception:
                rms = 1.0
            if rms >= _vad_thr:
                speech_seen, silent_run = True, 0
            elif speech_seen:
                silent_run += 1
                if len(frames) >= min_chunks and silent_run >= sil_chunks:
                    break
        logger.info("Grabación cortada en %.1fs (%d chunks, voz=%s)", len(frames) * CHUNK / SAMPLE_RATE, len(frames), speech_seen)
        wav = pcm_frames_to_wav(frames)
        # Ganancia digital (Fifine bajo): x4 por defecto, con clip. Env JARVIS_MIC_GAIN.
        try:
            gain = float(os.environ.get("JARVIS_MIC_GAIN", "4.0"))
        except Exception:
            gain = 4.0
        if gain != 1.0:
            try:
                import numpy as _np
                import io as _io
                import wave as _wv
                raw = b"".join(frames)
                a = _np.frombuffer(raw, dtype=_np.int16).astype(_np.float32) * gain
                a = _np.clip(a, -32768, 32767).astype(_np.int16)
                buf = _io.BytesIO()
                with _wv.open(buf, "wb") as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(2)
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(a.tobytes())
                wav = buf.getvalue()
            except Exception as e:
                logger.debug("Ganancia mic fallo: %s", e)
        return wav

    def run(self) -> None:
        self.ws.start()
        self.ws.set_state("idle")
        logger.info(
            "PC control + voz activo (WOL no aplica aquí). WS=%s modelos=%s",
            self.ws.url,
            WAKE_MODELS,
        )

        stream = self._open_stream()
        try:
            while True:
                frame = stream.read(CHUNK, exception_on_overflow=False)
                if _SPEAKING.is_set():
                    continue  # TTS en curso: no escuchar (evita auto-disparo por altavoz)
                audio = int16_frame_to_float32(frame)
                prediction = self.model.predict(audio)
                if not self._wake_detected(prediction):
                    continue
                # Doble confirmación: exige 2ª detección en 0.5s (filtra falsos positivos Vosk parcial)
                try:
                    import time as _t
                    _t.sleep(0.12)
                    frame2 = stream.read(CHUNK, exception_on_overflow=False)
                    pred2 = self.model.predict(int16_frame_to_float32(frame2))
                    if not self._wake_detected(pred2):
                        logger.debug("WAKE descartado (sin confirmación): %s", prediction)
                        continue
                except Exception:
                    pass

                now = time.time()
                if now - self._last_wake < COOLDOWN_SEC:
                    continue
                self._last_wake = now
                _stop_current_tts()  # cancela resto anterior antes de escuchar
                _set_state("LISTENING")
                logger.info("WAKE detectado %s -> grabando %.0fs", prediction, RECORD_SECONDS)
                if os.environ.get("JARVIS_WAKE_BEEP", "0") == "1":
                    _beep()

                self.ws.set_state("listening")
                self.ws.send_subtitle("Te escucho…")
                wav_bytes = self._record_utterance(stream)

                self.ws.set_state("thinking")
                transcript = transcribe_wav_windows_sapi(wav_bytes)
                if transcript:
                    logger.info("Transcripción local: %s", transcript)
                    handled, message = try_handle_power_command(transcript)
                    if handled:
                        self.ws.send_subtitle(message)
                        self.ws.set_state("idle")
                        continue
                    self.ws.send_subtitle(f"Tú: {transcript}")

                self.ws.send_audio_wav(wav_bytes, wait=True)
                _set_state("IDLE")
                logger.info("Audio %d bytes enviado a laptop (SAPI=%s)",
                            len(wav_bytes), transcript or "None")
        except KeyboardInterrupt:
            logger.info("Agente de control PC detenido.")
        finally:
            stream.stop_stream()
            stream.close()
            self.audio.terminate()
            self.ws.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS control de energía por voz (PC fijo)")
    parser.add_argument("--ws", default=DEFAULT_WS_URL, help="WebSocket del servidor en la laptop")
    parser.add_argument(
        "--text",
        help="Probar un comando en texto (sin micrófono), p. ej. --text \"apaga el pc\"",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.text:
        handled, message = try_handle_power_command(args.text)
        if handled:
            print(message)
        else:
            print("No coincide con apagado/reinicio/bloqueo.")
        return

    PcControlVoiceAgent(ws_url=args.ws).run()


if __name__ == "__main__":
    main()
