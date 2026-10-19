"""Compatibilidad de cable jr_killswitch/jr_unlock con los formatos FINALES.

El hub construye los sobres con P.make_envelope y ctr creciente por
dispositivo (igual que jr_req); el agente los valida con ChannelGuard y
los despacha a _handle_killswitch/_handle_unlock. Sin red: FakeWS.

Formato exacto exigido:
  jr_killswitch: payload SOLO {"trace_id"} (sin grant).
  jr_unlock:     payload {"trace_id", "grant"} con grant ligado a
                 agent.unlock + {} (mint_grant en release()).
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions as A
from agent import _handle_killswitch, _handle_unlock, UNLOCK_ACTION
from audit import AuditLog
from protocol import ChannelGuard, make_envelope, mint_grant

SECRET = "testsecret-solo-para-tests"


def run(coro):
    return asyncio.run(coro)


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(json.loads(text))


def _ctx(tmp_path):
    return {"roots": [], "apps": {}, "commands": [],
            "high_max_per_minute": 1000, "high_max_per_hour": 10000,
            "_high_ts": [], "kill_file": str(tmp_path / "killswitch.json")}


def test_sin_manifiestos_viejos():
    """system.killswitch/system.unlock NO existen: por pc_proxy dan
    accion desconocida, nunca viajan con formato viejo."""
    assert "system.killswitch" not in A.BY_NAME
    assert "system.unlock" not in A.BY_NAME


def test_wire_bloqueo_sobre_firmado_ctr_creciente(tmp_path):
    import killswitch as KS
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    ctx, used, ws = _ctx(tmp_path), set(), FakeWS()
    guard = ChannelGuard(SECRET)

    env1 = make_envelope(SECRET, "jr_killswitch", {"trace_id": "w-1"}, 1)
    ok, why = guard.check(env1)
    assert ok, why
    assert set(env1["payload"]) == {"trace_id"}, env1  # SOLO trace_id
    ctr = run(_handle_killswitch(ws, env1["payload"], SECRET, ctx, used,
                                 log, 0))
    assert ctr == 1 and KS.is_locked(ctx["kill_file"]) is True
    assert ws.sent[0]["type"] == "jr_res"
    assert ws.sent[0]["payload"]["result"]["locked"] is True
    assert log.verify()[0]


def test_wire_unlock_grant_ligado_a_agent_unlock(tmp_path):
    import killswitch as KS
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    ctx, used, ws = _ctx(tmp_path), set(), FakeWS()
    guard = ChannelGuard(SECRET)
    KS.set_locked(ctx["kill_file"], True, "w-lock")

    g = mint_grant(SECRET, UNLOCK_ACTION, {})
    assert g["action"] == "agent.unlock"
    env2 = make_envelope(SECRET, "jr_unlock",
                         {"trace_id": "w-2", "grant": g}, 2)
    ok, why = guard.check(env2)
    assert ok, why
    ctr = run(_handle_unlock(ws, env2["payload"], SECRET, ctx, used, log, 1))
    assert ctr == 2  # ctr 1 -> 2, cero sobres jr_req en el camino
    assert KS.is_locked(ctx["kill_file"]) is False
    assert ws.sent[0]["payload"]["ok"] is True
    assert ws.sent[0]["payload"]["result"]["locked"] is False
    assert log.verify()[0]


def test_wire_unlock_grant_de_otra_accion_denegado(tmp_path):
    import killswitch as KS
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    ctx, used, ws = _ctx(tmp_path), set(), FakeWS()
    guard = ChannelGuard(SECRET)
    KS.set_locked(ctx["kill_file"], True, "w-lock")

    g = mint_grant(SECRET, "apps.open", {"app": "calc"})
    env = make_envelope(SECRET, "jr_unlock",
                        {"trace_id": "w-3", "grant": g}, 1)
    assert guard.check(env)[0]
    ctr = run(_handle_unlock(ws, env["payload"], SECRET, ctx, used, log, 0))
    assert ctr == 1
    assert KS.is_locked(ctx["kill_file"]) is True  # sigue bloqueado
    res = ws.sent[0]["payload"]["result"]
    assert ws.sent[0]["payload"]["ok"] is False
    assert res["locked"] is True and "unlock denegado" in res["error"], res
    assert log.verify()[0]
