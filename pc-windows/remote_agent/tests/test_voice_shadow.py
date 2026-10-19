"""FASE A1/A2: sombra local (sin envios, sin guardar audio), wake barge-in,
metricas p50/p95. Todo mockeado, dirs temporales."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voice as V


def test_shadow_append_no_audio_only_text(tmp_path, monkeypatch):
    cfg = {"VOICE_SHADOW_LOG": str(tmp_path / "shadow.jsonl")}
    monkeypatch.setattr(V, "_SHADOW_METRICS",
                        {"n": 0, "lat_s": [], "wake_hits": 0,
                         "t0": None, "false_wake": 0})
    e = V.shadow_append(cfg, "hola mundo", 0.42, wake=True, stt_model="medium")
    assert e["text"] == "hola mundo" and "audio" not in e
    txt = (tmp_path / "shadow.jsonl").read_text(encoding="utf-8")
    assert "hola mundo" in txt and "base64" not in txt.lower()
    m = V.shadow_metrics()
    assert m["n"] == 1 and m["wake_hits"] == 1


def test_shadow_metrics_p50_p95(monkeypatch):
    monkeypatch.setattr(V, "_SHADOW_METRICS",
                        {"n": 4, "lat_s": [0.1, 0.2, 0.3, 1.0],
                         "wake_hits": 2, "t0": 0, "false_wake": 1})
    m = V.shadow_metrics()
    assert m["lat_p50"] >= 0.2 and m["lat_p95"] >= 0.3
    assert m["triggers_per_hour"] >= 0 and m["false_wake"] == 1


def test_describe_downloads_informs_size_before_download():
    ds = V.describe_downloads()
    names = [d["name"] for d in ds]
    assert any("jarvis" in n.lower() for n in names)
    for d in ds:
        assert "size_bytes" in d and "present" in d
        assert isinstance(d["size_bytes"], int) and d["size_bytes"] > 0


def test_wake_missing_model_returns_no_hit(monkeypatch):
    import voice as _v
    monkeypatch.setattr(_v.wake_score, "_m", None, raising=False)
    # fuerza fallo de import simulando entorno sin modelo
    hit, score = V.wake_score(b"\x00\x00" * 1280, 0.99)
    assert hit is False and score >= 0.0


def test_stop_for_wake_stops_playback(monkeypatch):
    called = {}
    monkeypatch.setattr(V, "_stop_current_tts",
                        lambda: called.setdefault("stop", True))
    V.set_playing(True)
    assert V.is_playing() is True
    V.stop_for_wake()
    assert called.get("stop") is True and V.is_playing() is False


def test_tts_priority_parse():
    assert V.tts_priority_of({"priority": "P0"}) == "P0"
    assert V.tts_priority_of({"priority": "p2"}) == "P2"
    assert V.tts_priority_of({}) == "P1"
    assert V.tts_priority_of({"priority": "X"}) == "P1"


def test_tts_enqueue_p0_front_and_fifo(monkeypatch):
    V._TTS_QUEUE.clear()
    V.tts_enqueue(b"a", "audio/mp3", "t1", "P1")
    V.tts_enqueue(b"b", "audio/mp3", "t2", "P1")
    V.tts_enqueue(b"x", "audio/mp3", "t0", "P0")
    first = V.tts_dequeue()
    assert first["trace"] == "t0"  # P0 interrumpe (al frente)
    V._TTS_QUEUE.clear()
