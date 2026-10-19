"""Fase 6 PC: files.write respeta allowed_roots (guard real de files_write).

OK dentro de JARVIS-recibidos; DENEGADO en C:\\Windows y con ".." que escapa.
Usa tmp_path como raiz (no toca disco fuera del tmp).
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions_files as F


def run(coro):
    return asyncio.run(coro)


def _ctx(root):
    return {"roots": [str(root)], "apps": {}, "commands": [],
            "output_max": 65536, "files_ext": "0", "trash_dir": "_jarvis_trash"}


def test_write_dentro_de_raiz_ok(tmp_path):
    ctx = _ctx(tmp_path)
    target = str(tmp_path / "JARVIS-recibidos" / "nota.txt")
    r = run(F.files_write({"path": target, "content": "hola pc"}, ctx))
    assert r.get("status") == "ok", r
    assert (tmp_path / "JARVIS-recibidos" / "nota.txt").read_text(
        encoding="utf-8") == "hola pc"


def test_write_fuera_de_raiz_denegado(tmp_path):
    ctx = _ctx(tmp_path)
    r = run(F.files_write({"path": r"C:\Windows\jarvis_bad.txt",
                           "content": "x"}, ctx))
    assert r.get("status") == "error" and r.get("code") == "outside_roots", r


def test_write_con_puntos_que_escapa_denegado(tmp_path):
    ctx = _ctx(tmp_path / "JARVIS-recibidos")
    (tmp_path / "JARVIS-recibidos").mkdir()
    evil = str(tmp_path / "JARVIS-recibidos" / ".." / "fuera.txt")
    r = run(F.files_write({"path": evil, "content": "x"}, ctx))
    assert r.get("status") == "error" and r.get("code") == "outside_roots", r
    assert not (tmp_path / "fuera.txt").exists()
