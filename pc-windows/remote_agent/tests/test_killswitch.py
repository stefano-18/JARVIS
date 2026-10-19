"""Kill-switch: jr_killswitch bloquea MEDIUM/HIGH (LOW sigue),
jr_unlock sin grant deniega, con grant HIGH valido restaura,
y el estado sobrevive al reinicio (fichero persistente).

Sin red ni SO: execute_action + handlers con ws falso.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import killswitch as KS
from agent import execute_action, _handle_killswitch, _handle_unlock, UNLOCK_ACTION
from audit import AuditLog
from protocol import mint_grant

SECRET = "testsecret-solo-para-tests"


def run(coro):
    return asyncio.run(coro)


async def _fake_ok(params, ctx):
    return {"status": "ok", "mock": True}


HIGH = {"name": "test.high", "params": {}, "risk": "high",
        "timeout": 5, "module": "test", "scope": "", "fn": _fake_ok}
MED = {"name": "files.write", "params": {"path": "x", "content": "y"},
       "risk": "medium", "timeout": 5, "module": "test",
       "scope": "files", "fn": _fake_ok}
LOW = {"name": "system.info", "params": {}, "risk": "low",
       "timeout": 5, "module": "test", "scope": "", "fn": _fake_ok}


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(json.loads(text))


def _ctx_unlocked(tmp_path):
    return {"roots": [], "apps": {}, "commands": [],
            "high_max_per_minute": 1000, "high_max_per_hour": 10000,
            "_high_ts": [],
            "kill_file": str(tmp_path / "killswitch.json")}


def test_bloqueado_deniega_medium_high_y_permite_low(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    ctx = _ctx_unlocked(tmp_path)
    used = set()
    KS.set_locked(ctx["kill_file"], True, "t-lock")
    g = mint_grant(SECRET, "test.high", {})
    rh = run(execute_action(HIGH, {}, g, ctx, SECRET, used,
                            log=log, trace_id="t-k-h"))
    assert rh["status"] == "error" and rh.get("executed") is False, rh
    assert "kill-switch" in rh["error"], rh
    rm = run(execute_action(MED, {"path": "x", "content": "y"}, None,
                            ctx, SECRET, used, log=log, trace_id="t-k-m"))
    assert rm["status"] == "error" and rm.get("executed") is False, rm
    rl = run(execute_action(LOW, {}, None, ctx, SECRET, used,
                            log=log, trace_id="t-k-l"))
    assert rl.get("status") == "ok", rl
    rows = log._read()
    assert [(r["action"], r["result"]) for r in rows] == [
        ("test.high", "error"), ("files.write", "error"),
        ("system.info", "ok")], rows
    assert log.verify()[0]


def test_killswitch_handler_bloquea_y_audita(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    ctx = _ctx_unlocked(tmp_path)
    ws = FakeWS()
    ctr = run(_handle_killswitch(ws, {"trace_id": "t-ks"}, SECRET,
                                 ctx, set(), log, 0))
    assert ctr == 1
    assert KS.is_locked(ctx["kill_file"]) is True
    assert log.verify()[0]
    env = ws.sent[0]
    assert env["type"] == "jr_res", env
    assert env["payload"]["ok"] is True, env
    assert env["payload"]["result"]["locked"] is True, env


def test_unlock_sin_grant_deniega(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    ctx = _ctx_unlocked(tmp_path)
    KS.set_locked(ctx["kill_file"], True, "t-lock")
    ws = FakeWS()
    ctr = run(_handle_unlock(ws, {"trace_id": "t-un"}, SECRET,
                             ctx, set(), log, 5))
    assert ctr == 6
    assert KS.is_locked(ctx["kill_file"]) is True  # sigue bloqueado
    env = ws.sent[0]
    assert env["type"] == "jr_res" and env["payload"]["ok"] is False, env
    res = env["payload"]["result"]
    assert res["status"] == "error" and res["locked"] is True, res
    assert "unlock denegado" in res["error"], res


def test_unlock_con_grant_restaura_y_es_un_solo_uso(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    ctx = _ctx_unlocked(tmp_path)
    KS.set_locked(ctx["kill_file"], True, "t-lock")
    used = set()
    ws = FakeWS()
    g = mint_grant(SECRET, UNLOCK_ACTION, {})
    ctr = run(_handle_unlock(ws, {"trace_id": "t-ok", "grant": g},
                             SECRET, ctx, used, log, 0))
    assert ctr == 1
    assert KS.is_locked(ctx["kill_file"]) is False
    assert g["grant_id"] in used
    env = ws.sent[0]
    assert env["payload"]["ok"] is True, env
    assert env["payload"]["result"]["locked"] is False, env
    # reutilizar el mismo grant se deniega (un solo uso)
    KS.set_locked(ctx["kill_file"], True, "t-relock")
    ws2 = FakeWS()
    ctr2 = run(_handle_unlock(ws2, {"trace_id": "t-re", "grant": g},
                              SECRET, ctx, used, log, 1))
    assert ctr2 == 2
    assert KS.is_locked(ctx["kill_file"]) is True
    assert ws2.sent[0]["payload"]["ok"] is False


def test_estado_sobrevive_al_reinicio(tmp_path):
    kf = str(tmp_path / "killswitch.json")
    KS.set_locked(kf, True, "t-persist")
    # "reinicio": se relee del mismo fichero como haria un proceso nuevo
    assert KS.load(kf)["locked"] is True
    assert KS.is_locked(kf) is True
    KS.set_locked(kf, False, "t-unpersist")
    assert KS.is_locked(kf) is False
