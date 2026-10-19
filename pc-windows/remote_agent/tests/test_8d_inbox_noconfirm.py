"""Fase 8D PC: files.write en JARVIS-recibidos no pide confirmacion (LOW);
en Downloads/Documents sigue MEDIUM (= confirmacion). Rutas y audit igual.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions as ACT
import policy as _pol


def run(coro):
    return asyncio.run(coro)


def _ctx(inbox, downloads, docs):
    return {"roots": [str(inbox), str(downloads), str(docs)],
            "apps": {}, "commands": [],
            "output_max": 65536, "files_ext": "0", "trash_dir": "_jarvis_trash",
            "media_volume": "0", "session_grants": "0"}


async def _exec(path, content, ctx):
    from agent import execute_action
    manifest = dict(ACT.BY_NAME["files.write"])
    assert manifest["risk"] == "medium"
    return await execute_action(manifest, {"path": str(path), "content": content},
                                None, ctx, "secret-test", set())


def test_inbox_es_low_sin_confirmacion(tmp_path):
    inbox, dl, docs = (tmp_path / "JARVIS-recibidos",
                       tmp_path / "Downloads", tmp_path / "Documents")
    ctx = _ctx(inbox, dl, docs)
    assert _pol.is_inbox_path(str(inbox / "n.txt"), ctx["roots"])
    r = run(_exec(inbox / "nota.txt", "hola", ctx))
    assert r.get("status") == "ok", r
    assert r.get("_risk") == "low", r
    assert (inbox / "nota.txt").read_text(encoding="utf-8") == "hola"


def test_downloads_sigue_medium(tmp_path):
    inbox, dl, docs = (tmp_path / "JARVIS-recibidos",
                       tmp_path / "Downloads", tmp_path / "Documents")
    ctx = _ctx(inbox, dl, docs)
    assert not _pol.is_inbox_path(str(dl / "n.txt"), ctx["roots"])
    r = run(_exec(dl / "nota.txt", "hola", ctx))
    assert r.get("status") == "ok", r
    assert r.get("_risk") == "medium", r


def test_documents_sigue_medium(tmp_path):
    inbox, dl, docs = (tmp_path / "JARVIS-recibidos",
                       tmp_path / "Downloads", tmp_path / "Documents")
    ctx = _ctx(inbox, dl, docs)
    r = run(_exec(docs / "nota.txt", "hola", ctx))
    assert r.get("status") == "ok", r
    assert r.get("_risk") == "medium", r


def test_escape_con_puntos_no_es_inbox(tmp_path):
    inbox = tmp_path / "JARVIS-recibidos"
    inbox.mkdir()
    ctx = _ctx(inbox, tmp_path / "Downloads", tmp_path / "Documents")
    evil = str(inbox / ".." / "fuera.txt")
    assert not _pol.is_inbox_path(evil, ctx["roots"])
    r = run(_exec(evil, "x", ctx))
    assert r.get("_risk") == "medium", r
