"""FASE B: sesiones, media/volumen, files.ext, verify_sync.
Todo mockeado, dirs temporales, sin tocar procesos del usuario."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions
import session as S
from agent import execute_action
from audit import AuditLog

SECRET = "testsecret-solo-para-tests"


def run(coro):
    return asyncio.run(coro)


async def _ok(params, ctx):
    return {"status": "ok", "mock": True}


MED = {"name": "volume.get", "params": {}, "risk": "medium",
       "timeout": 5, "module": "media", "scope": "media", "fn": _ok}


def _ctx(**kw):
    d = {"roots": [], "apps": {}, "commands": [],
         "high_max_per_minute": 100, "high_max_per_hour": 1000,
         "_kill_locked": False, "session_grants": "1",
         "media_volume": "1", "files_ext": "1"}
    d.update(kw)
    return d


# --- B1 sesiones ---
def test_session_mint_ttl_max_600():
    s = S.mint_session(SECRET, ["volume.get"], 3, ttl_s=9999)
    assert s["expires"] - s["issued"] <= 600


def test_session_rejects_missing_expired_counter():
    ctx = _ctx()
    bad = {"actions": ["volume.get"], "issued": 1, "expires": 9999999999,
           "max_actions": 1, "hmac": "x"}
    ok, _, why = S.check_session(SECRET, bad, "volume.get", ctx)
    assert ok is False
    s = S.mint_session(SECRET, ["volume.get"], 1, ttl_s=1, now=1000)
    ok, _, why = S.check_session(SECRET, s, "volume.get", ctx, now=2000)
    assert ok is False and "caduc" in why
    ctx2 = _ctx()
    s2 = S.mint_session(SECRET, ["volume.get"], 1, ttl_s=600)
    ok, rem, _ = S.check_session(SECRET, s2, "volume.get", ctx2)
    assert ok is True and rem == 0
    S.consume_session(ctx2, s2)
    ok, _, why = S.check_session(SECRET, s2, "volume.get", ctx2)
    assert ok is False and "agot" in why


def test_session_rejects_not_in_list_and_excluded():
    ctx = _ctx()
    s = S.mint_session(SECRET, ["volume.get"], 5)
    ok, _, _ = S.check_session(SECRET, s, "media.next", ctx)
    assert ok is False
    for ex in ("clipboard.read", "shell.exec", "system.shutdown",
               "system.lock", "files.delete"):
        sx = S.mint_session(SECRET, [ex], 5)
        ok, _, why = S.check_session(SECRET, sx, ex, ctx)
        assert ok is False and "EXCLUID" in why, (ex, why)


def test_session_single_active_id(tmp_path):
    ctx = _ctx()
    s1 = S.mint_session(SECRET, ["volume.get"], 5)
    ok, _, _ = S.check_session(SECRET, s1, "volume.get", ctx)
    assert ok is True
    S.consume_session(ctx, s1)
    s2 = S.mint_session(SECRET, ["volume.get"], 5)
    ok, _, why = S.check_session(SECRET, s2, "volume.get", ctx)
    assert ok is False and "otra sesion" in why


def test_session_killswitch_revokes(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl", side="agent")
    ctx = _ctx()
    s = S.mint_session(SECRET, ["volume.get"], 5)
    S.consume_session(ctx, s)
    assert ctx.get("_session_id") == s["session_id"]
    S.revoke_session(ctx)
    assert ctx.get("_session_id") is None


def test_session_response_format_never_empty_error(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl", side="agent")
    ctx = _ctx()
    m = {"name": "volume.get", "params": {}, "risk": "medium",
         "timeout": 5, "module": "media", "scope": "media", "fn": _ok}
    s = S.mint_session(SECRET, ["volume.get"], 2)
    r = run(execute_action(m, {}, s, ctx, SECRET, set(),
                           log=log, trace_id="t-sess-ok"))
    assert set(("status", "executed", "session_remaining",
                "error", "code")) <= set(r.keys()), r
    assert r["status"] == "ok" and r["executed"] is True
    assert r["session_remaining"] == 1
    rows = log._read()
    assert rows[-1]["grant_id"] == s["session_id"]
    assert rows[-1]["result"] == "ok"
    r2 = run(execute_action(m, {}, {"session_id": "x"}, ctx, SECRET,
                            set(), log=log, trace_id="t-sess-bad"))
    assert r2["status"] == "error" and r2["executed"] is False
    assert str(r2["error"]).strip() != "" and str(r2["code"]).strip() != ""


def test_session_off_by_default(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl", side="agent")
    ctx = _ctx(session_grants="0")
    m = {"name": "volume.get", "params": {}, "risk": "medium",
         "timeout": 5, "module": "media", "scope": "media", "fn": _ok}
    s = S.mint_session(SECRET, ["volume.get"], 2)
    r = run(execute_action(m, {}, s, ctx, SECRET, set(),
                           log=log, trace_id="t-off"))
    assert r["status"] == "error" and r["code"] == "feature_disabled"


# --- B2 media/volumen manifiestos + gating ---
def test_media_manifests_risk_medium():
    for n in ("media.play_pause", "media.next", "media.previous",
              "volume.get", "volume.set", "volume.mute"):
        assert n in actions.BY_NAME, n
        assert actions.BY_NAME[n]["risk"] == "medium", n


def test_media_off_by_default(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl", side="agent")
    ctx = _ctx(media_volume="0")
    r = run(execute_action(actions.BY_NAME["media.next"], {}, None,
                           ctx, SECRET, set(), log=log, trace_id="t-m-off"))
    assert r["status"] == "error" and r["code"] == "feature_disabled"


def test_media_mock_play(monkeypatch, tmp_path):
    import actions_media as M
    monkeypatch.setattr(M, "_media_key",
                        lambda w: {"status": "ok", "media": w})
    log = AuditLog(tmp_path / "a.jsonl", side="agent")
    ctx = _ctx()
    for n, w in (("media.play_pause", "play_pause"),
                 ("media.next", "next"), ("media.previous", "previous")):
        r = run(execute_action(actions.BY_NAME[n], {}, None, ctx,
                               SECRET, set(), log=log, trace_id="t-" + n))
        assert r["status"] == "ok", (n, r)


def test_volume_mock(monkeypatch, tmp_path):
    import actions_media as M
    async def _g(p, c):
        return {"status": "ok", "level": 42, "muted": False}
    async def _s(p, c):
        return {"status": "ok", "level": int(p.get("level", 0))}
    async def _m(p, c):
        return {"status": "ok", "muted": True}
    monkeypatch.setattr(M, "volume_get", _g)
    monkeypatch.setattr(M, "volume_set", _s)
    monkeypatch.setattr(M, "volume_mute", _m)
    log = AuditLog(tmp_path / "a.jsonl", side="agent")
    ctx = _ctx()
    r = run(M.volume_get({}, ctx))
    assert r["level"] == 42
    r = run(M.volume_set({"level": 10}, ctx))
    assert r["level"] == 10
    r = run(M.volume_mute({"muted": True}, ctx))
    assert r["muted"] is True


# --- B3 files ---
def test_files_mkdir_hash_inside_roots(tmp_path):
    import asyncio as _a
    import actions_files as F
    root = tmp_path / "r"
    root.mkdir()
    ctx = {"roots": [str(root)], "files_ext": "1",
           "trash_dir": "_jarvis_trash", "output_max": 65536}
    r = _a.run(F.files_mkdir({"path": str(root / "sub" / "x")}, ctx))
    assert r["status"] == "ok"
    assert (root / "sub" / "x").is_dir()
    (root / "f.txt").write_text("abc", encoding="utf-8")
    h = _a.run(F.files_hash({"path": str(root / "f.txt")}, ctx))
    assert h["status"] == "ok" and len(h["sha256"]) == 64
    r2 = _a.run(F.files_mkdir({"path": "C:\\Windows\\nope"}, ctx))
    assert r2["status"] == "error"


def test_files_quarantine_never_permanent(tmp_path):
    import asyncio as _a
    import actions_files as F
    root = tmp_path / "r"
    root.mkdir()
    ctx = {"roots": [str(root)], "files_ext": "1",
           "trash_dir": "_jarvis_trash", "output_max": 65536}
    f = root / "borrar.txt"
    f.write_text("x", encoding="utf-8")
    r = _a.run(F.files_delete({"path": str(f)}, ctx))
    assert r["status"] == "ok"
    assert not f.exists()
    assert "_cuarentena" in r["quarantined"]
    assert (tmp_path / "r" / "_cuarentena").is_dir()


def test_verify_sync_ok():
    ok, diff = actions.verify_sync()
    assert ok is True and diff == {}, diff
