"""ERRORES NUNCA VACIOS: todo status error lleva error legible + code.

Regresion: process.terminate devolvia error:"" (dict sin error) cuando el
PID no existia. Todo mockeado, sin tocar el SO ni procesos reales.
"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions_process as AP
from agent import execute_action
from audit import AuditLog
from protocol import mint_grant

SECRET = "testsecret-solo-para-tests"


def run(coro):
    return asyncio.run(coro)


def _fake_run_factory(code, stderr="", stdout=""):
    def _fake(*a, **k):
        return types.SimpleNamespace(returncode=code, stderr=stderr,
                                     stdout=stdout)
    return _fake


def _assert_honest(res, expect_code=None):
    assert res.get("status") == "error", res
    assert isinstance(res.get("error"), str) and res["error"].strip(), res
    assert isinstance(res.get("code"), str) and res["code"].strip(), res
    if expect_code:
        assert res["code"] == expect_code, res


def test_terminate_pid_inexistente_error_con_texto_y_code(monkeypatch):
    # taskkill exit 128 + mensaje, el caso que antes devolvia error:""
    monkeypatch.setattr(AP.subprocess, "run", _fake_run_factory(
        128, stderr="ERROR: no se encontro el proceso \"123456\"."))
    r = run(AP.process_terminate({"pid": 123456}, {}))
    _assert_honest(r, "pid_not_found")
    assert "no encontrado" in r["error"] and "123456" in r["error"], r


def test_terminate_fallo_sin_detalle_igual_tiene_texto(monkeypatch):
    # stderr/stdout VACIOS: ni asi puede salir error vacio
    monkeypatch.setattr(AP.subprocess, "run", _fake_run_factory(1))
    r = run(AP.process_terminate({"pid": 4242}, {}))
    _assert_honest(r)
    assert "4242" in r["error"], r


def test_terminate_acceso_denegado(monkeypatch):
    monkeypatch.setattr(AP.subprocess, "run", _fake_run_factory(
        1, stderr="ERROR: Acceso denegado."))
    r = run(AP.process_terminate({"pid": 4}, {}))
    _assert_honest(r, "access_denied")


def test_terminate_pid_invalido_y_protegido():
    _assert_honest(run(AP.process_terminate({}, {})), "invalid_pid")
    _assert_honest(run(AP.process_terminate({"pid": 0}, {})), "protected_pid")
    _assert_honest(run(AP.process_terminate({"pid": 1}, {})), "protected_pid")


def test_terminate_posix_pid_inexistente_y_sin_permiso(monkeypatch):
    monkeypatch.setattr(AP.sys, "platform", "linux")

    def _lookup(pid, sig):
        raise ProcessLookupError(3, "No such process")
    monkeypatch.setattr(AP.os, "kill", _lookup)
    _assert_honest(run(AP.process_terminate({"pid": 99991}, {})),
                   "pid_not_found")

    def _denied(pid, sig):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(AP.os, "kill", _denied)
    _assert_honest(run(AP.process_terminate({"pid": 1 + 1}, {})),
                   "access_denied")


def test_execute_action_rellena_error_vacio_de_cualquier_fn(tmp_path):
    """Red de seguridad: aunque una fn devuelva error pelao/vacio,
    execute_action lo entrega con texto y code."""
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")

    async def bare(params, ctx):
        return {"status": "error"}

    async def empty(params, ctx):
        return {"status": "error", "error": ""}

    low_bare = {"name": "t.bare", "risk": "low", "timeout": 5,
                "module": "t", "scope": "", "fn": bare}
    low_empty = {"name": "t.empty", "risk": "low", "timeout": 5,
                 "module": "t", "scope": "", "fn": empty}
    ctx = {"roots": [], "apps": {}, "commands": [], "_kill_locked": False}
    r1 = run(execute_action(low_bare, {}, None, ctx, SECRET, set(),
                            log=log, trace_id="t-e-1"))
    _assert_honest(r1)
    assert "t.bare" in r1["error"], r1
    r2 = run(execute_action(low_empty, {}, None, ctx, SECRET, set(),
                            log=log, trace_id="t-e-2"))
    _assert_honest(r2)
    assert log.verify()[0]


def test_denegaciones_con_code(tmp_path):
    """kill-switch, politica y limite HIGH salen con code estable."""
    import killswitch as KS
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")

    async def _fake_ok(params, ctx):
        return {"status": "ok"}

    high = {"name": "test.high", "risk": "high", "timeout": 5,
            "module": "t", "scope": "", "fn": _fake_ok}
    kf = str(tmp_path / "killswitch.json")
    ctx = {"roots": [], "apps": {}, "commands": [],
           "high_max_per_minute": 1000, "high_max_per_hour": 10000,
           "_high_ts": [], "kill_file": kf}
    KS.set_locked(kf, True, "t-e")
    g = mint_grant(SECRET, "test.high", {})
    r = run(execute_action(high, {}, g, ctx, SECRET, set(),
                           log=log, trace_id="t-e-ks"))
    _assert_honest(r, "killswitch_locked")
    KS.set_locked(kf, False, "t-e")

    r2 = run(execute_action(high, {}, None, ctx, SECRET, set(),
                            log=log, trace_id="t-e-pol"))
    _assert_honest(r2, "policy_denied")

    ctx2 = dict(ctx, high_max_per_minute=1, high_max_per_hour=100,
                _high_ts=[])
    used = set()
    g1 = mint_grant(SECRET, "test.high", {})
    assert run(execute_action(high, {}, g1, ctx2, SECRET, used,
                              log=log, trace_id="t-e-l1"))["status"] == "ok"
    g2 = mint_grant(SECRET, "test.high", {})
    r3 = run(execute_action(high, {}, g2, ctx2, SECRET, used,
                            log=log, trace_id="t-e-l2"))
    _assert_honest(r3, "high_rate_limited")
    assert log.verify()[0]
