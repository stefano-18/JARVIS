"""Reconciliacion: manifiestos de energia existen en BY_NAME con riesgo HIGH
y quedan auditados via execute_action (fn real JAMAS ejecutada: mock).
Solo lectura de manifiestos + mocks."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions as A
import actions_system as S
from agent import execute_action
from audit import AuditLog
from protocol import mint_grant

SECRET = "testsecret-solo-para-tests"
CTX = {"roots": [], "apps": {}, "commands": []}

EXPECT = {
    "system.shutdown": S.system_shutdown,
    "system.restart": S.system_restart,
    "system.lock": S.system_lock,
    "system.logoff": S.system_logoff,
}


def run(coro):
    return asyncio.run(coro)


def test_manifiestos_energia_high_en_by_name():
    for name, fn in EXPECT.items():
        assert name in A.BY_NAME, f"falta {name}"
        m = A.BY_NAME[name]
        assert m["risk"] == "high", name
        assert m["params"] == {}, name  # sin retardo parametrizable: /t 5 fijo
        assert m["fn"] is fn, name
        assert m["timeout"] == 30 and m["module"] == "system", name


def test_sin_grant_bloqueado_y_auditado(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    used = set()
    for name in EXPECT:
        r = run(execute_action(A.BY_NAME[name], {}, None, CTX, SECRET,
                               used, log=log, trace_id="t-power-deny"))
        assert r["status"] == "error" and r.get("executed") is False, (name, r)
        assert "BLOQUEADO" in r["error"], (name, r)
    rows = log._read()
    assert [(x["action"], x["risk"], x["result"]) for x in rows] == [
        (n, "high", "error") for n in EXPECT]
    ok, msg = log.verify()
    assert ok, msg


def test_con_grant_pasa_politica_y_audita_sin_ejecutar(tmp_path):
    """La fn real (shutdown/reboot/...) se sustituye por mock: la puerta
    HIGH + la auditoria quedan probadas sin tocar el SO."""
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    used = set()

    async def fake_fn(params, ctx):
        return {"status": "ok", "mock": True}

    for name in EXPECT:
        m = dict(A.BY_NAME[name], fn=fake_fn)
        g = mint_grant(SECRET, name, {})
        r = run(execute_action(m, {}, g, CTX, SECRET, used, log=log,
                               trace_id="t-power-grant"))
        assert r.get("status") == "ok", (name, r)
    rows = log._read()
    assert len(rows) == len(EXPECT)
    assert all(x["grant_id"] != "-" and x["result"] == "ok" for x in rows)
    ok, msg = log.verify()
    assert ok, msg
