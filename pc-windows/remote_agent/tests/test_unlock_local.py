"""Desbloqueo LOCAL de emergencia: scripts/unlock_local.py.

Sin red ni reinicio: el agente lee killswitch.json en CADA decision
MEDIUM/HIGH, asi que pasar el fichero a desbloqueado restaura la
operativa con el MISMO ctx (sin reconstruir nada).
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import killswitch as KS
import unlock_local as UL
from agent import execute_action, _is_locked
from audit import AuditLog

SECRET = "testsecret-solo-para-tests"


def run(coro):
    return asyncio.run(coro)


async def _fake_ok(params, ctx):
    return {"status": "ok", "mock": True}


MED = {"name": "files.write", "params": {"path": "x", "content": "y"},
       "risk": "medium", "timeout": 5, "module": "test",
       "scope": "files", "fn": _fake_ok}
LOW = {"name": "system.info", "params": {}, "risk": "low",
       "timeout": 5, "module": "test", "scope": "", "fn": _fake_ok}


def _ctx(kf):
    return {"roots": [], "apps": {}, "commands": [],
            "high_max_per_minute": 1000, "high_max_per_hour": 10000,
            "_high_ts": [], "kill_file": kf}


def test_bloqueado_unlock_sin_reinicio_restaura_medium(tmp_path, monkeypatch):
    """El caso exigido: bloqueado -> unlock_local -> MEDIUM funciona con
    el MISMO ctx (sin reiniciar ni reconstruir)."""
    kf = tmp_path / "killswitch.json"
    monkeypatch.setattr(UL, "KILL_FILE", kf)
    monkeypatch.setattr(UL, "LOCAL_LOG", tmp_path / "killswitch_local.log")
    log = AuditLog(tmp_path / "audit.jsonl", side="agent")
    ctx = _ctx(str(kf))  # un solo ctx en toda la prueba (= sin reinicio)
    ctx["roots"] = [str(tmp_path)]  # files.write dentro de allowed_roots
    target = {"path": str(tmp_path / "memo.txt"), "content": "hola"}
    used = set()

    KS.set_locked(str(kf), True, "t-lock")
    assert _is_locked(ctx) is True
    rm = run(execute_action(MED, target, None,
                            ctx, SECRET, used, log=log, trace_id="t-u-m1"))
    assert rm["status"] == "error" and "kill-switch" in rm["error"], rm

    assert UL.main(["--yes"]) == 0  # desbloqueo local, sin prompt

    assert _is_locked(ctx) is False  # mismo ctx, sin reinicio
    rm2 = run(execute_action(MED, target, None,
                             ctx, SECRET, used, log=log, trace_id="t-u-m2"))
    assert rm2.get("status") == "ok", rm2
    assert log.verify()[0]


def test_unlock_registra_en_log_aparte_y_no_toca_audit(tmp_path, monkeypatch):
    kf = tmp_path / "killswitch.json"
    ll = tmp_path / "killswitch_local.log"
    monkeypatch.setattr(UL, "KILL_FILE", kf)
    monkeypatch.setattr(UL, "LOCAL_LOG", ll)
    KS.set_locked(str(kf), True, "t-lock")
    assert UL.main(["--yes"]) == 0
    assert KS.is_locked(str(kf)) is False
    txt = ll.read_text(encoding="utf-8")
    assert "unlock-local" in txt and "locked_before=True" in txt, txt
    # audit.jsonl ni siquiera se crea en el directorio del desbloqueo
    assert not (tmp_path / "audit.jsonl").exists()
    assert "audit" not in txt


def test_unlock_ya_desbloqueado_no_hace_nada(tmp_path, monkeypatch):
    kf = tmp_path / "killswitch.json"
    ll = tmp_path / "killswitch_local.log"
    monkeypatch.setattr(UL, "KILL_FILE", kf)
    monkeypatch.setattr(UL, "LOCAL_LOG", ll)
    assert UL.main(["--yes"]) == 0
    assert not ll.exists()  # sin bloqueo no hay nada que registrar


def test_confirmacion_en_consola(tmp_path, monkeypatch):
    kf = tmp_path / "killswitch.json"
    monkeypatch.setattr(UL, "KILL_FILE", kf)
    monkeypatch.setattr(UL, "LOCAL_LOG", tmp_path / "killswitch_local.log")
    KS.set_locked(str(kf), True, "t-lock")
    monkeypatch.setattr("builtins.input", lambda *a, **k: "DESBLOQUEAR")
    assert UL.main([]) == 0
    assert KS.is_locked(str(kf)) is False
    KS.set_locked(str(kf), True, "t-relock")
    monkeypatch.setattr("builtins.input", lambda *a, **k: "no")
    assert UL.main([]) == 1
    assert KS.is_locked(str(kf)) is True  # palabra mal -> sigue bloqueado
