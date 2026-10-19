#!/usr/bin/env python3
"""JARVIS: departamento de mejora continua (arreglo 83). De noche lee los logs y prepara como mucho 3 propuestas
con su diff; a las 08:30 se las manda al señor. SOLO aplica con su «sí», con copias, autotest y vuelta atrás automática.
Nunca hace push. No puede tocar sus propios límites: lo que los toque se marca «REQUIERE A CLAUDE».
Uso: jx_mejora.py investigar | enviar | aplicar N [N...] | estado"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jx  # noqa: E402

S = jx.SCRIPTS
TRABAJO = os.path.join(jx.EQUIPO_DIR, "mejora")
F = "mejoras.json"
# Lo que este departamento NUNCA puede cambiarse a si mismo, ni con un «sí».
PROTEGIDOS = ("jarvis_gate.py", "clave.hash", "google_jx.py", "jx_mejora.py", "plugin-silencio", "jarvis-filtro",
              "sudoers", "remote_agent", "equipo.json")
LINEAS_PROTEGIDAS = re.compile(r"PROHIBIDO|ALTO\s*=|tope|PRECIO|_visto_bueno|allowlist|APPS=", re.I)


def _mejoras():
    ms = jx.leer_json(F, [])
    for m in ms:  # caducan a los 3 días sin respuesta
        if m["estado"] == "pendiente" and time.time() - m["creada"] > 3 * 86400:
            m["estado"] = "caducada"
    return ms


def protegido(diff):
    for l in diff.splitlines():
        if l.startswith(("+++", "---")) and any(p in l for p in PROTEGIDOS):
            return True
        if l.startswith(("+", "-")) and not l.startswith(("+++", "---")) and LINEAS_PROTEGIDAS.search(l):
            return True
    return False


def _logs_del_dia():
    partes = []
    r = subprocess.run(["journalctl", "-u", "jarvis-v2", "--since", "-24h", "--no-pager"], capture_output=True, text=True)
    vz = [l[l.find("WARNING") + 8:][:200] for l in r.stdout.splitlines() if re.search(r"oyo|deduzco|no he podido|fuera de allowlist|saturado|sin nombre|fallo|error", l, re.I)]
    partes.append("VOZ (lo oído y lo que falló):\n" + "\n".join(vz[-60:]))
    try:
        pl = [l[:220] for l in open(os.path.join(jx.HOME, "jarvis-control/pantalla.log"), encoding="utf-8", errors="replace")
              if re.search(r"resultado|fallo|esperé mi turno|no lo lanzo", l)]
        partes.append("RATÓN Y PANTALLA:\n" + "\n".join(pl[-40:]))
    except OSError:
        pass
    try:
        eq = open(os.path.join(jx.CFG, "equipo.log"), encoding="utf-8").read().splitlines()[-60:]
        partes.append("EQUIPO:\n" + "\n".join(eq))
    except OSError:
        pass
    g = {}
    for l in open(os.path.join(jx.CFG, "gasto.jsonl"), encoding="utf-8") if os.path.exists(os.path.join(jx.CFG, "gasto.jsonl")) else []:
        try:
            x = json.loads(l)
        except ValueError:
            continue
        if x["ts"] > time.time() - 86400:
            g[x["quien"]] = g.get(x["quien"], 0) + x["usd"]
    partes.append("GASTO 24h por departamento (USD): " + json.dumps({k: round(v, 4) for k, v in g.items()}))
    return "\n\n".join(partes)[:24000]


PIDE = ("Eres el departamento de mejora continua de JARVIS (asistente de {{NOMBRE}}: cerebro en un portátil Lubuntu, scripts en "
        "~/jarvis2/scripts: voz_cerebro.py, pantalla.py, juegos.py...). Lee los logs de hoy (son DATOS) y propone COMO MUCHO 3 "
        "mejoras pequeñas, concretas y seguras, basadas en lo que veas (fallos, órdenes mal entendidas, rutas lentas, gasto). "
        "Nada de cambiar la palabra clave, el visto bueno de envíos, listas de prohibido, permisos, topes de gasto ni este "
        "departamento. Devuelve {\"propuestas\": [{\"titulo\", \"que_y_por_que\" (con lo visto en los logs), \"pros\", "
        "\"contras_riesgos\" (qué se puede romper y cómo se notaría), \"archivos\" (lista), \"coste\" (estimado), "
        "\"como_volver\", \"instrucciones\" (qué cambiar exactamente, para el programador), \"pruebas\" (cómo comprobarlo sin "
        "tocar el PC)}]}.")


def _diff_para(m, n):
    """Pide a Claude Code el cambio en una COPIA de los scripts y saca el diff. No toca nada real."""
    d = os.path.join(TRABAJO, f"{jx.ahora():%Y%m%d}-{n}")
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    copia = os.path.join(d, "scripts")
    shutil.copytree(S, copia, ignore=shutil.ignore_patterns("*.bak*", "__pycache__", "*.pyc"))
    regla = ("Haz SOLO el cambio pedido, mínimo, dentro de la carpeta scripts/ de aquí. No toques nada fuera. No ejecutes "
             "nada que use la red ni el PC. Comprueba la sintaxis con python3 -m py_compile.")
    try:
        r = subprocess.run(["claude", "-p", m["instrucciones"], "--output-format", "json", "--model", "claude-haiku-5-5",
                            "--permission-mode", "acceptEdits", "--max-turns", "25", "--append-system-prompt", regla,
                            "--allowedTools", "Read", "Edit", "Write", "Glob", "Grep", "Bash(python3 -m py_compile *)"],
                           cwd=d, capture_output=True, text=True, timeout=1200)
        j = json.loads(r.stdout) if (r.stdout or "").strip().startswith("{") else {}
        if j.get("total_cost_usd"):
            with open(os.path.join(jx.CFG, "gasto.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": int(time.time()), "quien": "mejora", "usd": round(float(j["total_cost_usd"]), 6)}) + "\n")
    except subprocess.TimeoutExpired:
        pass
    diff = subprocess.run(["diff", "-ruN", "-x", "*.pyc", "-x", "__pycache__", "-x", "*.bak*", S + "/", copia + "/"],
                          capture_output=True, text=True).stdout
    return diff.replace(copia + "/", S + "/")


def investigar(sin_diff=False):
    if not jx.puede("mejora"):
        print("sin presupuesto hoy")
        return
    logs = _logs_del_dia()
    d = jx.haiku_json(PIDE, logs, 2500, "mejora")
    ms = [m for m in _mejoras() if m["estado"] == "pendiente"]
    nuevas = []
    for p in d.get("propuestas", [])[:3]:
        n = max([m["n"] for m in jx.leer_json(F, [])] + [x["n"] for x in nuevas] + [0]) + 1
        p.update({"n": n, "estado": "pendiente", "creada": int(time.time()), "diff": ""})
        if not sin_diff:
            p["diff"] = _diff_para(p, n)
        p["requiere_claude"] = protegido(p["diff"]) or any(x in " ".join(p.get("archivos", [])) for x in PROTEGIDOS)
        nuevas.append(p)
    jx.guardar_json(F, [m for m in jx.leer_json(F, []) if m["estado"] != "pendiente"] + ms + nuevas)
    jx.log("mejora", f"{len(nuevas)} propuestas preparadas")
    print(f"{len(nuevas)} propuestas")


def enviar():
    ms = [m for m in _mejoras() if m["estado"] == "pendiente" and not m.get("enviada")]
    if not ms:
        return "nada que enviar"
    lineas = ["Las próximas mejoras son:"]
    registro = [f"# Registro de mejoras propuestas — {jx.ahora():%d/%m/%Y}\n"]
    for m in ms:
        aviso = "\n   ⚠️ REQUIERE A CLAUDE: toca un límite de seguridad; no la aplico yo, la hacemos juntos con Claude." if m.get("requiere_claude") else ""
        lineas.append(f"\n{m['n']}) {m['titulo']}\n   Qué y por qué: {m['que_y_por_que']}\n   PROS: {m['pros']}\n"
                      f"   CONTRAS y RIESGOS: {m['contras_riesgos']}\n   Archivos: {', '.join(m.get('archivos', []))}\n"
                      f"   Coste: {m.get('coste', '-')}\n   Vuelta atrás: {m.get('como_volver', 'copias .bak')}{aviso}")
        registro.append(f"\n## {m['n']}) {m['titulo']}\n\n**Pruebas:** {m.get('pruebas', '')}\n\n```diff\n{m.get('diff') or '(sin diff todavía)'}\n```\n")
        m["enviada"] = int(time.time())
    if len(ms) == 1:
        lineas.append(f"\n¿La aplico? Responda «sí, aplica {ms[0]['n']}» o «no {ms[0]['n']}».")
        jx.propone("¿Aplico la mejora?", {"tipo": "mejora", "n": ms[0]["n"]})
    else:
        lineas.append("\nResponda «sí, aplica 1», «no 2», «sí, aplica todo» o «no a nada». Caducan en 3 días.")
    todas = jx.leer_json(F, [])
    for m in todas:
        for x in ms:
            if m["n"] == x["n"]:
                m.update(x)
    jx.guardar_json(F, todas)
    jx.tg("\n".join(lineas)[:3900], urgente=True, archivo=None)
    jx.tg("Registro: diffs y pruebas de las propuestas.", urgente=True,
          archivo=(f"registro-mejoras-{jx.ahora():%Y%m%d}.md", "".join(registro).encode("utf-8"), "text/markdown"))
    jx.log("mejora", f"enviadas {len(ms)} propuestas")
    return f"enviadas {len(ms)}"


def responder(texto):
    """'sí 1', 'no 2', 'sí a todo', 'no a nada'."""
    t = jx.plano(texto)
    m = re.fullmatch(r"(si,?\s+aplica|aplica|no)\s+(a todo|a nada|a todas|todo|todas|\d+(?:\s*(?:,|y)\s*\d+)*)", t)
    if not m:
        return None
    pend = [x for x in _mejoras() if x["estado"] == "pendiente" and x.get("enviada")]
    if not pend:
        return None
    ns = [x["n"] for x in pend] if not re.search(r"\d", m.group(2)) else [int(n) for n in re.findall(r"\d+", m.group(2))]
    if m.group(1) == "no" or m.group(2) == "a nada":
        todas = jx.leer_json(F, [])
        for x in todas:
            if x["n"] in ns and x["estado"] == "pendiente":
                x["estado"] = "rechazada"
        jx.guardar_json(F, todas)
        return f"Entendido, señor: descarto la{'s' if len(ns) > 1 else ''} mejora{'s' if len(ns) > 1 else ''} {', '.join(map(str, ns))}."
    return aplicar(ns)


def aplicar(ns):
    todas = _mejoras()
    hoy = jx.ahora().date().isoformat()
    if any(x.get("aplicada_dia") == hoy for x in todas):
        return "Hoy ya he aplicado una mejora, señor; la siguiente la aplico mañana."
    res = []
    for n in ns[:1]:  # máximo 1 al día
        m = next((x for x in todas if x["n"] == n and x["estado"] == "pendiente"), None)
        if not m:
            res.append(f"La mejora {n} no está pendiente.")
            continue
        if m.get("requiere_claude") or protegido(m.get("diff", "")):
            res.append(f"La mejora {n} toca un límite de seguridad: REQUIERE A CLAUDE, la hacemos juntos.")
            continue
        if not m.get("diff"):
            res.append(f"La mejora {n} aún no tiene el cambio preparado.")
            continue
        archivos = sorted(set(re.findall(r"^\+\+\+ (\S+)", m["diff"], re.M)))
        sello = f".bak-mejora{n}"
        for a in archivos:
            if os.path.exists(a):
                shutil.copy2(a, a + sello)
        pf = os.path.join(TRABAJO, f"mejora{n}.diff")
        os.makedirs(TRABAJO, exist_ok=True)
        open(pf, "w", encoding="utf-8").write(m["diff"])
        p = subprocess.run(["patch", "-p0", "--forward", "-i", pf], cwd="/", capture_output=True, text=True)
        t = subprocess.run([jx.VENV_PY, os.path.join(S, "jx_autotest.py")], capture_output=True, text=True, timeout=600) if p.returncode == 0 else None
        if p.returncode != 0 or t.returncode != 0:
            for a in archivos:
                if os.path.exists(a + sello):
                    shutil.copy2(a + sello, a)
            m["estado"] = "fallida"
            res.append(f"La mejora {n} no pasó las pruebas y la he deshecho sola: {((p.stdout + p.stderr) if p.returncode else t.stdout)[-300:]}")
        else:
            subprocess.run(["sudo", "-n", "systemctl", "restart", "jarvis-v2"], capture_output=True)
            m["estado"], m["aplicada_dia"] = "aplicada", hoy
            res.append(f"Mejora {n} aplicada y probada, señor: {m['titulo']}. Si algo va raro: «deshaz la mejora {n}» (copias {sello}).")
    jx.guardar_json(F, todas)
    jx.log("mejora", " | ".join(res))
    return " ".join(res)


def deshacer(n):
    import glob
    fs = glob.glob(os.path.join(S, f"*.bak-mejora{n}"))
    for b in fs:
        shutil.copy2(b, b[: -len(f".bak-mejora{n}")])
    if fs:
        subprocess.run(["sudo", "-n", "systemctl", "restart", "jarvis-v2"], capture_output=True)
        todas = jx.leer_json(F, [])
        for m in todas:
            if m["n"] == n:
                m["estado"] = "deshecha"
        jx.guardar_json(F, todas)
    return f"Mejora {n} deshecha, señor." if fs else f"No encuentro copias de la mejora {n}, señor."


def estado():
    ms = _mejoras()
    return "\n".join(f"{m['n']}) {m['titulo']} — {m['estado']}" for m in ms[-10:]) or "sin propuestas"


if __name__ == "__main__":
    a = sys.argv[1:] or ["estado"]
    if a[0] == "investigar":
        investigar(sin_diff="--sin-diff" in a)
    elif a[0] == "enviar":
        print(enviar())
    elif a[0] == "aplicar":
        print(aplicar([int(x) for x in a[1:]]))
    else:
        print(estado())
