"""
KWS offline con Vosk (modelo ES, gramatica cerrada). Sin tflite, sin claves.
Interfaz: predict(audio_float32) -> {"hey jarvis": 1.0} o {}
Dispara solo si aparece "jarvis" ("hey" solo no vale).
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get(
    "JARVIS_VOSK_MODEL", r"C:\JARVIS-PC\models\vosk-model-small-es-0.42"
)


class VoskKWS:
    def __init__(self, model_dir: str = DEFAULT_MODEL) -> None:
        from vosk import Model, KaldiRecognizer
        self._Model, self._Rec = Model, KaldiRecognizer
        self.model = Model(model_dir)
        self.vad_rms = float(os.environ.get("JARVIS_KWS_VAD_RMS", "0.005"))
        self._rec = None
        self._new_recognizer()
        try:
            from vosk import SetLogLevel
            SetLogLevel(-1)  # silencia LOG de vosk tras arrancar
        except Exception:
            pass
        logger.info("KWS vosk-es listo (gramatica hey jarvis|jarvis)")

    def _new_recognizer(self):
        import numpy as np  # noqa (asegura import ok)
        self._rec = self._Rec(
            self.model, 16000,
            json.dumps(["hey jarvis", "jarvis", "[unk]"], ensure_ascii=False),
        )

    def predict(self, audio) -> dict:
        try:
            import numpy as np
            samples = np.asarray(audio, dtype=np.float32).ravel()
            if samples.size == 0:
                return {}
            rms = float(np.sqrt(np.mean(samples ** 2)))
            if rms < self.vad_rms:
                return {}  # silencio: idle ~0% CPU
            pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            if self._rec.AcceptWaveform(pcm):
                txt = json.loads(self._rec.Result()).get("text", "")
                self._new_recognizer()
                if "jarvis" in txt.lower():
                    return {"hey jarvis": 1.0}
            else:
                # parcial: dispara en cuanto aparece "jarvis" (latencia ~300ms)
                part = json.loads(self._rec.PartialResult()).get("partial", "")
                if "jarvis" in part.lower():
                    self._new_recognizer()
                    return {"hey jarvis": 1.0}
        except Exception as e:
            logger.debug("KWS-vosk error: %s", e)
        return {}
