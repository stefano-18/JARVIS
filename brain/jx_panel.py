#!/usr/bin/env python3
"""JARVIS: panel de estado (solo red de casa). Cada parte con su semáforo, las habilidades y la actividad.

http://<portátil>:8790/?k=<clave>   (la clave está en ~/.config/jarvis/panel.key)
Solo responde a direcciones de casa (127.*, 192.168.*, 10.*, 172.16-31.*) y con la clave. Solo lee: no cambia nada.
"""
import html
import ipaddress
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jx  # noqa: E402

PUERTO = int(os.environ.get("JARVIS_PANEL_PORT", "8790"))
CLAVE_F = os.path.join(jx.CFG, "panel.key")
CACHE = {"t": 0.0, "pc": {}, "pc_t": 0.0}
LOCK = threading.Lock()


def clave():
    if not os.path.exists(CLAVE_F):
        with open(CLAVE_F, "w", encoding="utf-8") as f:
            f.write(secrets.token_urlsafe(18))
        os.chmod(CLAVE_F, 0o600)
    return open(CLAVE_F, encoding="utf-8").read().strip()


def _sh(cmd, t=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _activo(u, usuario=True):
    return _sh(["systemctl"] + (["--user"] if usuario else []) + ["is-active", u]) == "active"


def _ultima(u):
    v = _sh(["systemctl", "--user", "show", u, "-p", "LastTriggerUSec", "--value"])
    m = re.search(r"(\d\d:\d\d:\d\d)", v)
    return m.group(1)[:5] if m else ""


def _log_equipo(n=8):
    try:
        lineas = open(os.path.join(jx.CFG, "equipo.log"), encoding="utf-8").read().splitlines()[-300:]
    except OSError:
        return []
    out = []
    for ln in lineas:
        m = re.match(r"\d{4}-(\d\d)-(\d\d) (\d\d:\d\d):\d\d \[(\w+)\] (.+)", ln)
        if m and m.group(4) != "habilidades":
            out.append({"cuando": f"{m.group(2)}/{m.group(1)} {m.group(3)}", "quien": m.group(4), "que": m.group(5)[:140]})
    return out[-n:]


def _habilidades():
    """Del registro real: la ayuda de «¿qué sabes hacer?» (jx.AYUDA), una línea por grupo de habilidades."""
    grupos = []
    for ln in jx.AYUDA.splitlines():
        ln = ln.strip()
        if not ln.startswith("•"):
            continue
        txt = ln.lstrip("• ").strip()
        frases = re.findall(r"«([^»]+)»", txt)
        titulo = re.split(r"[:(«]", txt, 1)[0].strip().rstrip(",") or txt[:30]
        grupos.append({"titulo": titulo[:60], "texto": txt, "frases": frases})
    return grupos


def _pc():
    """Estado del PC a través del agente (cada 30 s como mucho: no carga el PC)."""
    if time.time() - CACHE["pc_t"] < 30:
        return CACHE["pc"]
    d = {"conectado": jx.agente_pc_conectado()}
    if d["conectado"]:
        try:
            import pc_do
            for k, accion, p in (("estado", "jarvis.status", {}), ("salud", "system.health", {}),
                                 ("musica", "music.now", {}), ("juego", "games.time", {"dias": 1})):
                r = pc_do.run(accion, p, timeout=60 if accion == "system.health" else 15)
                d[k] = r if isinstance(r, dict) and r.get("status") == "ok" else {}
        except Exception as e:  # noqa: BLE001
            d["error"] = str(e)[:80]
    CACHE.update(pc=d, pc_t=time.time())
    return d


def estado():
    with LOCK:
        if time.time() - CACHE["t"] < 4 and CACHE.get("d"):
            return CACHE["d"]
        pc = _pc()
        ps = (pc.get("estado") or {}).get("servicios", {})
        try:
            tg = json.load(open(os.path.expanduser("~/.hermes/gateway_state.json")))["platforms"]["telegram"]["state"]
        except Exception:  # noqa: BLE001
            tg = "?"
        vig = _sh(["journalctl", "--user", "-u", "jarvis-vigilante", "-n", "3", "--no-pager", "-o", "cat"]).splitlines()
        vig = next((v for v in reversed(vig) if ":" in v and ("bien" in v or "CA" in v)), "")
        try:
            import jx_obsidian as O
            o = O.estado()
        except Exception:  # noqa: BLE001
            o = {}
        voz_ok = ps.get("jarvis-voz") == "active"
        partes = [
            {"nombre": "Cerebro (voz)", "ok": _activo("jarvis-v2", False), "detalle": "servidor de voz en el portátil"},
            {"nombre": "Telegram", "ok": _activo("hermes-gateway") and tg == "connected", "detalle": f"bot @Qovr_bot · {tg}"},
            {"nombre": "Agenda", "ok": _activo("jarvis-agenda"), "detalle": "recordatorios, resumen, copias"},
            {"nombre": "Vigilante", "ok": _activo("jarvis-vigilante.timer"),
             "detalle": (f"última ronda {_ultima('jarvis-vigilante.timer')}: " + vig.split(": ", 1)[-1][:90]) if vig else ""},
            {"nombre": "Agente del PC", "ok": bool(pc.get("conectado")), "detalle": "control de apps, ventanas, ratón y teclado"
             if pc.get("conectado") else "PC apagado o agente caído"},
            {"nombre": "Voz del PC", "ok": voz_ok, "detalle": "Hey/Ok/Jarvis · Ctrl+Alt+J" if voz_ok else "PC apagado o voz caída"},
            {"nombre": "Clips (30 s)", "ok": ps.get("jarvis-clip") == "active",
             "detalle": "Ctrl+Alt+G · último: " + ((pc.get("estado") or {}).get("ultimo_clip") or "ninguno")},
            {"nombre": "Avisos del PC", "ok": ps.get("jarvis-descargas.timer") == "active" and ps.get("jarvis-noche.timer") == "active",
             "detalle": "descargas, temperatura y resumen de las 8:30"},
            {"nombre": "Memoria Obsidian", "ok": bool(o.get("notas") is not None and os.path.isdir(o.get("vault", ""))),
             "detalle": f"{o.get('notas', '?')} notas · {o.get('secciones', '?')} secciones"},
            {"nombre": "Copias de seguridad", "ok": _activo("jarvis-backup.timer"), "detalle": f"última: {_ultima('jarvis-backup.timer') or '03:30'}"},
        ]
        try:
            import jx_skills as K
            compra = K.lista_compra()
        except Exception:  # noqa: BLE001
            compra = []
        rs = sorted(jx.recordatorios(), key=lambda r: r["ts"])
        sal = pc.get("salud") or {}
        d = {
            "hora": jx.ahora().strftime("%H:%M:%S"),
            "partes": partes,
            "gasto": round(jx.gastado(jx._inicio_dia()), 3),
            "tope": float(jx.equipo().get("tope_global_usd", 0.5)),
            "recordatorios": [{"cuando": time.strftime("%d/%m %H:%M", time.localtime(r["ts"])), "texto": r["texto"]} for r in rs[:8]],
            "compra": compra[:12],
            "pc": {"cpu": sal.get("cpu_temp"), "gpu": sal.get("gpu_temp"), "ram": sal.get("ram_uso"), "disco": sal.get("disco_libre_gb"),
                   "musica": ((pc.get("musica") or {}).get("titulo") or "") if (pc.get("musica") or {}).get("estado") == "Playing" else "",
                   "juego_min": (pc.get("juego") or {}).get("minutos"), "voz": (pc.get("estado") or {}).get("voz", [])},
            "ordenes": [o for o in reversed(jx.leer_json("actividad.json", [])) if o.get("canal") != "prueba"][:8],
            "equipo": list(reversed(_log_equipo())),
            "habilidades": _habilidades(),
            "agentes": agentes(),
            "roadmap": roadmap_panel(),
        }
        CACHE.update(t=time.time(), d=d)
        return d


# ---------------------------------------------------------------- agentes: ficha con «foto», qué hacen ahora y chat
AGENTES = [
    {"id": "mayordomo", "nombre": "JARVIS", "papel": "Mayordomo: atiende voz y Telegram y reparte", "icono": "🤵", "color": "#00b4ff",
     "ejemplos": ["qué tengo hoy", "busca cuándo sale GTA 6", "pon música de Queen"]},
    {"id": "investigador", "nombre": "Investigador", "papel": "Tareas largas de web; le manda el resultado a Telegram", "icono": "🔎",
     "color": "#7a5cff", "ejemplos": ["compara los 3 mejores ratones inalámbricos de menos de 60 €"]},
    {"id": "programador", "nombre": "Programador", "papel": "Tareas de código con Claude Code, sin publicar nada", "icono": "👨‍💻",
     "color": "#2fd27a", "ejemplos": ["haz un script que ordene mis descargas por tipo"]},
    {"id": "correo", "nombre": "Correo", "papel": "Lee y resume su Gmail; solo borradores, nunca envía", "icono": "✉️", "color": "#ff9f43",
     "ejemplos": ["tengo correos nuevos", "léeme el último correo", "revisa mi correo"]},
    {"id": "agenda", "nombre": "Agenda", "papel": "Calendario, recordatorios y temporizadores", "icono": "📅", "color": "#ffc400",
     "ejemplos": ["recuérdame mañana a las 9 llamar al médico", "qué tengo mañana", "pon un temporizador de 10 minutos"]},
    {"id": "pc", "nombre": "Agente del PC", "papel": "Apps, ventanas, ratón y teclado del PC", "icono": "🖥️", "color": "#00e6c3",
     "ejemplos": ["abre Steam", "cámbiame a Spotify", "haz clic en Librería en Steam"]},
    {"id": "memoria", "nombre": "Memoria", "papel": "Su Obsidian: apunta y busca en sus notas", "icono": "🧠", "color": "#ff5fa2",
     "ejemplos": ["apunta que el wifi de invitados está en la nevera", "busca en mis notas el coche"]},
    {"id": "tecnico", "nombre": "Técnico", "papel": "Vigilante, copias, autotest y registros", "icono": "🛠️", "color": "#8ea3c7",
     "ejemplos": ["estado", "cómo está el PC", "qué me he perdido"]},
    {"id": "mejora", "nombre": "Mejora continua", "papel": "Propone mejoras; solo aplica con su «sí»", "icono": "💡", "color": "#b8e986",
     "ejemplos": ["propón mejoras"]},
    {"id": "seguridad", "nombre": "Seguridad", "papel": "Audita el propio JARVIS y le manda un informe", "icono": "🛡️", "color": "#ff4d5e",
     "ejemplos": ["revisa la seguridad"]},
]
DEP = {"pc": "mayordomo", "memoria": "mayordomo", "correo": "correo_lee"}
PROC = {"investigador": r"jx_demanda\.py investigador", "programador": r"jx_demanda\.py programador|cc_tarea",
        "correo": r"jx_demanda\.py correo|jx_seguridad\.py.*correo", "pc": r"pantalla\.py", "tecnico": r"jx_seguridad\.py|jx_mejora|jx_autotest",
        "memoria": r"jx_obsidian"}
QUIEN = {"mayordomo": ("mayordomo",), "investigador": ("investigador",), "programador": ("programador",),
         "correo": ("correo_lee", "correo_avisa", "correo"), "agenda": ("agenda",), "pc": ("pantalla", "pc"),
         "memoria": ("memoria",), "tecnico": ("tecnico",), "mejora": ("mejora",), "seguridad": ("seguridad",)}


def _ultimo_de(quienes):
    for e in reversed(_log_equipo(300)):
        if e["quien"] in quienes:
            return f"{e['cuando']} · {e['que']}"
    return ""


def _chat(aid):
    return jx.leer_json(f"chat_{aid}.json", [])


def agentes():
    procs = _sh(["ps", "-eo", "args"])
    tareas = jx.leer_json("tareas.json", [])
    pc = CACHE.get("pc") or {}
    out = []
    for a in AGENTES:
        aid = a["id"]
        ahora, trabajando = "", False
        rx = PROC.get(aid)
        if rx:
            m = re.search(r"^.*(?:" + rx + r").*$", procs, re.M)
            if m:
                trabajando = True
                ahora = "Trabajando: " + re.sub(r"^.*?(jx_\w+\.py|pantalla\.py|cc_tarea\S*)\s*", "", m.group(0))[:90]
        if aid in ("investigador", "programador"):
            vivas = [t for t in tareas if t.get("dep") == aid and t.get("estado") not in ("entregada", "cancelada", "hecha")]
            if vivas and not ahora:
                ahora, trabajando = "En cola: " + vivas[-1]["que"][:80], True
        ultimo = _ultimo_de(QUIEN[aid])
        if aid == "mayordomo":
            act = [o for o in jx.leer_json("actividad.json", []) if o.get("canal") != "prueba"]
            if act:
                ultimo = f"{act[-1]['cuando']} · «{act[-1]['pidio']}» → {act[-1]['hizo'][:70]}"
        elif aid == "pc":
            voz = ((pc.get("estado") or {}).get("voz") or [])
            ultimo = ultimo or (voz[-1] if voz else "")
        elif aid == "agenda":
            rs = sorted(jx.recordatorios(), key=lambda r: r["ts"])
            if rs and not ahora:
                ahora = "Próximo: " + time.strftime("%d/%m %H:%M", time.localtime(rs[0]["ts"])) + " · " + rs[0]["texto"][:60]
        elif aid == "memoria":
            try:
                import jx_obsidian as O
                ahora = ahora or f"{O.estado().get('notas', 0)} notas en su Obsidian"
            except Exception:  # noqa: BLE001
                pass
        dep = (jx.equipo().get("departamentos") or {}).get(DEP.get(aid, aid), {})
        vivo = {"pc": bool(pc.get("conectado"))}.get(aid, dep.get("activo", True) and not jx.equipo().get("pausado"))
        if vivo and not ahora and dep.get("horario") and dep["horario"] != "00-24":
            ahora = f"En espera · trabaja a demanda (horario {dep['horario'].replace('-', ' a ')} h)"
        h = _chat(aid)
        out.append({**a, "vivo": bool(vivo), "trabajando": trabajando, "ahora": ahora or ("Disponible" if vivo else "Apagado"),
                    "ultimo": ultimo, "chat": h[-20:]})
    return out


def encarga(aid, texto):
    """Le da la tarea a ESE agente, por los mismos caminos que la voz y Telegram (el candado de lo delicado sigue igual)."""
    texto = (texto or "").strip()[:1000]
    if not texto:
        return "Dígame qué quiere, señor."
    try:
        import jx_skills as K
        if aid == "investigador":
            r = jx.demanda("investigador", texto)
        elif aid == "programador":
            r = jx.demanda("programador", texto)
        elif aid == "correo":
            r = jx.responde(texto, "panel") or (jx.demanda("correo") if re.search(r"revis|mira|lee", jx.plano(texto))
                                                else K.correos_nuevos("panel"))
        elif aid == "memoria":
            r = jx.responde(texto, "panel") or K.busca_notas(texto, texto)
        elif aid == "tecnico":
            r = jx.responde(texto, "panel") or jx.responde("estado", "panel")
        elif aid == "mejora":
            r = jx.responde(texto, "panel") or jx.demanda("mejoras")
        elif aid == "seguridad":
            r = jx.responde("revisa la seguridad", "panel") if re.search(r"revis|audit|segur|vulnera", jx.plano(texto)) \
                else (jx.responde(texto, "panel") or "Dígame «revisa la seguridad» y audito todo JARVIS, señor.")
        elif aid == "pc":
            r = jx.responde(texto, "panel")
            if not r:                       # algo de pantalla: el agente lo hace (con «señalar y confirmar» si está activo)
                subprocess.Popen([jx.VENV_PY, os.path.join(jx.SCRIPTS, "pantalla.py"), texto, "--pasos", "12"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                r = "En ello, señor. Si hay que pulsar algo, le señalo con el ratón y le pregunto antes."
        else:                               # mayordomo y agenda
            r = jx.responde(texto, "panel")
            if not r:
                r = jx.haiku("Eres JARVIS, el mayordomo de {{NOMBRE}}: español, le llamas señor, 1-3 frases. Si te piden hacer "
                             "algo en el PC o mandar algo, di que lo pida por voz o Telegram.", texto, 300, "mayordomo")
    except Exception as e:  # noqa: BLE001
        r = f"No he podido, señor ({str(e)[:80]})."
    h = _chat(aid)
    h += [{"de": "señor", "texto": texto, "cuando": jx.ahora().strftime("%H:%M")},
          {"de": aid, "texto": str(r), "cuando": jx.ahora().strftime("%H:%M")}]
    jx.guardar_json(f"chat_{aid}.json", h[-40:])
    return str(r)


def roadmap_panel():
    """«Por implementar»: la lista del señor (roadmap.json) + las propuestas pendientes de Mejora continua (mejoras.json)."""
    import jx_skills as K
    items = [dict(x) for x in K.roadmap()]
    for m in jx.leer_json("mejoras.json", []):
        if m.get("estado") == "pendiente":
            items.append({"id": f"m{m.get('n')}", "texto": (m.get("titulo") or m.get("que") or m.get("resumen") or "propuesta")[:160],
                          "estado": "propuesta", "origen": f"Mejora continua · diga «sí, aplica {m.get('n')}» o «no {m.get('n')}»",
                          "creado": time.strftime("%d/%m %H:%M", time.localtime(m.get("creada", time.time())))})
    orden = {"pendiente": 0, "propuesta": 1, "hecho": 2}
    return sorted(items, key=lambda x: (orden.get(x["estado"], 3), str(x.get("hecho_en", "")), str(x["id"])))


PAGINA = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "jx_panel.html"), encoding="utf-8").read() \
    if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "jx_panel.html")) else "<h1>Falta jx_panel.html</h1>"


def de_casa(ip):
    try:
        a = ipaddress.ip_address(ip)
        return a.is_private or a.is_loopback
    except ValueError:
        return False


class H(BaseHTTPRequestHandler):
    def _no(self, code=403):
        self.send_response(code)
        self.end_headers()

    def do_GET(self):
        if not de_casa(self.client_address[0]):
            return self._no()
        u = urlparse(self.path)
        if parse_qs(u.query).get("k", [""])[0] != clave():
            return self._no()
        if u.path == "/api/estado":
            try:
                body = json.dumps(estado(), ensure_ascii=False).encode()
            except Exception as e:  # noqa: BLE001
                body = json.dumps({"error": str(e)[:120]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
        elif u.path == "/cerebro":                  # mapa del cerebro (Graphify), lo manda el PC cada 15 min
            f = os.path.expanduser("~/jarvis2/graphify-out/graph.html")
            body = open(f, "rb").read() if os.path.exists(f) else \
                "<h2 style='font-family:sans-serif'>Aún no hay mapa: genérelo con Graphify en el PC.</h2>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif u.path == "/":
            body = PAGINA.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        else:
            return self._no(404)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        """Chat con un agente. Solo desde casa, con la clave y desde la propia página (cabecera X-Jarvis)."""
        if not de_casa(self.client_address[0]) or self.headers.get("X-Jarvis") != "panel":
            return self._no()
        u = urlparse(self.path)
        if u.path not in ("/api/chat", "/api/roadmap") or parse_qs(u.query).get("k", [""])[0] != clave():
            return self._no()
        if u.path == "/api/roadmap":
            import jx_skills as K
            n = min(int(self.headers.get("Content-Length", "0")), 4000)
            d = json.loads(self.rfile.read(n) or b"{}")
            if d.get("accion") == "add":
                r = K.rm_add(str(d.get("texto", "")), origen="panel")
            elif d.get("accion") == "hecho":
                r = K.rm_hecho(str(d.get("id", "")))
            else:
                return self._no(400)
            CACHE["t"] = 0
            body = json.dumps({"ok": bool(r)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        try:
            n = min(int(self.headers.get("Content-Length", "0")), 8000)
            d = json.loads(self.rfile.read(n) or b"{}")
            aid = str(d.get("agente", ""))
            if aid not in {a["id"] for a in AGENTES}:
                return self._no(400)
            r = encarga(aid, str(d.get("texto", "")))
            CACHE["t"] = 0                    # que la ficha se refresque ya
            body = json.dumps({"respuesta": r}, ensure_ascii=False).encode()
        except Exception as e:  # noqa: BLE001
            body = json.dumps({"respuesta": f"No he podido ({str(e)[:80]})."}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # sin ruido en el registro
        pass


if __name__ == "__main__":
    if sys.argv[1:] == ["--prueba"]:
        print(json.dumps(estado(), ensure_ascii=False, indent=1)[:3000])
        sys.exit(0)
    clave()
    ThreadingHTTPServer(("0.0.0.0", PUERTO), H).serve_forever()
