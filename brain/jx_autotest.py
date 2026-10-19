#!/usr/bin/env python3
"""JARVIS: autotest nocturno (mejora 8). No toca el PC ni manda nada. Sale con 1 si algo falla."""
import glob
import json
import os
import py_compile
import subprocess
import sys

HOME = os.path.expanduser("~")
S = os.path.join(HOME, "jarvis2/scripts")
sys.path.insert(0, S)
fallos = []


def ok(nombre, cond, detalle=""):
    print(f"{'OK ' if cond else 'MAL'} {nombre}{(' -> ' + str(detalle)[:120]) if not cond and detalle else ''}")
    if not cond:
        fallos.append(nombre)


for f in sorted(glob.glob(os.path.join(S, "*.py"))):
    try:
        py_compile.compile(f, doraise=True)
    except py_compile.PyCompileError as e:
        ok(f"compila {os.path.basename(f)}", False, e)
ok("compilan los scripts", not [x for x in fallos if x.startswith("compila")])
r = subprocess.run(["node", "--check", os.path.join(HOME, "jarvis-control/plugin-silencio/index.js")], capture_output=True)
ok("filtro index.js compila", r.returncode == 0, r.stderr)

try:
    import voz_cerebro as v
    v._POOL.submit = lambda *a, **k: None
    ok("_es_juego farmofobia", v._es_juego("farmofobia") == "Phasmophobia", v._es_juego("farmofobia"))
    ok("_es_juego spotify no es juego", v._es_juego("spotify") is None)
    ok("_pronuncia Phasmophobia", "Fasmofobia" in v._pronuncia("Abriendo Phasmophobia, señor."))
    ok("_pronuncia no toca frases normales", v._pronuncia("Son las cinco, señor.") == "Son las cinco, señor.")
except Exception as e:  # noqa: BLE001
    ok("voz_cerebro se importa", False, e)

try:
    import datetime as dt
    import jx
    base = dt.datetime(2026, 10, 19, 17, 0)
    c, _ = jx.cuando("recuérdame mañana a las 7 llamar", base)
    ok("fecha 'mañana a las 7'", c == dt.datetime(2026, 10, 20, 7, 0), c)
    c, _ = jx.cuando("en 20 minutos", base)
    ok("fecha 'en 20 minutos'", c == base + dt.timedelta(minutes=20), c)
    c, _ = jx.cuando("el lunes a las 9", base)
    ok("fecha 'el lunes a las 9'", c == dt.datetime(2026, 10, 26, 9, 0), c)
    ok("cuenta 3 por 7", jx._cuenta("cuánto es 3 por 7") == "Son 21, señor.", jx._cuenta("cuánto es 3 por 7"))
    ok("hora sin IA", (jx.local("qué hora es") or "").startswith("Son las"))
    ok("ayuda sin IA", "sé hacer" in (jx.local("/ayuda") or ""))
except Exception as e:  # noqa: BLE001
    ok("jx funciona", False, e)

try:
    r = subprocess.run(["/usr/bin/node", os.path.join(S, "filtro_puente.mjs"), os.path.join(HOME, "jarvis-control/plugin-silencio/index.js")],
                       input=json.dumps({"text": "estado", "chatId": "", "messageId": ""}), capture_output=True, text=True, timeout=30)
    linea = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("JXR ")), "")
    ok("filtro contesta 'estado' sin IA", '"kind":"string"' in linea and "señor" in linea, linea or r.stderr[-120:])
except Exception as e:  # noqa: BLE001
    ok("filtro puente", False, e)

try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("jf", os.path.join(HOME, ".hermes/plugins/jarvis-filtro/__init__.py"))
    jf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jf)
    ok("la clave nunca va a una herramienta", (jf.guardia("terminal", {"command": "cat ~/jarvis-control/clave.hash"}) or {}).get("action") == "block")
    ok("computer_use bloqueado", (jf.guardia("computer_use", {}) or {}).get("action") == "block")
    ok("una palabra suelta no se toma por clave", not jf._gate("verify", "zzqxautotest"))
except Exception as e:  # noqa: BLE001
    ok("plugin jarvis-filtro", False, e)

print(f"\n{len(fallos)} fallo(s)" if fallos else "\nTodo bien.")
sys.exit(1 if fallos else 0)
