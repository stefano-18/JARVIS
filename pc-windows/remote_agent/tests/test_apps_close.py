"""apps.close honesto + propiedad por instantaneas. Todo mockeado."""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions_apps as AA

CTX = {"apps": {"demo": "demo.exe"}}


def run(coro):
    return asyncio.run(coro)


def _fake_run_factory(code, stderr="", stdout="", capture=None):
    def _fake(*a, **k):
        if capture is not None:
            capture.append((a, k))
        return types.SimpleNamespace(returncode=code, stderr=stderr,
                                     stdout=stdout)
    return _fake


def _ctx_owned(app="demo", pids=None, exe="demo.exe"):
    return {"apps": {"demo": "demo.exe"},
            "_owned": {"demo": {"pids": list(pids or [4242]),
                                "exe": exe, "app": app}}}


def test_close_exit_0_closed_true_force(monkeypatch):
    monkeypatch.setattr(AA, "_snapshot", lambda exes: {})
    monkeypatch.setattr(AA.subprocess, "run", _fake_run_factory(0))
    r = run(AA.apps_close({"app": "demo", "force": True}, dict(CTX)))
    assert r["status"] == "ok" and r["closed"] is True, r
    assert r["owned"] is False, r
    assert r["exit_code"] == 0 and "message" in r, r
    assert r["killed_pids"] == [], r


def test_close_not_found_closed_false_con_motivo_force(monkeypatch):
    import sys as _sys
    expect = 128 if _sys.platform == "win32" else 1
    monkeypatch.setattr(AA, "_snapshot", lambda exes: {})
    monkeypatch.setattr(AA.subprocess, "run", _fake_run_factory(
        expect, stderr="ERROR: no se encontro el proceso"))
    r = run(AA.apps_close({"app": "demo", "force": True}, dict(CTX)))
    assert r["status"] == "error" and r["closed"] is False, r
    assert r["owned"] is False, r
    assert r["exit_code"] == expect, r
    assert "no estaba en ejecucion" in r["error"], r
    assert r["killed_pids"] == [], r


def test_close_otro_codigo_error_closed_false_force(monkeypatch):
    monkeypatch.setattr(AA, "_snapshot", lambda exes: {})
    monkeypatch.setattr(AA.subprocess, "run", _fake_run_factory(
        5, stderr="Acceso denegado"))
    r = run(AA.apps_close({"app": "demo", "force": True}, dict(CTX)))
    assert r["status"] == "error" and r["closed"] is False, r
    assert r["owned"] is False, r
    assert r["exit_code"] == 5 and "NO digas que se cerro" in r["error"], r


def test_close_fuera_de_allowlist_closed_false():
    r = run(AA.apps_close({"app": "no-existe"}, dict(CTX)))
    assert r["status"] == "error" and r["closed"] is False, r
    assert r.get("owned") is False, r
    assert r.get("killed_pids") == [], r
    assert "allowlist" in r["error"], r


def test_close_excepcion_closed_false_force(monkeypatch):
    def _boom(*a, **k):
        raise OSError("taskkill roto")
    monkeypatch.setattr(AA, "_snapshot", lambda exes: {})
    monkeypatch.setattr(AA.subprocess, "run", _boom)
    r = run(AA.apps_close({"app": "demo", "force": True}, dict(CTX)))
    assert r["status"] == "error" and r["closed"] is False, r
    assert r.get("owned") is False, r
    assert r.get("killed_pids") == [], r


def test_close_propio_usa_pid_arbol(monkeypatch):
    capture = []
    monkeypatch.setattr(AA, "_pid_image", lambda pid: "demo.exe")
    monkeypatch.setattr(AA.subprocess, "run",
                        _fake_run_factory(0, capture=capture))
    r = run(AA.apps_close({"app": "demo"}, _ctx_owned()))
    assert r["status"] == "ok" and r["closed"] is True, r
    assert r["owned"] is True and r["exit_code"] == 0, r
    assert r["killed_pids"] == [4242], r
    args = capture[0][0][0]
    assert "/PID" in args and "/T" in args, args
    assert "/IM" not in args, args


def test_close_ajeno_sin_force_rechaza_sin_tocar_so(monkeypatch):
    called = []
    monkeypatch.setattr(AA.subprocess, "run",
                        _fake_run_factory(0, capture=called))
    r = run(AA.apps_close({"app": "demo"}, dict(CTX)))
    assert r["status"] == "error" and r["closed"] is False, r
    assert r["owned"] is False, r
    assert r["killed_pids"] == [], r
    assert "no la abri yo" in r["error"], r
    assert called == [], "no debe tocar el SO sin force"
