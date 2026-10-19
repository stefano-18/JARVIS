"""Limitador local HIGH: max 10/min y 60/hora (deslizantes, configurables).

Reloj simulado via ctx["_clock"]: sin tocar el SO ni la red.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as C
from agent import execute_action, build_ctx
from audit import AuditLog
from protocol import mint_grant

SECRET = "testsecret-solo-para-tests"


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self, t=1000000.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


async def _fake_high(params, ctx):
    return {"status": "ok", "mock": True}


HIGH = {"name": "test.high", "params": {}, "risk": "high",
        "timeout": 5, "module": "test", "scope": "", "fn": _fake_high}
LOW = {"name": "system.info", "params": {}, "risk": "low",
       "timeout": 5, "module": "test", "scope": "",
       "fn": _fake_high}


def _ctx(clock, per_min=10, per_hour=60):
    return {"roots": [], "apps": {}, "commands": [],
            "high_max_per_minute": per_min, "high_max_per_hour": per_hour,
            "_clock": clock, "_high_ts": [], "_kill_locked": False}


def test_defaults_config_y_build_ctx():
    cfg = C.load(overrides={"DEVICE_ID": "x", "SECRET": "y"},
                 dotenv_path=__import__("pathlib").Path("/no/existe/.env"))
    assert cfg.get("HIGH_MAX_PER_MINUTE", "10") == "10", cfg
    assert cfg.get("HIGH_MAX_PER_HOUR", "60") == "60", cfg
    ctx = build_ctx(cfg)
    assert ctx["high_max_per_minute"] == 10, ctx
    assert ctx["high_max_per_hour"] == 60, ctx


def test_minuto_permite_10_y_deniega_11(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    clock = Clock()
    ctx = _ctx(clock, per_min=10, per_hour=60)
    used = set()
    for i in range(10):
        g = mint_grant(SECRET, "test.high", {})
        r = run(execute_action(HIGH, {}, g, ctx, SECRET, used,
                               log=log, trace_id=f"t-m-{i}"))
        assert r.get("status") == "ok", (i, r)
    g = mint_grant(SECRET, "test.high", {})
    r = run(execute_action(HIGH, {}, g, ctx, SECRET, used,
                           log=log, trace_id="t-m-11"))
    assert r["status"] == "error" and r.get("executed") is False, r
    assert r["error"].startswith("limite de acciones HIGH superado; espera "), r
    assert r["error"].endswith(" s"), r
    # denegacion auditada
    rows = log._read()
    assert len(rows) == 11 and rows[-1]["result"] == "error", rows
    assert rows[-1]["action"] == "test.high" and rows[-1]["risk"] == "high"
    ok, msg = log.verify()
    assert ok, msg


def test_ventana_desliza_con_reloj_simulado(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    clock = Clock()
    ctx = _ctx(clock, per_min=2, per_hour=100)
    used = set()
    for i in range(2):
        g = mint_grant(SECRET, "test.high", {})
        r = run(execute_action(HIGH, {}, g, ctx, SECRET, used,
                               log=log, trace_id=f"t-s-{i}"))
        assert r.get("status") == "ok", (i, r)
    g = mint_grant(SECRET, "test.high", {})
    r = run(execute_action(HIGH, {}, g, ctx, SECRET, used,
                           log=log, trace_id="t-s-deny"))
    assert r["status"] == "error", r
    assert "espera" in r["error"] and r["error"].endswith(" s"), r
    # la denegacion NO consume cuota: sigue denegando en el mismo instante
    g2 = mint_grant(SECRET, "test.high", {})
    r2 = run(execute_action(HIGH, {}, g2, ctx, SECRET, used,
                            log=log, trace_id="t-s-deny2"))
    assert r2["status"] == "error", r2
    # avanzado 61s la ventana desliza y vuelve a permitir
    clock.advance(61)
    g3 = mint_grant(SECRET, "test.high", {})
    r3 = run(execute_action(HIGH, {}, g3, ctx, SECRET, used,
                            log=log, trace_id="t-s-ok"))
    assert r3.get("status") == "ok", r3


def test_hora_permite_60_y_deniega_61(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    clock = Clock()
    # per_min alto para no interferir; hora = 3 en este test reducido
    ctx = _ctx(clock, per_min=100, per_hour=3)
    used = set()
    for i in range(3):
        g = mint_grant(SECRET, "test.high", {})
        r = run(execute_action(HIGH, {}, g, ctx, SECRET, used,
                               log=log, trace_id=f"t-h-{i}"))
        assert r.get("status") == "ok", (i, r)
        clock.advance(61)  # evita el limite por minuto, acumula la hora
    g = mint_grant(SECRET, "test.high", {})
    r = run(execute_action(HIGH, {}, g, ctx, SECRET, used,
                           log=log, trace_id="t-h-deny"))
    assert r["status"] == "error" and r.get("executed") is False, r
    assert r["error"].startswith("limite de acciones HIGH superado; espera "), r
    # tras 1h desde la primera, vuelve a permitir
    clock.advance(3600)
    g2 = mint_grant(SECRET, "test.high", {})
    r2 = run(execute_action(HIGH, {}, g2, ctx, SECRET, used,
                            log=log, trace_id="t-h-ok"))
    assert r2.get("status") == "ok", r2


def test_low_no_limitado(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    clock = Clock()
    ctx = _ctx(clock, per_min=1, per_hour=1)
    used = set()
    for i in range(5):
        r = run(execute_action(LOW, {}, None, ctx, SECRET, used,
                               log=log, trace_id=f"t-l-{i}"))
        assert r.get("status") == "ok", (i, r)
