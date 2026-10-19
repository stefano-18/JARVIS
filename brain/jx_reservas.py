#!/usr/bin/env python3
"""JARVIS: prueba diaria de los modelos de reserva (mejora 10). Solo Claude para pensar (arreglo 81): Groq solo para oír
y Ollama (PC y portátil) como reserva sin claves. Apunta en ~/.config/jarvis/proveedores.json cuáles
responden; la voz se salta los caídos hasta que vuelvan. No imprime claves."""
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jx  # noqa: E402


def _get(url, headers=None, timeout=8):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def _clave_hermes(nombre):
    try:
        txt = open(os.path.join(jx.HOME, ".hermes/config.yaml"), encoding="utf-8").read()
        m = re.search(r"-\s*name:\s*" + re.escape(nombre) + r"\s*\n(?:\s+\w+:.*\n)*?\s+api_key:\s*['\"]?([^'\"\n]+)", txt)
        return m.group(1).strip() if m else ""
    except OSError:
        return ""


def _groq():
    for f in (os.path.join(jx.CFG, "groq.key"),):
        try:
            k = open(f, encoding="utf-8").read().strip()
            if k:
                return k
        except OSError:
            pass
    return jx._env().get("GROQ_API_KEY", "")


def prueba():
    res = {}
    pruebas = {
        "groq": lambda: _get("https://api.groq.com/openai/v1/models", {"Authorization": "Bearer " + _groq(), "User-Agent": "jarvis/1.0"}),
        "ollama-portatil": lambda: _get("http://127.0.0.1:11434/api/tags", timeout=4),
        "ollama-pc": lambda: _get(f"http://{jx.conf()['pc_ip']}:11434/api/tags", timeout=4) if jx.pc_encendido() else "pc apagado",
    }
    for n, f in pruebas.items():
        try:
            r = f()
            res[n] = {"ok": r == 200, "ts": int(time.time()), "detalle": str(r)} if r != "pc apagado" else {"ok": None, "ts": int(time.time()), "detalle": r}
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            for k in (_groq(), _clave_hermes("mistral")):
                if k:
                    msg = msg.replace(k, "***")
            res[n] = {"ok": False, "ts": int(time.time()), "detalle": msg[:80]}
    jx.guardar_json("proveedores.json", res)
    notas = []
    if res.get("groq", {}).get("ok") is False:
        notas.append("Groq (solo para oír) no acepta la clave: {{NOMBRE}} tiene que ponerla él con su script (nunca en el chat)")
    print(", ".join(f"{k}: {'sí' if v['ok'] else ('-' if v['ok'] is None else 'NO')}" for k, v in res.items()) + (" | " + "; ".join(notas) if notas else ""))


if __name__ == "__main__":
    prueba()
