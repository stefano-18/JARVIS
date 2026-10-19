"""Fixes diagnostico voz: wake via .onnx + STT en CPU/int8.
Mockeado (sin modelos reales, sin micro), rapido."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voice as V


def test_wake_onnx_path_exists():
    pytest.importorskip("openwakeword")
    p = V.wake_onnx_path()
    assert p.endswith(".onnx") and os.path.exists(p), p


def test_wake_score_uses_onnx_framework(monkeypatch):
    _oww = pytest.importorskip("openwakeword")
    seen = {}

    class _FakeModel:
        def __init__(self, *a, **k):
            seen["kwargs"] = k
        def predict(self, x):
            return {"hey_jarvis_v0.1": 0.9}

    monkeypatch.setattr(_oww, "Model", _FakeModel)
    monkeypatch.delattr(V.wake_score, "_m", raising=False)
    try:
        hit, score = V.wake_score(b"\x00\x00" * 1280, 0.5)
    finally:
        monkeypatch.delattr(V.wake_score, "_m", raising=False)
    assert hit is True and score == 0.9
    kw = seen["kwargs"]
    assert kw.get("inference_framework") == "onnx", kw
    assert str(kw.get("wakeword_models", [""]))[0:1] != "" and \
        kw["wakeword_models"][0].endswith(".onnx"), kw


def test_transcribe_uses_cpu_int8(monkeypatch):
    _fw = pytest.importorskip("faster_whisper")
    seen = {}

    class _Seg:
        text = "hola mundo"

    class _FakeModel:
        def __init__(self, *a, **k):
            seen["args"] = a
            seen["kwargs"] = k
        def transcribe(self, *a, **k):
            return ([_Seg()], None)

    monkeypatch.setattr(_fw, "WhisperModel", _FakeModel)
    monkeypatch.setattr(V, "_stt_model", None)
    try:
        txt = V.transcribe_wav_bytes(b"RIFF" + b"\x00" * 100,
                                     model_name="medium")
    finally:
        monkeypatch.setattr(V, "_stt_model", None)
    assert txt == "hola mundo"
    assert seen["kwargs"].get("device") == "cpu", seen
    assert seen["kwargs"].get("compute_type") == "int8", seen
    assert V._stt_desc == "medium/cpu/int8"


def test_voice_text_payload_for_socket_queue():
    p = V.make_voice_text_payload("enciende la luz", "stt")
    assert p == {"text": "enciende la luz", "source": "stt"}
    # drain_queue es el puente hilo-captura -> jr_voice_text del agent
    import queue as _q
    q = _q.Queue()
    q.put("enciende la luz")
    assert V.drain_queue(q) == ["enciende la luz"]
    assert V.drain_queue(q) == []
