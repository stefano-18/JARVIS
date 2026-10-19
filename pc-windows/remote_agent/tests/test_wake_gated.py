"""Wake-gated en vivo: solo envia tras 'Hey Jarvis'. Mockeado, sin micro
real, sin hub, sin hilos infinitos (simula el bucle con N iteraciones)."""
import os
import queue as _q
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voice as V


def test_live_arm_logic():
    assert V.live_should_arm(False, False) is True
    assert V.live_should_arm(False, True) is True
    assert V.live_should_arm(True, False) is False
    assert V.live_should_arm(True, True) is True
    assert V.live_next_armed(False) is True
    assert V.live_next_armed(True) is False


def _simulate_live(chunks, hits, vad_level=100.0, playing=False):
    """Replica la logica del bucle de start_mic_stt con wake-gated,
    acotada a len(chunks). Retorna (enviados, armed_final, stops)."""
    wake_on, thr = True, 0.5
    armed = V.live_should_arm(wake_on, False)
    buf, silent, sent, stops = [], 0, [], 0
    hit_iter = iter(hits)
    for data in chunks:
        hit = next(hit_iter, False)
        if playing and hit:
            stops += 1
            buf, silent, armed = [], 0, True
            continue
        if not armed:
            if hit:
                armed = True
                buf, silent = [], 0
            continue
        level = 0.0 if set(data) == {0} else vad_level
        if level >= 25:
            buf.append(data)
            silent = 0
        elif buf:
            buf.append(data)
            silent += 1
            if silent >= 2 or len(buf) >= 75:
                sent.append(b"".join(buf))
                buf, silent = [], 0
                armed = V.live_next_armed(wake_on)
    return sent, armed, stops


def test_wake_gated_sends_only_after_wake():
    voice = b"\x01\x02" * 512
    chunks = [voice] * 6
    # sin wake en las 2 primeras, hit en la 3a -> solo desde ahi se acumula
    sent, armed, _ = _simulate_live(chunks, [False, False, True, False,
                                             False, False])
    assert len(sent) == 0  # 3 chunks con voz no cierran frase (silencio=2)
    assert armed is True  # quedo armado tras el wake


def test_no_wake_no_send():
    voice = b"\x01\x02" * 512
    sent, armed, _ = _simulate_live([voice] * 6, [False] * 6)
    assert sent == [] and armed is False


def test_disarm_after_phrase():
    assert V.live_next_armed(True) is False  # exige nuevo wake
    voice = b"\x01\x02" * 512
    sil = b"\x00\x00" * 512
    # wake, voz, voz, silencio, silencio -> cierra 1 frase y desarma
    sent, armed, _ = _simulate_live(
        [voice, voice, voice, sil, sil, voice, voice],
        [True, False, False, False, False, False, False],
        vad_level=100.0)
    assert len(sent) == 1 and armed is False


def test_stop_for_wake_marks_not_playing(monkeypatch):
    called = {}
    monkeypatch.setattr(V, "_stop_current_tts",
                        lambda: called.setdefault("stop", True))
    V.set_playing(True)
    V.stop_for_wake()
    assert called.get("stop") is True and V.is_playing() is False


def test_start_mic_stt_wake_log_path(monkeypatch):
    """start_mic_stt con VOICE_WAKE=1 anuncia modo wake-gated (hilo mock
    que falla al abrir micro y sale sin colgar)."""
    class _PA:
        paInt16 = 1
        def open(self, **k):
            raise RuntimeError("mock sin micro")
        def terminate(self):
            pass
    monkeypatch.setattr(V, "_find_mic", lambda pa: (_PA(), 0))
    logs = []
    pytest.importorskip("pyaudio")  # real, solo para pasar al mock de _find_mic
    import pyaudio
    t = V.start_mic_stt({"VOICE_WAKE": "1", "VOICE_VAD": "25",
                         "VOICE_STT_MODEL": "m", "VOICE_WAKE_THRESHOLD": "0.5"},
                        _q.Queue(), log_fn=logs.append)
    t.join(timeout=5)
    assert any("wake-gated" in m for m in logs), logs
