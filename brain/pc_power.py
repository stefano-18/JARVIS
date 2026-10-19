"""pc_power.py - Energia del PC fijo por el canal hub (127.0.0.1:18766).

Comandos:
  status              Estado hub + PC (solo lectura).
  shutdown --yes      Apaga el PC (HIGH: grant 60 s un solo uso).
  suspend             NO soportado por el canal (sin manifiesto): explica y sale.

Seguridad:
- El secreto se lee de jarvis2/.env en proceso, NUNCA se imprime.
- shutdown exige --yes (la skill de Telegram solo lo pasa tras un "si"
  explicito del usuario) + grant firmado de 60 s + ratelimit del repo.
- suspend no se ejecuta: requiere manifiesto nuevo en el PC (ver docs/fase3b.md).
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

_JROOT = Path(__file__).resolve().parent.parent
if str(_JROOT) not in sys.path:
    sys.path.insert(0, str(_JROOT))

PC_IP_DEFAULT = "{{PC_IP}}"


def load_env():
    vals = {}
    envf = _JROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def ping_ok(ip):
    try:
        r = subprocess.run(["ping", "-n", "1", "-w", "1000", ip],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def tcp_ok(ip, port, timeout=3):
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


async def hub_info(secret, device):
    from remote import hub_client as hc
    h = hc.HubClientHandle(device=device, secret=secret)
    try:
        return await h.ainfo()
    except Exception as e:
        return {"status": "error", "code": "hub_down",
                "error": f"hub local caido: {str(e)[:120]}"}


def policy_ctx():
    try:
        import yaml
        reg = yaml.safe_load(
            (_JROOT / "config" / "remote.yaml").read_text(encoding="utf-8"))
        pol = (reg or {}).get("policy", {})
        return {"roots": pol.get("allowed_roots", []), "apps": {},
                "commands": []}
    except Exception:
        return {"roots": [], "apps": {}, "commands": []}


async def cmd_status(env):
    ip = env.get("PC_IP", PC_IP_DEFAULT)
    info = await hub_info(env.get("JARVIS_REMOTE_SECRET", ""),
                          env.get("JARVIS_REMOTE_DEVICE_ID", "local-client"))
    lines = []
    if info.get("status") == "ok":
        res = info.get("result", {}) if isinstance(info.get("result"), dict) else info
        devs = res.get("devices", res.get("nodes", "?"))
        lines.append(f"hub: ok, dispositivos: {devs}")
    else:
        lines.append(f"hub: {info.get('code', 'error')} "
                     f"({str(info.get('error', ''))[:100]})")
    up = ping_ok(ip) or tcp_ok(ip, 11434) or tcp_ok(ip, 8765)
    lines.append(f"pc ({ip}): {'alcanzable' if up else 'no responde'}")
    print("\n".join(lines))
    return 0 if info.get("status") == "ok" else 1


async def cmd_shutdown(env):
    from remote_agent import protocol as P
    from remote import ratelimit as RL
    from remote import pc_proxy as proxy
    secret = env.get("JARVIS_REMOTE_SECRET", "")
    device = env.get("JARVIS_REMOTE_DEVICE_ID", "local-client")
    if not secret:
        print("ERROR: falta JARVIS_REMOTE_SECRET en jarvis2/.env")
        return 2
    info = await hub_info(secret, device)
    if info.get("status") != "ok":
        print(f"ERROR: hub no disponible "
              f"({str(info.get('error', ''))[:100]})")
        return 1
    ok_rl, wait_s = RL.check_and_add()
    if not ok_rl:
        print(RL.message("apagar el PC", wait_s))
        return 1
    proxy.configure_client(device, secret)
    grant = P.mint_grant(secret, "system.shutdown", {})
    RL.note(grant.get("grant_id"))
    res = await proxy.call_remote("system.shutdown", policy_ctx(), grant,
                                  timeout=45)
    if res.get("status") == "ok":
        print("RESULTADO: orden de apagado enviada al PC.")
        return 0
    print(f"RESULTADO: el PC rechazo o fallo: "
          f"{str(res.get('error', res))[:200]}")
    return 1


def cmd_suspend():
    print("NO SOPORTADO: el canal hub no tiene manifiesto system.suspend.")
    print("Diseno propuesto en jarvis2/docs/fase3b.md (requiere cambio en el PC).")
    return 3


async def amain(argv):
    env = load_env()
    os.environ.setdefault("JARVIS_REMOTE_DEVICE_ID",
                          env.get("JARVIS_REMOTE_DEVICE_ID", "local-client"))
    if env.get("JARVIS_REMOTE_SECRET"):
        os.environ["JARVIS_REMOTE_SECRET"] = env["JARVIS_REMOTE_SECRET"]
    if not argv or argv[0] == "status":
        return await cmd_status(env)
    if argv[0] == "shutdown":
        if "--yes" not in argv[1:]:
            print("Requiere --yes (tras confirmacion explicita del usuario).")
            return 2
        return await cmd_shutdown(env)
    if argv[0] == "suspend":
        return cmd_suspend()
    print("Uso: pc_power.py [status|shutdown --yes|suspend]")
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain(sys.argv[1:])))
