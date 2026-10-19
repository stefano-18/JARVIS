"""process.list/info: el parseo de tasklist debe tolerar "6,976 KB".

Regresion: "Mem Usage" como "6,976 KB" dejaba "6976B" tras los replace y
todo int() fallaba -> top=[] siempre y process.info siempre "pid no
encontrado". Mockeado, sin tocar el SO.
"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions_process as AP


def run(coro):
    return asyncio.run(coro)


SAMPLE = (
    '"System Idle Process","0","Services","0","8 KB"\n'
    '"System","4","Services","0","6,976 KB"\n'
    '"ApplicationFrameHost.exe","392","Console","1","42,412 KB"\n'
)


def _fake_run_factory(stdout):
    def _fake(*a, **k):
        return types.SimpleNamespace(stdout=stdout, returncode=0,
                                     stderr="")
    return _fake


def test_parse_kb_con_coma_y_sin_coma(monkeypatch):
    rows = AP._parse_tasklist(
        'Image Name,PID,Session Name,Session#,Mem Usage\n' + SAMPLE)
    assert len(rows) == 3, rows
    by_pid = {r["pid"]: r for r in rows}
    assert by_pid[0]["ram_kb"] == 8, rows
    assert by_pid[4]["ram_kb"] == 6976, rows
    assert by_pid[392]["ram_kb"] == 42412, rows
    assert by_pid[392]["name"] == "ApplicationFrameHost.exe", rows


def test_process_list_respeta_limit_y_ordena(monkeypatch):
    monkeypatch.setattr(AP.subprocess, "run", _fake_run_factory(SAMPLE))
    r = run(AP.process_list({"limit": 50}, {}))
    assert r["status"] == "ok", r
    assert [p["pid"] for p in r["top"]] == [392, 4, 0], r
    r2 = run(AP.process_list({"limit": 2}, {}))
    assert [p["pid"] for p in r2["top"]] == [392, 4], r2


def test_process_info_encuentra_uwp_y_rechaza_inexistente(monkeypatch):
    monkeypatch.setattr(AP.subprocess, "run", _fake_run_factory(SAMPLE))
    ok = run(AP.process_info({"pid": 392}, {}))
    assert ok["status"] == "ok", ok
    assert ok["process"]["name"] == "ApplicationFrameHost.exe", ok
    miss = run(AP.process_info({"pid": 999999}, {}))
    assert miss["status"] == "error" and miss["error"] == "pid no encontrado", miss
    assert miss["code"] == "pid_not_found", miss
    bad = run(AP.process_info({}, {}))
    assert bad["status"] == "error" and bad["error"] == "pid invalido", bad
    assert bad["code"] == "invalid_pid", bad
