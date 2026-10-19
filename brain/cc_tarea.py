#!/usr/bin/env python3
"""Lanza un trabajo largo de Claude Code en ~/tareas/<nombre> y avisa por Telegram al terminar.
Uso: cc_tarea.py <nombre> <haiku|sonnet> "<tarea>"  |  cc_tarea.py estado <nombre>  |  cc_tarea.py ver <nombre>"""
import importlib.util, json, os, re, subprocess, sys, time

HOME = os.path.expanduser("~")
CHAT = "{{CHAT_TELEGRAM}}"
MODELOS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"}
REGLAS = ("Trabajas solo, sin hacer preguntas: decide lo razonable y sigue. "
          "Todo el trabajo va dentro de esta carpeta; no toques nada fuera de ella. "
          "No uses sudo, no publiques nada en internet, no hagas pagos ni crees cuentas. "
          "Al terminar deja un README.md breve en español con qué has hecho y cómo abrirlo o probarlo.")
PERMITIDAS = ["Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch",
              "Bash(npm *)", "Bash(npx *)", "Bash(node *)", "Bash(python3 *)", "Bash(pip *)",
              "Bash(ls *)", "Bash(mkdir *)", "Bash(cat *)", "Bash(git *)"]


def telegram(texto):
    for g in ("{{HOME}}/jarvis-control/jarvis_gate.py", "{{HOME}}/jarvis2/scripts/jarvis_gate.py"):
        if os.path.exists(g):
            spec = importlib.util.spec_from_file_location("gate", g)
            m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
            return m._tg_send_message(CHAT, texto)


def carpeta(nombre):
    slug = re.sub(r"[^a-z0-9-]+", "-", nombre.lower()).strip("-")[:40] or "tarea"
    return os.path.join(HOME, "tareas", slug), slug


def estado(nombre):
    d, slug = carpeta(nombre)
    f = os.path.join(d, ".jarvis-estado")
    print(open(f).read().strip() if os.path.exists(f) else f"no existe la tarea {slug}")


def ver(nombre):
    d, slug = carpeta(nombre)
    if not os.path.isdir(d):
        print(f"no existe la tarea {slug}"); return
    subprocess.run(["pkill", "-f", "http.server 8080"], capture_output=True)
    subprocess.Popen(["python3", "-m", "http.server", "8080", "--bind", "0.0.0.0"], cwd=d,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    print("abrir en el navegador del PC: http://{{PORTATIL_IP}}:8080")


def lanzar(nombre, modelo, tarea):
    d, slug = carpeta(nombre)
    os.makedirs(d, exist_ok=True)
    st = os.path.join(d, ".jarvis-estado")
    open(st, "w").write(f"en curso desde {time.strftime('%H:%M')} con {modelo}")
    cmd = ["claude", "-p", tarea, "--output-format", "json", "--model", MODELOS.get(modelo, MODELOS["haiku"]),
           "--permission-mode", "acceptEdits", "--max-turns", "80", "--append-system-prompt", REGLAS,
           "--allowedTools", *PERMITIDAS]
    try:
        r = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=2 * 3600)
        open(os.path.join(d, ".jarvis-log.json"), "w").write(r.stdout or r.stderr)
        j = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
        res = (j.get("result") or "").strip().replace("\n", " ")
        coste = j.get("total_cost_usd")
        ok = r.returncode == 0 and not j.get("is_error")
    except subprocess.TimeoutExpired:
        ok, res, coste = False, "se pasó de 2 horas y lo he parado", None
    c = f" Coste: {coste:.2f} $." if isinstance(coste, (int, float)) else ""
    if ok:
        open(st, "w").write(f"terminada a las {time.strftime('%H:%M')}")
        telegram(f"Señor, he terminado «{slug}». {res[:400]}{c}")
    else:
        open(st, "w").write(f"fallida a las {time.strftime('%H:%M')}")
        telegram(f"Señor, no he podido terminar «{slug}». {res[:300]}{c}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in ("estado", "ver"):
        {"estado": estado, "ver": ver}[sys.argv[1]](sys.argv[2])
    elif len(sys.argv) == 4:
        lanzar(*sys.argv[1:])
    else:
        print(__doc__)
