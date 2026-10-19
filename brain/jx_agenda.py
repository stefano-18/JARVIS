#!/usr/bin/env python3
"""JARVIS: agenda y técnico (arreglos 76-77). Servicio de usuario jarvis-agenda. Hace SOLO tareas fijas y sin IA
autónoma: recordatorios y temporizadores (Telegram + voz del PC), avisos guardados en horas de silencio, resumen de la
mañana (calendario y número de correos sin leer, solo lectura), aviso de gasto y, de madrugada, copias verificadas,
rotación de logs, autotest y prueba de modelos de reserva. Nada sale a nadie salvo al propio chat del señor."""
import glob
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jx  # noqa: E402

HECHO = "hecho_hoy.json"


def tablon(dep, texto):
    os.makedirs(jx.EQUIPO_DIR, exist_ok=True)
    linea = f"- {jx.ahora():%d/%m %H:%M} **{dep}**: {texto}\n"
    for f in ("tablon.md", f"{dep}.md"):
        p = os.path.join(jx.EQUIPO_DIR, f)
        try:
            viejo = open(p, encoding="utf-8").read().splitlines(True)[-300:] if os.path.exists(p) else []
            open(p, "w", encoding="utf-8").write("".join(viejo) + linea)
        except OSError:
            pass
    jx.log(dep, texto)


def una_vez(clave):
    """True la primera vez que se pide hoy esta clave."""
    h = jx.leer_json(HECHO, {})
    hoy = f"{jx.ahora():%Y%m%d}"
    if h.get("_dia") != hoy:
        h = {"_dia": hoy}
    if h.get(clave):
        return False
    h[clave] = int(time.time())
    jx.guardar_json(HECHO, h)
    return True


def gjx(*args, timeout=90):
    py = os.path.join(jx.HOME, "jarvis-control/gvenv/bin/python")  # el entorno con las librerias de Google
    r = subprocess.run([py if os.path.exists(py) else jx.VENV_PY, os.path.join(jx.SCRIPTS, "google_jx.py"), *args], capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads((r.stdout or "").strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": (r.stderr or r.stdout or "")[-200:]}


# ------------------------------------------------------------------ agenda y contable
def recordatorios():
    for r in jx.vencidos():
        txt = f"⏰ Señor, le recuerdo: {r['texto']}"
        jx.tg(txt, urgente=True)  # lo pidió él: sale aunque sea hora de silencio
        if jx.pc_encendido():
            jx.decir(f"Señor, le recuerdo: {r['texto']}")
        tablon("agenda", f"recordatorio entregado: {r['texto'][:60]}")


def resumen_manana(forzar=False):
    if jx.leer_json("ajustes.json", {}).get("resumen") is False and not forzar:
        return None
    partes = [f"Buenos días, señor. Hoy es {jx.DIAS[jx.ahora().weekday()]} {jx.ahora().day} de {jx.MESES[jx.ahora().month - 1]}."]
    c = gjx("cal-list", "1")
    if c.get("ok"):
        hoy = jx.ahora().date().isoformat()
        ev = [e for e in c["eventos"] if e["inicio"].startswith(hoy)]
        partes.append("Agenda de hoy: " + ("; ".join(f"{e['inicio'][11:16] or 'todo el día'} {e['titulo']}" for e in ev) if ev else "nada."))
    else:
        partes.append("Agenda: no he podido leer el calendario.")
    m = gjx("mail-list", "is:unread in:inbox", "50")
    partes.append(f"Correos sin leer: {len(m['correos'])}{'+' if len(m['correos']) >= 50 else ''}." if m.get("ok") else "Correo: no he podido leerlo.")
    ayer = jx.gastado(jx._inicio_dia(1), jx._inicio_dia())
    partes.append(f"Gasto de ayer: {ayer:.3f} USD.")
    rs = [r for r in jx.recordatorios() if r["ts"] < jx._inicio_dia(-1)]
    if rs:
        partes.append(f"Recordatorios de hoy: {len(rs)}.")
    partes.append("(Para no recibirlo: «quita el resumen».)")
    txt = "\n".join(partes)
    jx.tg(txt, urgente=True)
    tablon("agenda", "resumen de la mañana enviado")
    return txt


def aviso_gasto():
    hoy = jx.gastado(jx._inicio_dia())
    lim = float(jx.conf().get("aviso_gasto_usd", 0.30))
    if hoy > lim and una_vez("aviso_gasto"):
        jx.tg(f"Señor, hoy el gasto ya va por {hoy:.2f} USD (aviso a partir de {lim:.2f}).")
        tablon("agenda", f"aviso de gasto {hoy:.2f}")


def copias():
    bdir = os.path.join(jx.HOME, "backups")
    tars = sorted(glob.glob(os.path.join(bdir, "*.tar.gz")) + glob.glob(os.path.join(bdir, "*.gpg")), key=os.path.getmtime)
    malos = []
    if tars:
        ult = [x for x in tars if x.endswith(".tar.gz")][-1:]
        for x in ult:
            if subprocess.run(["tar", "-tzf", x], capture_output=True).returncode != 0:
                malos.append(os.path.basename(x))
    papelera = os.path.join(jx.HOME, "papelera-jarvis", "backups")
    movidos = 0
    for pat in ("jarvis-2*.tar.gz", "jarvis-secretos-*.gpg", "jarvis-completo-*.tar.gz"):
        fs = sorted(glob.glob(os.path.join(bdir, pat)), key=os.path.getmtime)
        for x in fs[:-14]:
            os.makedirs(papelera, exist_ok=True)
            shutil.move(x, os.path.join(papelera, os.path.basename(x)))
            movidos += 1
    tablon("tecnico", f"copias: {len(tars)} revisadas, {movidos} viejas a la papelera" + (f", MAL: {malos}" if malos else ""))
    if malos:
        jx.tg(f"Señor, la copia de seguridad {malos[0]} no se puede leer. Lo reviso.", urgente=False)


def rota_logs():
    pats = [os.path.join(jx.HOME, "jarvis-control", "*.log"), os.path.join(jx.HOME, "jarvis-control", "audit*"),
            os.path.join(jx.HOME, "tareas", "**", "*.log"), os.path.join(jx.HOME, "jarvis2", "logs", "*.log"),
            os.path.join(jx.CFG, "equipo.log")]
    n = 0
    for p in pats:
        for f in glob.glob(p, recursive=True):
            if os.path.isfile(f) and not f.endswith(".gz") and os.path.getsize(f) > 5 * 1024 * 1024:
                for i in (2, 1):
                    if os.path.exists(f"{f}.{i}.gz"):
                        os.replace(f"{f}.{i}.gz", f"{f}.{i + 1}.gz")
                subprocess.run(["gzip", "-c", f], stdout=open(f + ".1.gz", "wb"))
                open(f, "w").close()
                n += 1
    gj = os.path.join(jx.CFG, "gasto.jsonl")
    if os.path.exists(gj) and os.path.getsize(gj) > 20 * 1024 * 1024:
        shutil.move(gj, gj + f".{jx.ahora():%Y%m}")
    tablon("tecnico", f"logs rotados: {n}")


def autotest():
    r = subprocess.run([jx.VENV_PY, os.path.join(jx.SCRIPTS, "jx_autotest.py")], capture_output=True, text=True, timeout=600)
    malo = r.returncode != 0
    tablon("tecnico", "autotest " + ("FALLA: " + (r.stdout or r.stderr)[-200:] if malo else "OK"))
    if malo:
        jx.tg("Señor, el autotest de esta noche ha fallado:\n" + (r.stdout or r.stderr)[-1500:])
    return not malo


def reservas():
    r = subprocess.run([jx.VENV_PY, os.path.join(jx.SCRIPTS, "jx_reservas.py")], capture_output=True, text=True, timeout=180)
    tablon("tecnico", "modelos de reserva: " + (r.stdout or r.stderr).strip()[-200:])


def entregas():
    """Entrega a su hora los encargos a demanda que ya están listos (arreglo 78)."""
    ts = jx.leer_json("tareas.json", [])
    cambio = False
    for t in ts:
        if t.get("estado") in ("lista", "fallida") and t.get("entrega", 0) and t["entrega"] <= time.time():
            out = os.path.join(jx.HOME, "tareas", t["nombre"], "RESULTADO.md")
            texto = open(out, encoding="utf-8").read() if os.path.exists(out) else "(sin resultado)"
            primeras = [l for l in texto.splitlines() if l.strip()][:3]
            jx.tg_informe(f"📋 Resultado de «{t['nombre']}»", texto, "\n".join(primeras))
            if jx.pc_encendido():
                jx.decir("Señor, le he mandado a Telegram el resultado de su encargo.")
            t["estado"] = "entregada"
            cambio = True
            tablon("agenda", f"entregado «{t['nombre']}»")
    if cambio:
        jx.guardar_json("tareas.json", ts)


# ------------------------------------------------------------------ bucle
def paso():
    n = jx.ahora()
    recordatorios()
    entregas()
    if int(jx.conf()["silencio_hasta"]) <= n.hour < int(jx.conf()["silencio_desde"]):
        k = jx.vacia_cola_silencio()
        if k:
            tablon("agenda", f"entregados {k} avisos guardados de la noche")
    if n.hour == 9 and una_vez("resumen"):
        resumen_manana()
    if 3 <= n.hour < 5:
        if una_vez("copias"):
            copias()
        if una_vez("logs"):
            rota_logs()
        if n.hour >= 4 and una_vez("autotest"):
            autotest()
        if una_vez("reservas"):
            reservas()
    aviso_gasto()


def main():
    tablon("agenda", "agenda en marcha")
    while True:
        try:
            paso()
        except Exception as e:  # noqa: BLE001
            jx.log("agenda", f"fallo en el bucle: {str(e)[:200]}")
        time.sleep(20)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        {"resumen": lambda: print(resumen_manana(forzar=True)), "copias": copias, "logs": rota_logs, "autotest": autotest,
         "reservas": reservas, "recordatorios": recordatorios}[sys.argv[1]]()
    else:
        main()
