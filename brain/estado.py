"""estado.py - Estado laptop + PC + IA para Telegram (solo lectura, stdlib).

Uso: python scripts/estado.py
Imprime lineas cortas. Nunca imprime secretos (solo el modelo en uso).
"""
import ctypes
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

_JROOT = Path(__file__).resolve().parent.parent
PC_IP = "{{PC_IP}}"


def mem() -> dict:
    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPF", ctypes.c_ulonglong),
                    ("ullAvailPF", ctypes.c_ulonglong),
                    ("ullTotalV", ctypes.c_ulonglong),
                    ("ullAvailV", ctypes.c_ulonglong),
                    ("ullAvailExV", ctypes.c_ulonglong)]
    st = MS()
    st.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    return {"pct": st.dwMemoryLoad,
            "total_gb": st.ullTotalPhys / 1e9,
            "free_gb": st.ullAvailPhys / 1e9}


def uptime_h() -> float:
    ms = ctypes.windll.kernel32.GetTickCount64()
    return ms / 3600000.0


def cpu_pct() -> str:
    try:
        import psutil
        return f"{psutil.cpu_percent(interval=1):.0f}%"
    except Exception:
        return "n/d (sin psutil)"


def tcp_ok(ip, port, timeout=3) -> bool:
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def ping_ok(ip) -> bool:
    try:
        r = subprocess.run((["ping", "-n", "1", "-w", "1000", ip] if os.name == "nt" else ["ping", "-c", "1", "-W", "1", ip]),
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def http_json(url, timeout=8):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "jarvis"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def main() -> int:
    out = []
    m = mem()
    du = shutil.disk_usage("C:\\")
    out.append(f"laptop: CPU {cpu_pct()}, RAM {m['pct']}% "
               f"({m['free_gb']:.1f}/{m['total_gb']:.1f} GB libres), "
               f"disco C: {du.free / 1e9:.0f}/{du.total / 1e9:.0f} GB libres, "
               f"uptime {uptime_h():.1f} h")
    gw = tcp_ok("127.0.0.1", 18789)
    oll = tcp_ok("127.0.0.1", 11434)
    hub = tcp_ok("127.0.0.1", 18765) or tcp_ok("127.0.0.1", 8765)
    out.append(f"servicios: gateway18789={'OK' if gw else 'CAIDO'}, "
               f"ollama={'OK' if oll else 'CAIDO'}, "
               f"jarvis-hub={'OK' if hub else 'CAIDO'}")
    pc_up = ping_ok(PC_IP) or tcp_ok(PC_IP, 22) or tcp_ok(PC_IP, 11434) or tcp_ok(PC_IP, 8765)
    if pc_up:
        tags = http_json(f"http://{PC_IP}:11434/api/tags")
        models = ",".join(t.get("name", "?") for t in (tags or {}).get(
            "models", [])[:4]) or "?"
        ps = http_json(f"http://{PC_IP}:11434/api/ps")
        loaded = ",".join(x.get("name", "?") for x in (ps or {}).get(
            "models", [])[:2]) or "ninguno"
        out.append(f"pc ({PC_IP}): ENCENDIDO, ollama OK, "
                   f"modelos: {models}, en memoria: {loaded}")
    else:
        out.append(f"pc ({PC_IP}): APAGADO o inalcanzable")
    try:
        cfg = json.loads((Path.home() / ".openclaw" / "openclaw.json"
                          ).read_text(encoding="utf-8"))
        model = (cfg.get("agents", {}).get("defaults", {}).get("model", {}))
        primary = model.get("primary", "?") if isinstance(model, dict) else model
        out.append(f"ia respondiendo: {primary}")
    except Exception:
        out.append("ia respondiendo: ?")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
