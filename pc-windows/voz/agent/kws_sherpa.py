"""
KWS offline con sherpa-onnx (sin tflite). Misma interfaz que openwakeword:
  kws = SherpaKWS()
  scores = kws.predict(audio_float32_80ms)  # {"hey jarvis": 1.0} o {}
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = os.environ.get(
    "JARVIS_KWS_DIR",
    r"C:\JARVIS-PC\models\sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01",
)
DEFAULT_KEYWORDS = os.environ.get(
    "JARVIS_KWS_KEYWORDS", r"C:\JARVIS-PC\models\jarvis_keywords.txt"
)


class SherpaKWS:
    def __init__(self, model_dir: str = DEFAULT_MODEL_DIR,
                 keywords_file: str = DEFAULT_KEYWORDS,
                 threshold: float = -1.0) -> None:
        import sherpa_onnx
        if threshold < 0:
            # 0.12: sensible a acento ES; el VAD gate ya filtra el silencio
            threshold = float(os.environ.get("JARVIS_KWS_THRESHOLD", "0.12"))
        d = Path(model_dir)
        enc = next(d.glob("encoder*.onnx"))
        dec = next(d.glob("decoder*.onnx"))
        joi = next(d.glob("joiner*.onnx"))
        tok = d / "tokens.txt"
        self._spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(tok), encoder=str(enc), decoder=str(dec), joiner=str(joi),
            keywords_file=keywords_file, num_threads=1,  # 1 hilo: no compite con juegos
            keywords_threshold=threshold,
        )
        self._stream = self._spotter.create_stream()
        # VAD gate: en silencio no se decodifica (idle ~0% CPU). Ruido sala <0.002.
        self.vad_rms = float(os.environ.get("JARVIS_KWS_VAD_RMS", "0.005"))
        logger.info("KWS sherpa-onnx listo (%s)", d.name)

    def predict(self, audio) -> dict:
        """audio: np float32 mono 16kHz (cualquier longitud). Devuelve dict scores."""
        try:
            import numpy as np
            samples = np.asarray(audio, dtype=np.float32).ravel()
            if samples.size == 0:
                return {}
            rms = float(np.sqrt(np.mean(samples ** 2)))
            if rms < self.vad_rms:
                return {}  # silencio: ni se alimenta el decoder
            self._stream.accept_waveform(16000, samples)
            while self._spotter.is_ready(self._stream):
                self._spotter.decode_stream(self._stream)
            res = self._spotter.get_result(self._stream)
            if res:
                kw = str(getattr(res, "keyword", "hey jarvis") or "hey jarvis")
                self._spotter.reset_stream(self._stream)
                return {kw.lower(): 1.0}
        except Exception as e:
            logger.debug("KWS error: %s", e)
        return {}
