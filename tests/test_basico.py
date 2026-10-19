#!/usr/bin/env python3
"""Pruebas que no necesitan el PC, ni claves, ni red (las usa GitHub Actions y se pueden lanzar a mano)."""
import datetime as dt
import glob
import os
import py_compile
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(R, "brain"))
fallos = []


def ok(nombre, cond, detalle=""):
    print(("OK  " if cond else "MAL ") + nombre + ("" if cond else f" -> {detalle}"))
    if not cond:
        fallos.append(nombre)


for f in glob.glob(os.path.join(R, "brain", "*.py")) + glob.glob(os.path.join(R, "hermes", "plugins", "*", "*.py")) + \
        glob.glob(os.path.join(R, "tools", "*.py")) + [os.path.join(R, "setup.py")]:
    try:
        py_compile.compile(f, doraise=True)
    except py_compile.PyCompileError as e:
        ok("compila " + os.path.relpath(f, R), False, e)
ok("compila todo el Python", not fallos)

os.environ.setdefault("HOME", "/tmp/jarvis-ci")
import jx  # noqa: E402

b = dt.datetime(2026, 10, 19, 17, 0)
ok("fecha 'mañana a las 7'", jx.cuando("mañana a las 7 llamar", b)[0] == dt.datetime(2026, 10, 20, 7, 0))
ok("fecha 'en 20 minutos'", jx.cuando("en 20 minutos", b)[0] == b + dt.timedelta(minutes=20))
ok("fecha 'el lunes a las 9'", jx.cuando("el lunes a las 9", b)[0] == dt.datetime(2026, 10, 26, 9, 0))
ok("fecha 'a las 18:30'", jx.cuando("a las 18:30", b)[0] == dt.datetime(2026, 10, 19, 18, 30))
ok("cuenta 3 por 7", jx._cuenta("cuánto es 3 por 7") == "Son 21, señor.")
ok("cuenta rechaza código", jx._cuenta("cuánto es __import__('os')") is None)
ok("ayuda sin IA", "sé hacer" in (jx.local("/ayuda") or ""))
ok("hora sin IA", (jx.local("qué hora es") or "").startswith("Son las"))
ok("«sí» fuerte para enviar", bool(jx.SI_FUERTE["enviar_borrador"].match("si, envia")) and not jx.SI_FUERTE["enviar_borrador"].match("si"))

print(f"\n{len(fallos)} fallo(s)" if fallos else "\nTodo bien.")
sys.exit(1 if fallos else 0)
