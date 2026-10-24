"""wake_pc.py - Despierta el PC fijo por Wake-on-LAN y espera a que responda.

Logica basada en Jarvis/tools/wake.py (stdlib, magic packet por broadcast).
Lee JARVIS_PC_MAC y PC_IP de jarvis2/.env (variables de entorno mandan).

"Despierto" = responde al ping O tiene abierto TCP 11434/8765 (por si el
PC bloquea ICMP en su firewall).

Uso:
    python scripts/wake_pc.py [--wait 120] [--no-wait] [--ping-only]

- Sin flags: si el PC ya responde al ping, informa "ya esta despierto" y
  no envia nada. Si no, envia magic packet y espera hasta 120 s.
- --ping-only: solo comprueba ping, no envia packet.
- --no-wait: envia packet y sale sin esperar.
- --wait N: segundos maximos de espera (default 120).

Salidas: lineas legibles. Exit 0 = despierto, 1 = timeout/fallo, 2 = MAC mala.
La MAC se muestra redactada (ultimo octeto oculto).
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_BROADCASTS = ("{{RED}}.255", "255.255.255.255")
DEFAULT_PORTS = (9, 7)
PING_TIMEOUT_MS = 1000


def load_env_file():
    """Lee jarvis2/.env (stdlib). No imprime valores."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    data = {}
    try:
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return data


def get_mac(file_env):
    return (os.getenv("JARVIS_PC_MAC") or file_env.get("JARVIS_PC_MAC", "")).strip()


def get_ip(file_env):
    return (os.getenv("PC_IP") or file_env.get("PC_IP", "{{PC_IP}}")).strip()


def redact_mac(mac):
    parts = mac.replace("-", ":").split(":")
    if len(parts) == 6:
        return ":".join(parts[:5]) + ":XX"
    return "XX:XX:XX:XX:XX:XX"


def build_magic_packet(mac):
    clean = "".join(c for c in mac if c in "0123456789abcdefABCDEF")
    if len(clean) != 12:
        raise ValueError("MAC invalida (se esperaban 12 hex)")
    return b"\xff" * 6 + bytes.fromhex(clean) * 16


def send_packet(pkt):
    sent = []
    for port in DEFAULT_PORTS:
        for bcast in DEFAULT_BROADCASTS:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(pkt, (bcast, port))
                s.close()
                sent.append(f"{bcast}:{port}")
            except OSError:
                continue
    return sent


def ping_ok(ip):
    try:
        r = subprocess.run(
            (["ping", "-n", "1", "-w", str(PING_TIMEOUT_MS), ip] if os.name == "nt"
             else ["ping", "-c", "1", "-W", str(max(1, PING_TIMEOUT_MS // 1000)), ip]),
            capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


TCP_PORTS = (22, 11434, 8765)  # 22 = SSH del PC Linux
TCP_TIMEOUT_S = 3


def tcp_ok(ip, ports=TCP_PORTS):
    """True si algun puerto TCP responde (por si ICMP esta bloqueado en el PC)."""
    for p in ports:
        try:
            s = socket.create_connection((ip, p), timeout=TCP_TIMEOUT_S)
            s.close()
            return True, p
        except OSError:
            continue
    return False, None


def awake(ip):
    """Despierto = ping OK o algun puerto TCP clave abierto. Retorna (bool, via)."""
    if ping_ok(ip):
        return True, "ping"
    ok, port = tcp_ok(ip)
    if ok:
        return True, f"tcp/{port}"
    return False, ""


def main(argv):
    wait_s = 120
    do_wait = True
    ping_only = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--wait" and i + 1 < len(argv):
            try:
                wait_s = max(0, int(argv[i + 1]))
            except ValueError:
                print("ERROR: --wait necesita un numero")
                return 1
            i += 2
        elif a == "--no-wait":
            do_wait = False
            i += 1
        elif a == "--ping-only":
            ping_only = True
            i += 1
        else:
            print(f"ERROR: flag desconocido: {a}")
            return 1

    file_env = load_env_file()
    mac = get_mac(file_env)
    ip = get_ip(file_env)
    print(f"PC objetivo: {ip} | MAC: {redact_mac(mac)}")

    is_awake, via = awake(ip)
    if is_awake:
        print(f"RESULTADO: ya esta despierto (via {via}). Nada que enviar.")
        return 0
    if ping_only:
        print("RESULTADO: apagado o inalcanzable (ni ping ni TCP 11434/8765).")
        return 1

    try:
        pkt = build_magic_packet(mac)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 2
    sent = send_packet(pkt)
    if not sent:
        print("ERROR: no se pudo enviar a ningun broadcast.")
        return 1
    print(f"Magic packet enviado via {', '.join(sent)}.")
    if not do_wait:
        print("RESULTADO: packet enviado (sin espera).")
        return 0

    print(f"Esperando hasta {wait_s} s a que {ip} responda (ping o TCP)...")
    deadline = time.time() + wait_s
    while time.time() < deadline:
        time.sleep(5)
        is_awake, via = awake(ip)
        if is_awake:
            print(f"RESULTADO: despierto (via {via}).")
            return 0
    print(f"RESULTADO: timeout ({wait_s} s) sin respuesta. Revisa BIOS/WOL y red.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
