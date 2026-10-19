#!/usr/bin/env python3
"""JARVIS: vigilante (mejora 6). Cada 5 min: jarvis-v2, hermes-gateway, jarvis-agenda y el agente del PC (si el PC esta
encendido). Reinicia lo caido y avisa al señor UNA vez si sigue caido 10 minutos; avisa tambien cuando vuelve."""
import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jx  # noqa: E402


def activo(unidad, usuario):
    r = subprocess.run(["systemctl"] + (["--user"] if usuario else []) + ["is-active", unidad], capture_output=True, text=True)
    return r.stdout.strip() == "active"


def puerto(ip, p):
    try:
        with socket.create_connection((ip, p), 2):
            return True
    except OSError:
        return False


def agente_conectado():
    # el agente del PC se conecta al hub del portatil (puerto 18765)
    r = subprocess.run(["ss", "-tnH", "state", "established", "( sport = :18765 )"], capture_output=True, text=True)
    return jx.conf()["pc_ip"] in r.stdout


def main():
    est = jx.leer_json("vigilante.json", {})
    ahora = time.time()
    comprobar = {
        "jarvis-v2": (lambda: activo("jarvis-v2", False) and puerto("127.0.0.1", 8765), ["sudo", "-n", "systemctl", "restart", "jarvis-v2"]),
        "hermes-gateway": (lambda: activo("hermes-gateway", True), ["systemctl", "--user", "restart", "hermes-gateway"]),
        "jarvis-agenda": (lambda: activo("jarvis-agenda", True), ["systemctl", "--user", "restart", "jarvis-agenda"]),
    }
    pc_on = jx.pc_encendido()
    if pc_on:
        comprobar["agente del PC"] = (agente_conectado, None)
    lineas = []
    for nombre, (prueba, reinicio) in comprobar.items():
        bien = prueba()
        e = est.get(nombre, {})
        if bien:
            if e.get("avisado"):
                jx.tg(f"✅ Señor, {nombre} vuelve a funcionar.", urgente=True)
            est[nombre] = {}
            lineas.append(f"{nombre}: bien")
            continue
        if not e.get("desde"):
            e = {"desde": ahora}
        if reinicio:
            subprocess.run(reinicio, capture_output=True, timeout=60)
            time.sleep(6)
            bien = prueba()
        if bien:
            jx.log("tecnico", f"vigilante: {nombre} estaba caído y lo he reiniciado")
            est[nombre] = {}
            lineas.append(f"{nombre}: reiniciado")
            continue
        if ahora - e["desde"] >= 600 and not e.get("avisado"):
            jx.tg(f"⚠️ Señor, {nombre} lleva más de 10 minutos caído y no consigo levantarlo.", urgente=True)
            e["avisado"] = True
        est[nombre] = e
        lineas.append(f"{nombre}: CAÍDO")
    if not pc_on:
        est.pop("agente del PC", None)
    jx.guardar_json("vigilante.json", est)
    print("; ".join(lineas))


if __name__ == "__main__":
    main()
