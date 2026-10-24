"""Agente del PC en Linux (Omarchy): lo que se puede probar sin tocar la pantalla del señor."""
import asyncio
import json
import os
import sys
import time

import pytest

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "voz"))
import actions_linux as L  # noqa: E402


WIN_HOME = "C:" + "\\" + "Users" + "\\X\\"   # ruta de ejemplo de Windows (montada para no parecer un dato real)


@pytest.mark.parametrize("win,linux", [
    (WIN_HOME + "Documents\\jarvis-juego.txt", os.path.expanduser("~/Documents/jarvis-juego.txt")),
    (WIN_HOME + "OneDrive\\Documents\\a.txt", os.path.expanduser("~/Documents/a.txt")),
    ("/home/y/b.txt", "/home/y/b.txt")])
def test_rutas_de_windows(win, linux):
    assert L.linux_path(win) == linux


@pytest.mark.parametrize("linea,cmd0", [("steam://rungameid/252950|cuenta2", ["steam", "steam://rungameid/252950"]),
                                        ("epic:instalar:fortnite", ["heroic"]), ("https://x.com", ["xdg-open", "https://x.com"]),
                                        ("rm -rf /", [])])
def test_ordenes_de_juego(linea, cmd0):
    assert L._launch_line(linea) == cmd0


def test_clic_fuera_de_pantalla_no_hace_nada(monkeypatch):
    monkeypatch.setattr(L, "_monitors", lambda: [{"name": "DP-1", "x": 0, "y": 0, "width": 1920, "height": 1080}])
    hecho = []
    monkeypatch.setattr(L, "_run", lambda cmd, t=10: hecho.append(cmd))
    r = asyncio.run(L.ui_click({"x": 5000, "y": 10}, {}))
    assert r["code"] == "out_of_bounds" and not hecho


@pytest.mark.parametrize("llega", [True, False])
def test_clic_solo_si_el_raton_llega_exacto(monkeypatch, llega):
    mons = [{"name": "DP-1", "x": 0, "y": 0, "width": 1920, "height": 1080},
            {"name": "HDMI-A-1", "x": -1920, "y": 0, "width": 1920, "height": 1080}]
    monkeypatch.setattr(L, "_monitors", lambda: mons)
    monkeypatch.setattr(L.shutil, "which", lambda x: "/usr/bin/" + x)
    pedido, clics = [], []
    monkeypatch.setattr(L, "mover_cursor", lambda x, y, m=None: pedido.append((x, y)) or llega)
    monkeypatch.setattr(L, "_run", lambda cmd, t=10: clics.append(cmd) or type("R", (), {"returncode": 0, "stderr": ""})())
    r = asyncio.run(L.ui_click({"x": -1500, "y": 800}, {}))
    assert pedido == [(-1500, 800)]
    assert (r["status"] == "ok") == llega
    assert bool([c for c in clics if c[:2] == ["ydotool", "click"]]) == llega     # sin llegar exacto, no hay clic


def test_ruta_en_l_cruza_por_la_franja_comun(monkeypatch):
    mons = [{"name": "DP-1", "x": 0, "y": 0, "width": 1920, "height": 1080},
            {"name": "HDMI-A-1", "x": -1920, "y": 250, "width": 1920, "height": 1080}]
    pos = {"c": (500, 100)}
    tramos = []
    monkeypatch.setattr(L, "_cursor", lambda: pos["c"])
    monkeypatch.setattr(L, "_ir", lambda x, y, n=30: tramos.append((x, y)) or pos.update(c=(x, y)) or True)
    assert L.mover_cursor(-1000, 900, mons)
    assert tramos[0] == (500, 260) and tramos[1][0] < 0 and tramos[-1] == (-1000, 900)   # baja a la franja, cruza, llega


def test_mandar_archivo_solo_de_sus_carpetas(tmp_path):
    p = tmp_path / "secreto.txt"
    p.write_text("x")
    assert asyncio.run(L.files_send({"path": str(p)}, {}))["code"] == "bad_path"
    assert asyncio.run(L.files_send({"path": os.path.expanduser("~/.ssh/id_ed25519")}, {}))["code"] == "bad_path"


def test_ultimo_archivo_no_sale_de_sus_carpetas():
    assert asyncio.run(L.files_latest({"dir": "../.ssh"}, {}))["code"] == "bad_path"


def test_tiempo_de_juego(tmp_path, monkeypatch):
    log = tmp_path / "juego.jsonl"
    ahora = time.time()
    log.write_text("\n".join(json.dumps(e) for e in [{"ini": ahora - 7200, "fin": ahora - 3600, "juego": "Rocket League"},
                                                      {"ini": ahora - 20 * 86400, "fin": ahora - 20 * 86400 + 600, "juego": "Viejo"}]))
    monkeypatch.setattr(L, "JUEGO_LOG", log)
    r = asyncio.run(L.games_time({"dias": 7}, {}))
    assert r["minutos"] == 60 and r["juegos"][0]["juego"] == "Rocket League"


def test_teclas_formato_windows(monkeypatch):
    hecho = []
    monkeypatch.setattr(L, "_run", lambda cmd, t=10: hecho.append(cmd) or type("R", (), {"returncode": 0, "stderr": ""})())
    asyncio.run(L.ui_keypress({"keys": "ctrl+v"}, {}))
    assert hecho[-1] == ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"]
    assert asyncio.run(L.ui_keypress({"keys": "hyper+x"}, {}))["code"] == "bad_modifier"


@pytest.mark.parametrize("oido,orden", [("Para.", "para"), ("Jarvis, cállate", "para"), ("¿Qué has dicho?", "repite"),
                                        ("para la música", None), ("pon música", None)])
def test_control_de_la_voz(oido, orden, tmp_path, monkeypatch):
    sys.argv = ["x"]
    import jarvis_voz as J
    monkeypatch.setattr(J, "RITMO_FILE", str(tmp_path / "ritmo.txt"))
    assert J.control_voz(oido) == orden
