"""Minuta una concesion HIGH firmada (60 s, un solo uso) SIN ejecutar nada.

Uso (prueba supervisada):
  python scripts/mint_grant.py <accion> '<params-json>'

Ejemplo:
  python scripts/mint_grant.py window.move '{"title": "Bloc de notas", "x": 100, "y": 100}'

Imprime el grant JSON listo para pegar en la llamada. El secreto se lee
de jarvis2/.env (nunca se imprime). La concesion caduca a los 60 s y solo
vale para la accion+params exactos: generala justo antes de usarla.
"""
import json
import sys
from pathlib import Path

_JROOT = Path(__file__).resolve().parent.parent
if str(_JROOT) not in sys.path:
    sys.path.insert(0, str(_JROOT))


def _load_secret() -> str:
    vals = {}
    envf = _JROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    return vals.get("JARVIS_REMOTE_SECRET", "")


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    action = sys.argv[1]
    try:
        params = json.loads(sys.argv[2])
    except ValueError as e:
        print(f"params JSON invalido: {e}")
        return 2
    secret = _load_secret()
    if not secret:
        print("Falta JARVIS_REMOTE_SECRET en jarvis2/.env")
        return 2
    from remote_agent import protocol as P
    from remote import ratelimit as RL
    ok_rl, wait_s = RL.check_and_add()
    if not ok_rl:
        print(RL.message(f"minutar {action}", wait_s))
        return 1
    grant = P.mint_grant(secret, action, params)
    RL.note(grant.get("grant_id"))
    print(json.dumps(grant, ensure_ascii=False))
    print("Valida 60 s, un solo uso, solo para "
          f"{action} {json.dumps(params, ensure_ascii=False)[:150]}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
