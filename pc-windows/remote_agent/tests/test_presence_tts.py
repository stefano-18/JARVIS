"""FASE A3/A4: jr_presence {idle_seconds, session_locked, ts} LOW y
jr_tts priority P0 interrumpe / resto encola. Mockeado, sin SO real."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import presence as PR
import voice as V


def test_presence_payload_exact_format(monkeypatch):
    monkeypatch.setattr(PR, "get_idle_seconds", lambda: 7)
    monkeypatch.setattr(PR, "is_session_locked", lambda: False)
    p = PR.make_presence_payload(ts=1234567890)
    assert set(p.keys()) == {"idle_seconds", "session_locked", "ts"}, p
    assert p == {"idle_seconds": 7, "session_locked": False,
                "ts": 1234567890}
    assert isinstance(p["idle_seconds"], int)
    assert isinstance(p["session_locked"], bool)
    assert isinstance(p["ts"], int)


def test_presence_no_screen_nor_keyboard_content(monkeypatch):
    monkeypatch.setattr(PR, "get_idle_seconds", lambda: 3)
    monkeypatch.setattr(PR, "is_session_locked", lambda: True)
    p = PR.make_presence_payload()
    blob = str(p).lower()
    assert "screen" not in blob and "key" not in blob and "text" not in blob


def test_presence_changed():
    a = {"idle_seconds": 1, "session_locked": False, "ts": 1}
    b = {"idle_seconds": 1, "session_locked": False, "ts": 2}
    assert PR.changed(a, b) is False  # ts no dispara (solo idle/lock)
    c = {"idle_seconds": 2, "session_locked": False, "ts": 2}
    assert PR.changed(a, c) is True
    d = {"idle_seconds": 1, "session_locked": True, "ts": 2}
    assert PR.changed(a, d) is True
    assert PR.changed(None, b) is True


def test_tts_priority_queue_behaviour(monkeypatch):
    V._TTS_QUEUE.clear()
    # P1 encola
    n = V.tts_enqueue(b"a" * 200, "audio/mp3", "t-p1", "P1")
    assert n == 1
    # P0 va al frente (interrumpe)
    V.tts_enqueue(b"b" * 200, "audio/mp3", "t-p0", "P0")
    assert V._TTS_QUEUE[0]["trace"] == "t-p0"
    V._TTS_QUEUE.clear()


def test_handle_tts_priority_p0_interrupts(monkeypatch):
    import agent as AG
    import base64

    async def fake_play(audio, mime):
        return {"played": True, "bytes": len(audio), "mime": mime,
                "error": ""}
    monkeypatch.setattr(AG, "_play_one_tts", fake_play)
    V._TTS_QUEUE.clear()
    V.set_playing(True)
    stopped = {}
    monkeypatch.setattr(V, "_stop_current_tts",
                        lambda: stopped.setdefault("x", True))

    class _WS:
        def __init__(self):
            self.sent = []
        async def send(self, s):
            self.sent.append(s)

    cfg = {"TTS_PRIORITY": "1"}
    audio = base64.b64encode(b"RIFF....WAVE" + b"x" * 200).decode()
    payload = {"audio": audio, "audio_mime": "audio/wav",
               "trace_id": "t-p0", "priority": "P0"}

    class _Log:
        def append(self, *a, **k):
            return {}
    ws = _WS()
    ctr = asyncio.run(AG._handle_tts(ws, "jr_tts", payload, cfg,
                                     "s", _Log(), V.ChunkAssembler(), 0))
    assert ctr >= 1 and stopped.get("x") is True
    V.set_playing(False)
    V._TTS_QUEUE.clear()
