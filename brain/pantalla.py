#!/usr/bin/env python3
"""JARVIS mira la pantalla del PC y usa el raton y el teclado para conseguir un objetivo (arreglo 45).

Uso: pantalla.py "<objetivo>" [--pasos N] [--espera S]   |   pantalla.py --prueba
Cada paso: captura de pantalla -> Claude Haiku decide un clic, teclas o texto -> el agente del PC lo hace.
Nunca envia, publica, compra, borra ni desinstala nada, ni escribe contraseñas.
"""
import asyncio, base64, io, json, os, re, sys, time, urllib.request

HOME = os.path.expanduser("~")
VENV = os.path.join(HOME, "jarvis2/.venv/bin/python")
try:
    from PIL import Image
except ImportError:
    if os.path.exists(VENV) and os.path.realpath(sys.executable) != os.path.realpath(VENV):
        os.execv(VENV, [VENV] + sys.argv)
    raise

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pc_do  # noqa: E402

LOG = os.path.join(HOME, "jarvis-control/pantalla.log")
ANCHO = 1280  # arreglo 75: menos tokens por captura
PROHIBIDO = re.compile(r"\b(enviar|env[ií]a|send|publicar|publica|post|comprar|compra|buy|pagar|pay|checkout|apagar|apaga|reiniciar|reinicia|"
                       r"borrar|borra|eliminar|elimina|delete|desinstalar|uninstall|formatear|contrase[ñn]a|password)\b", re.I)
SISTEMA = (
    "Controlas el ratón y el teclado del PC Windows del señor mirando capturas de pantalla. Te doy un objetivo y la "
    "captura actual (y lo que ya hiciste). Responde SOLO un JSON, sin nada más, con UNA acción, o con varias seguidas si "
    "en ESTA imagen ya ves todos los pasos (por ejemplo marcar una opción y luego pulsar Jugar): "
    '{"acciones":[{...},{...}]} (máximo 4; nunca pongas hecho dentro de la lista). Acciones posibles:\n'
    '{"accion":"clic","x":N,"y":N,"doble":false,"que":"qué pulsas"}  (x,y en píxeles de ESTA imagen, centro del elemento)\n'
    '{"accion":"teclas","teclas":"enter"}  (una tecla o combinación: enter, esc, tab, ctrl+l, alt+f4 no, win)\n'
    '{"accion":"escribir","texto":"..."}  (escribe en el campo que ya tiene el foco)\n'
    '{"accion":"esperar"}  (si algo está cargando)\n'
    '{"accion":"hecho","resumen":"frase corta"}  (objetivo cumplido o ya estaba así)\n'
    '{"accion":"imposible","motivo":"frase corta"}\n'
    "Reglas: nunca pulses Enviar, Publicar, Comprar, Pagar, Borrar, Eliminar, Desinstalar ni confirmes nada de eso; "
    "nunca pulses Enter ni el botón de enviar en un chat, correo o red social (eso lo envía); nunca apagues, reinicies "
    "ni cierres la sesión; nunca escribas contraseñas ni datos personales; no cierres ventanas que no pide el objetivo. Si el objetivo exige "
    "algo de eso, responde imposible. Lee con cuidado los textos de la imagen y pulsa el elemento cuyo texto coincide con "
    "el objetivo (no el primero que veas); di en \"que\" el texto exacto que pulsas. No repitas un clic que no cambió nada: prueba otra cosa o responde imposible."
)
_SIS_CACHE = [{"type": "text", "text": SISTEMA, "cache_control": {"type": "ephemeral"}}]  # arreglo 75: se reutiliza en cada paso


def _log(t):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + t + "\n")
    except OSError:
        pass


def pc(accion, params, timeout=40):
    from remote import grants as G
    g = G.create_grant(pc_do.SECRET, accion, params)
    r = asyncio.run(pc_do._call(accion, params, grant=g, timeout=timeout))
    m = re.search(r"limite de acciones.*?espera (\d+) s", str((r or {}).get("error", "")))
    if m:
        _log(f"el agente pide esperar {m.group(1)} s")
        time.sleep(int(m.group(1)) + 1)
        g = G.create_grant(pc_do.SECRET, accion, params)
        r = asyncio.run(pc_do._call(accion, params, grant=g, timeout=timeout))
    if not isinstance(r, dict) or r.get("status") != "ok":
        raise RuntimeError(f"{accion}: {str((r or {}).get('error', r))[:160]}")
    return r


def _imagen(x):
    if isinstance(x, dict):
        for v in x.values():
            b = _imagen(v)
            if b:
                return b
    if isinstance(x, str) and len(x) > 5000:
        return x
    return None


def captura(zona=None):
    try:
        r = pc("screen.capture", {"format": "jpeg", "quality": 70})
    except RuntimeError:
        r = pc("screen.capture", {})
    b = _imagen(r)
    if not b:
        raise RuntimeError("la captura no trajo imagen")
    img = Image.open(io.BytesIO(base64.b64decode(b.split(",", 1)[-1]))).convert("RGB")
    if zona:
        img = img.crop((zona[0], zona[1], min(zona[2], img.size[0]), min(zona[3], img.size[1])))
    W, H = img.size
    esc = W / ANCHO if W > ANCHO else 1.0
    if esc != 1.0:
        img = img.resize((ANCHO, round(H / esc)))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=60)
    return base64.b64encode(out.getvalue()).decode(), esc, img.size


def _tope(pedido):
    try:
        import jx
        return jx.tope_tokens("pantalla", pedido)
    except Exception:  # noqa: BLE001
        return pedido


def haiku(objetivo, b64, tam, hechos):
    key = open(os.path.join(HOME, ".config/jarvis/anthropic.key"), encoding="utf-8").read().strip()
    txt = f"Objetivo: {objetivo}\nTamaño de la imagen: {tam[0]}x{tam[1]}\n"
    txt += ("Ya hiciste: " + " | ".join(hechos[-6:])) if hechos else "Es el primer paso."
    txt += "\nResponde SOLO con el JSON de una acción, empezando por { y sin texto antes ni después."
    body = json.dumps({"model": "claude-haiku-5-5", "max_tokens": _tope(400), "thinking": {"type": "disabled"}, "system": _SIS_CACHE, "messages": [
        {"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                                     {"type": "text", "text": txt}]}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", body,
                                 {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=40) as r:
        d = json.load(r)
        _gasto(d)
    out = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", out, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except ValueError:
            pass
    _log("sin JSON: " + out[:200].replace("\n", " "))
    return {"accion": "esperar"}


def escribir(texto):
    pc("clipboard.write", {"text": texto})
    pc("ui.keypress", {"keys": "ctrl+v"})


LAYOUT_F = os.path.join(HOME, ".config/jarvis/pantallas.json")
EVITAR = None




def _gasto(d):
    try:
        import jx
        jx.apunta_gasto(d.get("usage"), "mayordomo")
    except Exception:  # noqa: BLE001
        pass


def _img(mon):
    r = pc("screen.capture", {"format": "jpeg", "quality": 70} | ({} if mon is None else {"monitor": mon}))
    b = _imagen(r)
    if not b:
        raise RuntimeError("la captura no trajo imagen")
    return Image.open(io.BytesIO(base64.b64decode(b.split(",", 1)[-1]))).convert("RGB")


def _parecido(a, b):
    a, b = a.resize((96, 54)).convert("L"), b.resize((96, 54)).convert("L")
    return sum(abs(x - y) for x, y in zip(a.getdata(), b.getdata()))


def _layout():
    try:
        return json.load(open(LAYOUT_F, encoding="utf-8"))
    except (OSError, ValueError):
        pass
    d = {"origen": [0, 0], "mons": []}
    try:
        todo = _img(0)
        W, H = todo.size
        mons = []
        for n in (1, 2):
            m = _img(n)
            w, h = m.size
            if (w, h) == (W, H):
                break
            cands = [(x, y) for x in sorted({0, W - w}) for y in sorted({0, H - h})]
            x, y = min(cands, key=lambda c: _parecido(todo.crop((c[0], c[1], c[0] + w, c[1] + h)), m))
            mons.append({"n": n, "x": x, "y": y, "w": w, "h": h})
        if len(mons) == 2 and (mons[0]["x"], mons[0]["y"]) != (mons[1]["x"], mons[1]["y"]):
            d = {"origen": [-mons[0]["x"], -mons[0]["y"]], "mons": mons}
        d["total"] = [W, H]  # arreglo 91: para notar si vuelve o se va una pantalla
    except Exception as e:  # noqa: BLE001
        _log(f"pantallas: {str(e)[:120]}")
        return d
    try:
        os.makedirs(os.path.dirname(LAYOUT_F), exist_ok=True)
        json.dump(d, open(LAYOUT_F, "w", encoding="utf-8"))
    except OSError:
        pass
    _log(f"pantallas: {json.dumps(d)}")
    return d


def _vista(img, off):
    W, H = img.size
    esc = W / ANCHO if W > ANCHO else 1.0
    if esc != 1.0:
        img = img.resize((ANCHO, round(H / esc)))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=60)
    return {"b64": base64.b64encode(out.getvalue()).decode(), "esc": esc, "tam": img.size, "off": off}


def capturas(zona=None):
    lay = None if zona else _layout()
    if lay and lay.get("mons"):
        todo = _img(0)
        W = max(m["x"] + m["w"] for m in lay["mons"]); H = max(m["y"] + m["h"] for m in lay["mons"])
        if todo.size != (W, H):  # arreglo 91: las pantallas han cambiado -> colocación nueva
            _log(f"pantallas cambiadas ({todo.size} != {(W, H)}): vuelvo a averiguar la colocación")
            try:
                os.remove(LAYOUT_F)
            except OSError:
                pass
            lay = _layout()
            if not lay.get("mons"):
                return [_vista(todo, (0, 0))]
            todo = _img(0)
        ox, oy = lay["origen"]
        return [_vista(todo.crop((m["x"], m["y"], m["x"] + m["w"], m["y"] + m["h"])), (m["x"] + ox, m["y"] + oy))
                for m in lay["mons"]]
    img = _img(None)
    if lay is not None and lay.get("total") and list(img.size) != lay["total"]:  # arreglo 91: ha vuelto otra pantalla
        _log(f"pantallas cambiadas ({img.size} != {lay['total']}): vuelvo a averiguar la colocación")
        try:
            os.remove(LAYOUT_F)
        except OSError:
            pass
        if _layout().get("mons"):
            return capturas(zona)
    if zona:
        img = img.crop((zona[0], zona[1], min(zona[2], img.size[0]), min(zona[3], img.size[1])))
        return [_vista(img, (zona[0], zona[1]))]
    return [_vista(img, (0, 0))]


def haiku_v(objetivo, vistas, hechos):
    key = open(os.path.join(HOME, ".config/jarvis/anthropic.key"), encoding="utf-8").read().strip()
    cont = []
    for n, v in enumerate(vistas, 1):
        if len(vistas) > 1:
            cont.append({"type": "text", "text": f"Pantalla {n}{' (la principal)' if n == 1 else ''}, {v['tam'][0]}x{v['tam'][1]}:"})
        cont.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": v["b64"]}})
    txt = f"Objetivo: {objetivo}\n"
    if len(vistas) > 1:
        txt += (f"El PC tiene {len(vistas)} pantallas (una imagen cada una). En cada clic añade \"pantalla\": N con la pantalla "
                "donde está el elemento; x,y son píxeles de ESA imagen.\n")
    else:
        txt += f"Tamaño de la imagen: {vistas[0]['tam'][0]}x{vistas[0]['tam'][1]}\n"
    txt += ("Ya hiciste: " + " | ".join(hechos[-6:])) if hechos else "Es el primer paso."
    txt += "\nResponde SOLO con el JSON, empezando por { y sin texto antes ni después."
    cont.append({"type": "text", "text": txt})
    body = json.dumps({"model": "claude-haiku-5-5", "max_tokens": _tope(500), "thinking": {"type": "disabled"}, "system": _SIS_CACHE,
                       "messages": [{"role": "user", "content": cont}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", body,
                                 {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=40) as r:
        d = json.load(r)
        _gasto(d)
    out = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", out, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except ValueError:
            pass
    _log("sin JSON: " + out[:200].replace("\n", " "))
    return {"accion": "esperar"}


def enfocar(patron):
    try:
        r = pc_do.run("window.list", {}, timeout=20)
        vs = [w for w in (r or {}).get("windows", []) if w.get("visible") and w.get("title")
              and re.search(patron, str(w.get("process", "")) + " " + str(w.get("title", "")), re.I)]
        if vs:
            pc("window.focus", {"hwnd": vs[0]["hwnd"]})
            return vs[0].get("title")
    except Exception as e:  # noqa: BLE001
        _log(f"enfocar {patron}: {str(e)[:120]}")
    return None


def _espera_ventana(patron, segundos):
    t0 = time.time()
    while time.time() - t0 < segundos:
        try:
            ws = (pc_do.run("window.list", {}, timeout=15) or {}).get("windows", [])
            if any(w.get("visible") and re.search(patron, str(w.get("title", "")), re.I) for w in ws):
                _log(f"ventana lista en {time.time() - t0:.1f}s")
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
    return False


def _confirmar_clics():
    """ajustes.json «confirmar_clics»: True = señalar y preguntar antes de cada clic."""
    try:
        return bool(json.load(open(os.path.join(HOME, ".config/jarvis/ajustes.json"), encoding="utf-8")).get("confirmar_clics"))
    except (OSError, ValueError):
        return False


def _haz(a, vistas, hechos):
    acc = a.get("accion")
    if acc == "clic":
        q = re.sub(r"\b(?:no|sin|nunca|ni)\b[^,;)]{0,25}?(?:\bVR\b|SteamVR)", "", str(a.get("que", "")), flags=re.I)
        if EVITAR and re.search(EVITAR, q, re.I):
            hechos.append(f"NO pulsaste {str(a.get('que', ''))[:50]!r}: esa opción está prohibida aquí, elige la otra")
            return "BLOQUEO"
        v = vistas[min(max(int(a.get("pantalla") or 1), 1), len(vistas)) - 1]
        x, y = v["off"][0] + round(int(a["x"]) * v["esc"]), v["off"][1] + round(int(a["y"]) * v["esc"])
        if _confirmar_clics():   # modo seguro: señalo sin pulsar y pregunto (lo pulsa «pulsa» en jx_skills)
            pc("ui.point", {"x": x, "y": y})
            que = str(a.get("que", "") or "ahí")[:60]
            json.dump({"x": x, "y": y, "que": que, "doble": bool(a.get("doble")), "ts": time.time()},
                      open(os.path.join(HOME, ".config/jarvis/clic_pendiente.json"), "w", encoding="utf-8"))
            msg = f"Tengo el ratón sobre «{que}», señor. ¿Pulso? Diga «pulsa» o «no»."
            try:
                import jx
                jx.decir(msg)
                jx.tg(msg, urgente=True)
            except Exception:  # noqa: BLE001
                pass
            return msg
        pc("ui.click", {"x": x, "y": y})
        globals()["_CLICO"] = True  # hubo que pulsar algo (p. ej. elegir cuenta)
        if a.get("doble"):
            pc("ui.click", {"x": x, "y": y})
        hechos.append(f"clic en {a.get('que', '')} ({a['x']},{a['y']})")
        time.sleep(0.35)
    elif acc == "teclas":
        k = str(a.get("teclas", ""))[:30]
        if re.search(r"alt\s*\+\s*f4|delete|supr", k, re.I):
            return "No he podido, señor: no cierro ni borro con el teclado."
        pc("ui.keypress", {"keys": k})
        hechos.append(f"teclas {k}")
        if re.fullmatch(r"\s*(win|windows|super|lwin)\s*", k, re.I):
            time.sleep(1.1)  # VENTANA_WIN: deja que se abra el menu de inicio
            return "MIRA"
        time.sleep(0.25)
    elif acc == "escribir":
        t = str(a.get("texto", ""))[:300]
        if PROHIBIDO.search(t):
            return "No he podido, señor: ese texto no lo escribo sin su visto bueno."
        escribir(t)
        hechos.append(f"escribí {t[:40]!r}")
        time.sleep(0.9)  # que salgan los resultados antes de pulsar Enter
    return None


def objetivo_hacer(objetivo, pasos=10, ventana=None, hasta=None):
    if PROHIBIDO.search(objetivo):
        return "Eso no lo hago con el ratón, señor: enviar, comprar, borrar o desinstalar necesitan otra vía y su visto bueno."
    hechos = []
    _log(f"objetivo: {objetivo}")
    zona = None
    if hasta:
        _espera_ventana(hasta, 35)
        time.sleep(0.6)
    for i in range(pasos):
        if ventana and i % 4 == 0:
            t = enfocar(ventana)
            _log(f"delante: {t}")
            zona = None
            time.sleep(0.3)
        vistas = capturas(zona)
        a = haiku_v(objetivo, vistas, hechos)
        _log(f"paso {i + 1}: {json.dumps(a, ensure_ascii=False)[:300]}")
        lista = [x for x in a.get("acciones", []) if isinstance(x, dict) and x.get("accion") in ("clic", "teclas", "escribir")][:4]
        if lista:
            for x in lista:
                r = _haz(x, vistas, hechos)
                if r in ("BLOQUEO", "MIRA"):
                    break
                if r:
                    return r
            time.sleep(0.3)
            continue
        acc = a.get("accion")
        if acc == "hecho":
            return a.get("resumen") or "Hecho, señor."
        if acc == "imposible" and not any(h.startswith("dijiste imposible") for h in hechos):
            hechos.append("dijiste imposible (" + str(a.get("motivo", ""))[:80] + "); mira otra vez con cuidado toda la imagen")
            time.sleep(0.8)
            continue
        if acc == "imposible":
            return "No he podido, señor: " + str(a.get("motivo", ""))[:120]
        if acc in ("clic", "teclas", "escribir"):
            r = _haz(a, vistas, hechos)
            if r and r not in ("BLOQUEO", "MIRA"):
                return r
        else:
            hechos.append("esperé")
            time.sleep(0.6)
        time.sleep(0.2)
    return "Lo he intentado varias veces, señor, pero no he terminado. ¿Lo miro de otra forma?"


def main(a):
    if a[:1] == ["--prueba"]:
        t0 = time.time()
        b64, esc, tam = captura()
        print(f"captura: OK ({tam[0]}x{tam[1]}, escala {esc:.2f}, {time.time() - t0:.1f}s)")
        t0 = time.time()
        d = haiku("Solo describe: responde hecho con un resumen de qué ventana se ve delante.", b64, tam, [])
        print(f"Haiku ve: {str(d.get('resumen') or d)[:140]} ({time.time() - t0:.1f}s)")
        try:
            pc("ui.keypress", {"keys": "shift"})
            print("teclado: OK")
        except Exception as e:  # noqa: BLE001
            print(f"teclado: {e}")
        return 0
    pasos, espera, obj, ventana, hasta, luego = 10, 0, [], None, None, ""
    i = 0
    while i < len(a):
        if a[i] == "--pasos" and i + 1 < len(a):
            pasos = max(1, min(20, int(a[i + 1]))); i += 2
        elif a[i] == "--unico" and i + 1 < len(a):
            import fcntl
            globals()["_UNICO"] = open(os.path.join(HOME, f".config/jarvis/unico-{re.sub(r'[^a-z]', '', a[i + 1])}.lock"), "w")
            try:
                fcntl.flock(_UNICO, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                _log(f"ya hay otra tarea '{a[i + 1]}' en marcha; esta no hace falta")
                return 0
            i += 2
        elif a[i] == "--evitar" and i + 1 < len(a):
            globals()["EVITAR"] = a[i + 1]; i += 2
        elif a[i] == "--luego" and i + 1 < len(a):
            luego = a[i + 1]; i += 2
        elif a[i] == "--hasta" and i + 1 < len(a):
            hasta = a[i + 1]; i += 2
        elif a[i] == "--ventana" and i + 1 < len(a):
            ventana = a[i + 1]; i += 2
        elif a[i] == "--espera" and i + 1 < len(a):
            espera = max(0, min(120, int(a[i + 1]))); i += 2
        else:
            obj.append(a[i]); i += 1
    if not obj:
        print(__doc__); return 2
    try:  # mejora 17: si el PC esta apagado, lo enciendo antes
        import pc_do as _pcd
        if not _pcd.pc_awake():
            _log("PC apagado: lo enciendo primero")
            _pcd.ensure_awake(120)
    except Exception as e:  # noqa: BLE001
        _log(f"WOL: {str(e)[:80]}")
    time.sleep(espera)
    if hasta:
        # esperar a que salga una ventana no necesita el raton: no cojo el turno todavia
        _espera_ventana(hasta, 90 if "inicio" in getattr(globals().get("_UNICO"), "name", "") else 35)
        time.sleep(0.6)
        hasta = None
    import fcntl
    turno = open(os.path.join(HOME, ".config/jarvis/pantalla.lock"), "w")
    t0 = time.time()
    while True:
        try:
            fcntl.flock(turno, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() - t0 > 180:
                _log("otra tarea de pantalla lleva más de 3 min; sigo igualmente")
                break
            time.sleep(0.5)
    if time.time() - t0 > 1:
        _log(f"esperé mi turno {time.time() - t0:.0f}s")
    try:
        r = objetivo_hacer(" ".join(obj), pasos, ventana, hasta)
    except Exception as e:  # noqa: BLE001
        _log(f"fallo: {e}")
        r = f"No he podido, señor ({str(e)[:120]})."
    _log(f"resultado: {r}")
    if luego:
        try:
            turno.close()  # suelto el raton para la tarea que pulsa Jugar
        except Exception:  # noqa: BLE001
            pass
    if luego and luego.startswith("steam://rungameid/"):
        try:
            n = open(os.path.join(HOME, ".config/jarvis/ultimo_juego.txt"), encoding="utf-8").read().strip()
        except OSError:
            n = ""
        if n and _espera_ventana(re.escape(n), 25):
            _log(f"{n} ya se abrió solo al elegir la cuenta; no lo lanzo otra vez")
            luego = ""
    if luego and not globals().get("_CLICO"):
        _log(f"luego: no hizo falta pulsar nada, el juego ya se lanzo; no lo vuelvo a abrir")
    if luego and globals().get("_CLICO") and not r.startswith("No he podido"):
        time.sleep(4)
        import juegos
        _log(f"luego: {luego} -> {juegos.mandar(luego) or 'enviado'}")
    print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

