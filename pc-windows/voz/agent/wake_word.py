"""
Wake word listener for the fixed PC ("Hey Jarvis" via openWakeWord).

On detection: HUD → listening, record microphone, send WAV to laptop for Whisper.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import struct
import sys
import time
import wave
from pathlib import Path

import numpy as np
import pyaudio
from openwakeword.model import Model

AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from ws_client import DEFAULT_WS_URL, JarvisWsClient

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK = 1280  # 80 ms @ 16 kHz (openWakeWord frame)
FORMAT = pyaudio.paInt16
WAKE_THRESHOLD = float(os.environ.get("JARVIS_WAKE_THRESHOLD", "0.55"))
RECORD_SECONDS = float(os.environ.get("JARVIS_RECORD_SECONDS", "6"))
COOLDOWN_SEC = float(os.environ.get("JARVIS_WAKE_COOLDOWN", "2.5"))
WAKE_MODELS = os.environ.get("JARVIS_WAKE_MODELS", "hey_jarvis").split(",")


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
    arr = np.array(ints, dtype=np.float32) / 32768.0
    return arr


class WakeWordAgent:
    def __init__(self, ws_url: str = DEFAULT_WS_URL) -> None:
        self.ws = JarvisWsClient(ws_url)
        self.audio = pyaudio.PyAudio()
        self.model = Model(wakeword_models=[m.strip() for m in WAKE_MODELS if m.strip()])
        self._last_wake = 0.0

    def _open_stream(self):
        return self.audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )

    def _wake_detected(self, scores: dict) -> bool:
        for name, score in scores.items():
            if score >= WAKE_THRESHOLD:
                logger.info("Wake word hit: %s=%.3f", name, score)
                return True
        return False

    def _record_utterance(self, stream) -> bytes:
        frames: list[bytes] = []
        total_chunks = int(RECORD_SECONDS * SAMPLE_RATE / CHUNK)
        for _ in range(total_chunks):
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
        return pcm_frames_to_wav(frames)

    def run(self) -> None:
        self.ws.start()
        self.ws.set_state("idle")
        logger.info("Listening for wake word (%s) → %s", WAKE_MODELS, self.ws.url)

        stream = self._open_stream()
        try:
            while True:
                frame = stream.read(CHUNK, exception_on_overflow=False)
                audio = int16_frame_to_float32(frame)
                prediction = self.model.predict(audio)
                if not self._wake_detected(prediction):
                    continue

                now = time.time()
                if now - self._last_wake < COOLDOWN_SEC:
                    continue
                self._last_wake = now

                self.ws.set_state("listening")
                self.ws.send_subtitle("Te escucho…")
                wav_bytes = self._record_utterance(stream)
                self.ws.set_state("thinking")
                self.ws.send_audio_wav(wav_bytes, wait=True)
        except KeyboardInterrupt:
            logger.info("Wake word agent stopped.")
        finally:
            stream.stop_stream()
            stream.close()
            self.audio.terminate()
            self.ws.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS wake word agent (PC Fijo)")
    parser.add_argument("--ws", default=DEFAULT_WS_URL, help="WebSocket URL of laptop server")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    WakeWordAgent(ws_url=args.ws).run()


if __name__ == "__main__":
    main()
