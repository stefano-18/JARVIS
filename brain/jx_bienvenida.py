#!/usr/bin/env python3
"""JARVIS: saludo por voz la primera vez que se enciende el PC cada día, y resumen del día por la tarde.

Lo lanza el vigilante cada 5 min (en segundo plano). Cada cosa sale una sola vez al día y solo si el PC está encendido.
Se apaga con ajustes.json: {"saludo": false} o {"resumen_tarde": false}.
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jx  # noqa: E402

ESTADO = "bienvenida.json"
SALUDOS = {
    "manana": ["Buenos días, señor. Me alegra verle.", "Buenos días, señor. Todo listo para empezar el día.",
               "Buenos días, señor. El café es cosa suya; del resto me encargo yo.", "Buenos días, señor. Sistemas en orden."],
    "tarde": ["Buenas tardes, señor. Bienvenido de nuevo.", "Buenas tardes, señor. Todo en orden por aquí.",
              "Buenas tardes, señor. Le estaba esperando."],
    "noche": ["Buenas noches, señor. Trabajando hasta tarde, por lo que veo.", "Buenas noches, señor. Aquí sigo, como siempre.",
              "Buenas noches, señor. Bienvenido."],
}


def una_vez(clave):
    est = jx.leer_json(ESTADO, {})
    hoy = jx.ahora().date().isoformat()
    if est.get(clave) == hoy:
        return False
    est[clave] = hoy
    jx.guardar_json(ESTADO, est)
    return True


def franja(h):
    return "manana" if 5 <= h < 14 else "tarde" if h < 21 else "noche"


def saludo():
    import jx_skills
    base = random.choice(SALUDOS[franja(jx.ahora().hour)])
    try:
        dia = jx_skills.que_tengo_hoy("voz").replace(" Eso es todo, señor.", "")
    except Exception:  # noqa: BLE001
        dia = ""
    return f"{base} {dia}".strip()


def resumen_tarde():
    partes = ["Señor, un breve resumen de su día."]
    try:
        g = jx.gastado(jx._inicio_dia())
        partes.append(f"Hoy JARVIS ha gastado {g:.2f} dólares en inteligencia artificial." if g >= 0.01 else
                      "Hoy apenas he gastado en inteligencia artificial.")
    except Exception:  # noqa: BLE001
        pass
    try:
        import jx_skills
        compra = jx_skills.lista_compra()
        if compra:
            partes.append("En la lista de la compra siguen: " + ", ".join(compra[:6]) + ".")
    except Exception:  # noqa: BLE001
        pass
    manana = (jx.ahora().date() + __import__("datetime").timedelta(days=1)).isoformat()
    rs = [r for r in jx.recordatorios() if time.strftime("%Y-%m-%d", time.localtime(r["ts"])) == manana]
    if rs:
        partes.append(f"Mañana tiene {len(rs)} recordatorio{'s' if len(rs) != 1 else ''}; el primero, a las "
                      f"{time.strftime('%H:%M', time.localtime(min(r['ts'] for r in rs)))}.")
    if jx.ahora().weekday() == 6:  # domingo: el gasto de la semana
        try:
            sem = jx.gastado(time.time() - 7 * 86400)
            partes.append(f"Esta semana JARVIS ha gastado {sem:.2f} dólares en total.")
        except Exception:  # noqa: BLE001
            pass
    partes.append("Eso es todo. Que tenga buena tarde, señor.")
    return " ".join(partes)


def diario():
    """Nota del día en Obsidian (JARVIS/Diario): así la memoria de JARVIS sabe qué pasó cada día."""
    import jx_obsidian as O
    import jx_skills as K
    hoy = jx.ahora()
    lineas = [f"# {jx.DIAS[hoy.weekday()].capitalize()} {hoy.day} de {jx.MESES[hoy.month - 1]} de {hoy.year}", ""]
    try:
        lineas.append("- Tiempo: " + K.el_tiempo("hoy").replace(", señor.", "."))
    except Exception:  # noqa: BLE001
        pass
    try:
        r = K._run("games.time", {"dias": 1})
        if K._ok(r) and r.get("minutos"):
            lineas.append(f"- Jugó {r['minutos']} min: " + ", ".join(f"{j['juego']} ({j['minutos']} min)" for j in r["juegos"]))
    except Exception:  # noqa: BLE001
        pass
    try:
        lineas.append(f"- Gasto de IA de JARVIS: {jx.gastado(jx._inicio_dia()):.2f} USD")
    except Exception:  # noqa: BLE001
        pass
    compra = K.lista_compra()
    if compra:
        lineas.append("- Pendiente de comprar: " + ", ".join(compra))
    notas = [ln for ln in K._nota("Notas rápidas").split("## ") if ln.startswith(hoy.strftime("%Y-%m-%d"))]
    if notas:
        lineas.append("- Apuntó hoy: " + "; ".join(n.split("\n", 1)[-1].strip().lstrip("- ") for n in notas))
    O.anota(hoy.strftime("%Y-%m-%d"), "\n".join(lineas), "JARVIS/Diario")


def main():
    h = jx.ahora().hour
    if h >= 23 and una_vez("diario"):          # el diario se escribe aunque el PC esté apagado
        try:
            diario()
        except Exception as e:  # noqa: BLE001
            jx.log("mayordomo", f"diario: {str(e)[:100]}")
    if not jx.agente_pc_conectado():
        return
    pend = jx.leer_json("al_encender.json", [])      # «recuérdame X cuando encienda el PC»
    if pend:
        jx.guardar_json("al_encender.json", [])
        txt = "Señor, me pidió que le recordara al encender el PC: " + "; ".join(p["texto"] for p in pend) + "."
        jx.decir(txt)
        jx.tg("⏰ " + txt, urgente=True)
    aj = jx.leer_json("ajustes.json", {})
    h = jx.ahora().hour
    if aj.get("saludo", True) and 6 <= h < 23 and una_vez("saludo"):
        jx.decir(saludo())
        jx.log("mayordomo", "saludo del día por voz")
    elif aj.get("resumen_tarde", True) and 20 <= h < 22 and una_vez("tarde"):
        jx.decir(resumen_tarde())
        jx.log("mayordomo", "resumen de la tarde por voz")


if __name__ == "__main__":
    if sys.argv[1:] == ["--prueba"]:
        print("SALUDO:", saludo())
        print("TARDE:", resumen_tarde())
    elif sys.argv[1:] == ["--diario"]:
        diario()
        print("diario escrito")
    else:
        main()
