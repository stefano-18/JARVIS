"""FASE C1: screen.capture monitor/max_width(1280)/jpeg q70 tope 1MB,
{data_b64,width,height,mime} HIGH auditada. Mockeado."""
import asyncio
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions
import actions_desktop as D
from agent import execute_action
from audit import AuditLog
from protocol import mint_grant

SECRET = "testsecret-solo-para-tests"


def run(coro):
    return asyncio.run(coro)


def test_manifest_screen_high():
    assert actions.BY_NAME["screen.capture"]["risk"] == "high"


def test_screen_c1_defaults_1280_q70_cap_1mb(monkeypatch):
    rgb = b"\x10\x20\x30" * (1600 * 900)

    def fake_shot(monitor):
        assert monitor == 1
        # Estructura real de _shot_mss: (rgb_bytes, (w, h))
        return rgb, (1600, 900)

    if D._mss is None:
        monkeypatch.setattr(D, "_mss", object())
    monkeypatch.setattr(D, "_shot_mss", fake_shot)
    res = run(D.screen_capture({"monitor": 1, "format": "jpeg"},
                               {"screen_c1": "1"}))
    assert res["status"] == "ok", res
    assert set(("data_b64", "width", "height", "mime")) <= set(res.keys())
    assert res["width"] == 1280
    assert res["height"] == 720  # 900 * 1280 / 1600 proporcional
    assert res["mime"] == "image/jpeg"
    raw = base64.b64decode(res["data_b64"])
    assert len(raw) <= 1024 * 1024, len(raw)


def test_screen_old_defaults_unchanged(monkeypatch):
    rgb = b"\x10\x20\x30" * (16 * 8)

    def fake_shot(monitor):
        # Estructura real de _shot_mss: (rgb_bytes, (w, h))
        return rgb, (16, 8)

    if D._mss is None:
        monkeypatch.setattr(D, "_mss", object())
    monkeypatch.setattr(D, "_shot_mss", fake_shot)
    res = run(D.screen_capture({"monitor": 1, "format": "png"}, {}))
    assert res["status"] == "ok" and res["mime"] == "image/png"
    assert (res["width"], res["height"]) == (16, 8)


def test_screen_high_audited_with_grant(monkeypatch, tmp_path):
    rgb = b"\x10\x20\x30" * (32 * 16)

    def fake_shot(monitor):
        return rgb, (32, 16)

    monkeypatch.setattr(D, "_shot_mss", fake_shot)
    log = AuditLog(tmp_path / "a.jsonl", side="agent")
    ctx = {"roots": [], "apps": {}, "commands": [],
           "high_max_per_minute": 100, "high_max_per_hour": 1000,
           "_kill_locked": False, "screen_c1": "1",
           "session_grants": "0", "media_volume": "0", "files_ext": "0"}
    m = actions.BY_NAME["screen.capture"]
    g = mint_grant(SECRET, "screen.capture",
                   {"monitor": 1, "format": "jpeg"})
    r = run(execute_action(m, {"monitor": 1, "format": "jpeg"}, g,
                           ctx, SECRET, set(), log=log,
                           trace_id="t-c1"))
    assert r["status"] == "ok", r
    rows = log._read()
    assert rows[-1]["action"] == "screen.capture"
    assert rows[-1]["risk"] == "high" and rows[-1]["result"] == "ok"
    ok, msg = log.verify()
    assert ok, msg
