"""Propiedad por instantaneas: owned real vs was_running, cierre multipid.

Casos exigidos (mockeados, sin tocar el SO):
1. app ya abierta (was_running:true, owned:false, sin registro),
2. app nueva con lanzador efimero (owned con PIDs reales de la instantanea),
3. cierre de lo propio (solo /PID /T, con killed_pids),
4. rechazo sin force de lo ajeno,
5. force por imagen exacta (con conteo de matados).
"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions_apps as AA

IDE = "%LOCALAPPDATA%\\Programs\\Antigravity IDE\\Antigravity IDE.exe"
CTX_APPS = {"apps": {"antigravity": IDE, "antigravity ide": IDE,
                     "demo": "demo.exe", "notepad": "notepad.exe"}}


def run(coro):
    return asyncio.run(coro)


def fast(monkeypatch):
    monkeypatch.setattr(AA, "_SETTLE_POLL", 0.01)
    monkeypatch.setattr(AA, "_SETTLE_TIMEOUT", 0.3)


def _fake_run(code=0, stderr="", stdout="", capture=None):
    def _fake(*a, **k):
        if capture is not None:
            capture.append((a, k))
        return types.SimpleNamespace(returncode=code, stderr=stderr,
                                     stdout=stdout)
    return _fake


def _ctx(**kw):
    ctx = {"apps": dict(CTX_APPS["apps"])}
    ctx.update(kw)
    return ctx


def snap_of(*pids, ppid=0, name="demo.exe"):
    return {p: {"name": name, "ppid": ppid, "created": "20260101"}
            for p in pids}


def test_app_ya_abierta_was_running(monkeypatch):
    # La app ya corre: antes==despues, el lanzador murio -> nada propio.
    fast(monkeypatch)
    existing = snap_of(100, 101, ppid=1)
    monkeypatch.setattr(AA, "_snapshot", lambda exes: dict(existing))
    monkeypatch.setattr(AA.subprocess, "Popen",
                        lambda *a, **k: types.SimpleNamespace(pid=999))
    monkeypatch.setattr(AA, "_pid_image", lambda pid: None)
    ctx = _ctx()
    r = run(AA.apps_open({"app": "demo"}, ctx))
    assert r == {"status": "ok", "app": "demo", "owned": False,
                 "was_running": True, "pids": []}, r
    assert ctx.get("_owned", {}) == {}, "no debe registrar nada ajeno"


def test_app_nueva_lanzador_efimero_owned_real(monkeypatch):
    # Lanzador 999 muere; aparecen 200 (raiz) + 201 (hijo de 200).
    # Solo se registra la raiz 200, no el hijo suelto ni el lanzador.
    fast(monkeypatch)
    seq = [snap_of(), {200: {"name": "demo.exe", "ppid": 999,
                             "created": "t2"},
                     201: {"name": "demo.exe", "ppid": 200,
                           "created": "t2"}}]
    monkeypatch.setattr(AA, "_snapshot", lambda exes: dict(seq[0]))
    monkeypatch.setattr(AA.subprocess, "Popen",
                        lambda *a, **k: types.SimpleNamespace(pid=999))
    monkeypatch.setattr(AA, "_pid_image",
                        lambda pid: "demo.exe" if pid in (200, 201) else None)
    async def _settle_now(exes, launcher):
        return seq[-1]
    monkeypatch.setattr(AA, "_settle", _settle_now)
    ctx = _ctx()
    r = run(AA.apps_open({"app": "demo"}, ctx))
    assert r == {"status": "ok", "app": "demo", "owned": True,
                 "was_running": False, "pids": [200]}, r
    assert ctx["_owned"]["demo"]["pids"] == [200], ctx["_owned"]


def test_cierre_propio_multipid_solo_pid_T(monkeypatch):
    cap = []
    monkeypatch.setattr(AA, "_pid_image", lambda pid: "demo.exe")
    monkeypatch.setattr(AA.subprocess, "run", _fake_run(0, capture=cap))
    ctx = _ctx(_owned={"demo": {"pids": [200, 202], "exe": "demo.exe",
                                "app": "demo"}})
    r = run(AA.apps_close({"app": "demo"}, ctx))
    assert r["status"] == "ok" and r["closed"] is True, r
    assert r["owned"] is True and r["killed_pids"] == [200, 202], r
    assert r["exit_code"] == 0 and "message" in r, r
    for (a, _k) in cap:
        assert "/PID" in a[0] and "/T" in a[0] and "/F" in a[0], a
        assert "/IM" not in a[0], a
    assert ctx.get("_owned", {}).get("demo") is None


def test_rechazo_ajeno_sin_force(monkeypatch):
    called = []
    monkeypatch.setattr(AA.subprocess, "run", _fake_run(0, capture=called))
    r = run(AA.apps_close({"app": "demo"}, _ctx()))
    assert r["status"] == "error" and r["closed"] is False, r
    assert r["owned"] is False and r["killed_pids"] == [], r
    assert "no la abri yo" in r["error"], r
    assert called == []


def test_force_imagen_exacta_con_conteo(monkeypatch):
    before = snap_of(100, 101, 102, ppid=1)
    after = snap_of(102, ppid=1)
    calls = {"n": 0}

    def _snap(exes):
        calls["n"] += 1
        return dict(before) if calls["n"] == 1 else dict(after)

    monkeypatch.setattr(AA, "_snapshot", _snap)
    cap = []
    monkeypatch.setattr(AA.subprocess, "run", _fake_run(0, capture=cap))
    r = run(AA.apps_close({"app": "demo", "force": True}, _ctx()))
    assert r["status"] == "ok" and r["closed"] is True, r
    assert r["owned"] is False and r["killed_pids"] == [100, 101], r
    assert r["exit_code"] == 0, r
    args = cap[0][0][0]
    assert args[:2] == ["taskkill", "/IM"] and args[2] == "demo.exe", args


def test_force_no_toca_otra_variante(monkeypatch):
    # Alias "antigravity ide" con force usa su imagen exacta, nunca /PID.
    monkeypatch.setattr(AA, "_snapshot", lambda exes: snap_of())
    cap = []
    monkeypatch.setattr(AA.subprocess, "run", _fake_run(0, capture=cap))
    r = run(AA.apps_close({"app": "antigravity ide", "force": True}, _ctx()))
    assert r["status"] == "ok" and r["owned"] is False, r
    args = cap[0][0][0]
    assert "/IM" in args and "Antigravity IDE.exe" in args, args
    assert "/PID" not in args, args


def test_alias_con_espacio_mismo_canon(monkeypatch):
    fast(monkeypatch)
    after = {777: {"name": "Antigravity IDE.exe", "ppid": 999,
                   "created": "t"}}
    monkeypatch.setattr(AA, "_snapshot", lambda exes: snap_of())
    monkeypatch.setattr(AA.subprocess, "Popen",
                        lambda *a, **k: types.SimpleNamespace(pid=999))
    monkeypatch.setattr(AA, "_pid_image",
                        lambda pid: "Antigravity IDE.exe"
                        if pid == 777 else None)
    monkeypatch.setattr(AA, "_settle",
                        (lambda exes, launcher: _ret(after)))
    ctx = _ctx()
    r = run(AA.apps_open({"app": "antigravity ide"}, ctx))
    assert r["owned"] is True and r["pids"] == [777], r
    monkeypatch.setattr(AA, "_pid_image", lambda pid: "Antigravity IDE.exe")
    cap = []
    monkeypatch.setattr(AA.subprocess, "run", _fake_run(0, capture=cap))
    r2 = run(AA.apps_close({"app": "antigravity"}, ctx))
    assert r2["status"] == "ok" and r2["owned"] is True, r2
    assert r2["killed_pids"] == [777], r2
    assert cap[0][0][0][2] == "777", cap


async def _ret(val):
    return val


def test_app_no_abierta_rechaza(monkeypatch):
    called = []
    monkeypatch.setattr(AA.subprocess, "run", _fake_run(0, capture=called))
    r = run(AA.apps_close({"app": "notepad"}, _ctx()))
    assert r["status"] == "error" and r["closed"] is False, r
    assert r["owned"] is False and r["killed_pids"] == [], r
    assert "no la abri yo" in r["error"], r
    assert called == []


def test_propio_ya_cerrado_no_toca_so(monkeypatch):
    called = []
    monkeypatch.setattr(AA, "_pid_image", lambda pid: None)
    monkeypatch.setattr(AA.subprocess, "run", _fake_run(0, capture=called))
    ctx = _ctx(_owned={"demo": {"pids": [4242], "exe": "demo.exe",
                                "app": "demo"}})
    r = run(AA.apps_close({"app": "demo"}, ctx))
    assert r["status"] == "error" and r["closed"] is False, r
    assert r["owned"] is True and r["killed_pids"] == [], r
    assert "ya no esta" in r["error"], r
    assert called == []
