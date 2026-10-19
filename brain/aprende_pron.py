#!/usr/bin/env python3
"""JARVIS (arreglo 74): aprende como debe leer la voz en español los nombres de apps y juegos.

Uso: aprende_pron.py [--populares] [archivo_de_nombres ...]
Siempre mira tambien juegos_ok.txt, apps_ok.txt y nombres_pc.txt. Guarda en ~/.config/jarvis/pronuncia.json
sin pisar lo ya aprendido, y apunta en pronuncia_vistos.json lo ya consultado para no volver a preguntarlo."""
import json, os, re, sys, urllib.request

HOME = os.path.expanduser("~")
CFG = os.path.join(HOME, ".config/jarvis")
F = os.path.join(CFG, "pronuncia.json")
VISTOS = os.path.join(CFG, "pronuncia_vistos.json")
USO = {"in": 0, "out": 0, "llamadas": 0}
COMUNES = set("""abrir abre cierra notas panel control archivos explorador configuracion configuración sistema servicios fotos
mapa lupa paint calculadora camara cámara grabadora sonido monitor recursos rendimiento programador tareas ejecutar
narrador teclado pantalla subtitulos subtítulos directo asistencia rapida rápida actualizaciones comprobar configurar
herramienta recortes informacion información iniciador enlace movil móvil eventos diagnostico diagnóstico memoria
liberador espacio disco directiva seguridad local origenes orígenes datos acceso acerca juego juegos bloc""".split())
REGLAS = ("Una voz de texto a voz en español de España lee nombres de juegos y programas. Para cada nombre, escríbelo como "
          "debe leerse para que suene como lo dice la gente (normalmente en inglés), con letras y tildes españolas. "
          "Ejemplos: Phasmophobia -> Fasmofobia, Spotify -> Espotifai, Steam -> Estim, Discord -> Díscord, "
          "Hollow Knight -> Jolou Nait, Counter-Strike 2 -> Cáunter Estráik 2. Si ya suena bien leído en español, o es "
          "una abreviatura sin sentido, devuélvelo exactamente igual.")


def haiku(system, user, max_tokens):
    key = open(os.path.join(CFG, "anthropic.key"), encoding="utf-8").read().strip()
    body = json.dumps({"model": "claude-haiku-5-5", "max_tokens": max_tokens, "thinking": {"type": "disabled"},
                       "system": system, "messages": [{"role": "user", "content": user}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", body,
                                 {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.load(r)
    u = d.get("usage", {})
    USO["in"] += u.get("input_tokens", 0); USO["out"] += u.get("output_tokens", 0); USO["llamadas"] += 1
    t = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    return json.loads(t[t.find("{"):t.rfind("}") + 1])


def _plano(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def valido(n, v):
    v = str(v).strip()
    return (len(n) >= 4 and n.lower() not in COMUNES and _plano(n) != _plano(v)
            and re.fullmatch(r"[\w áéíóúüñÁÉÍÓÚÜÑ'.:!+&-]{1,60}", v) is not None and len(v) <= 2 * len(n) + 10)


def leer(p, defecto):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return defecto


def guardar(p, d):
    tmp = p + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, p)


def nombres_de(p):
    try:
        return [x.strip() for x in open(p, encoding="utf-8-sig").read().split("\n") if x.strip()]
    except OSError:
        return []


def main(a):
    pr, vistos = leer(F, {}), set(leer(VISTOS, []))
    antes = len(pr)
    conocidos = {k.lower() for k in pr} | {x.lower() for x in vistos}
    if "--populares" in a:
        for tema in ("100 videojuegos de PC populares de acción, shooters y battle royale (actuales y clásicos)",
                     "100 videojuegos de PC populares de rol, aventura, mundo abierto y soulslike",
                     "100 videojuegos de PC populares de estrategia, simulación, supervivencia, deportes, carreras, indies y cooperativos",
                     "150 aplicaciones y programas comunes de Windows (navegadores, chat, música, vídeo, edición, ofimática, "
                     "programación, utilidades, lanzadores de juegos, periféricos)"):
            tema += ", con el nombre oficial"
            try:
                d = haiku(REGLAS + " Responde SOLO un objeto JSON {nombre oficial: lectura} con todos.", "Dame " + tema + ".", 16000)
            except Exception as e:  # noqa: BLE001
                print(f"populares: fallo ({str(e)[:80]})")
                continue
            for n, v in d.items():
                n = str(n).strip()
                if n.lower() not in {k.lower() for k in pr} and valido(n, v):
                    pr[n] = str(v).strip()
                vistos.add(n)
            print(f"populares: {len(d)} nombres recibidos")
    todos = []
    for p in [x for x in a if not x.startswith("--")] + [os.path.join(CFG, f) for f in ("nombres_pc.txt", "juegos_ok.txt", "apps_ok.txt")]:
        todos += nombres_de(p)
    falta, vis = [], set()
    for n in todos:
        if 2 <= len(n) <= 40 and n.lower() not in conocidos and n.lower() not in vis:
            falta.append(n); vis.add(n.lower())
    for i in range(0, len(falta), 40):
        tanda = falta[i:i + 40]
        try:
            d = haiku(REGLAS + " Responde SOLO un objeto JSON {nombre: lectura} con todos los nombres que te paso.",
                      json.dumps(tanda, ensure_ascii=False), 3000)
        except Exception as e:  # noqa: BLE001
            print(f"tanda {i // 40 + 1}: fallo ({str(e)[:80]})")
            continue
        for n in tanda:
            if n in d and valido(n, d[n]) and n.lower() not in {k.lower() for k in pr}:
                pr[n] = str(d[n]).strip()
            vistos.add(n)
    guardar(F, pr)
    guardar(VISTOS, sorted(vistos))
    print(f"pronuncia.json: {len(pr)} nombres ({len(pr) - antes} nuevos); consultados ahora: {len(falta)}; "
          f"llamadas: {USO['llamadas']}, tokens: {USO['in']} entrada / {USO['out']} salida")


if __name__ == "__main__":
    main(sys.argv[1:])
