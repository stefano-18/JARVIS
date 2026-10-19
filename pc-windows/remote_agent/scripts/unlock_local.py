"""DESBLOQUEO LOCAL DE EMERGENCIA del kill-switch (SOLO uso fisico en este PC).

No pasa por la red: lo ejecuta el usuario con doble clic o
`python scripts\\unlock_local.py`. Pide confirmacion en consola y
restablece killswitch.json a desbloqueado.

El desbloqueo queda registrado en killswitch_local.log (fichero aparte).
NUNCA toca audit.jsonl (prohibido con el agente vivo: rompería la
hash-chain y falsearía la auditoría).

El agente lee killswitch.json en CADA decision MEDIUM/HIGH
(agent._is_locked -> killswitch.is_locked), asi que el desbloqueo surte
efecto inmediato SIN reiniciar el agente.
"""
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KILL_FILE = PROJECT_ROOT / "killswitch.json"
LOCAL_LOG = PROJECT_ROOT / "killswitch_local.log"

sys.path.insert(0, str(PROJECT_ROOT))
import killswitch as KS  # noqa: E402  (stdlib + modulo propio, sin red)

CONFIRM_WORD = "DESBLOQUEAR"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def current_state() -> tuple:
    """(locked: bool, raw: str) del fichero. Ausente/corrupto = desbloqueado."""
    try:
        raw = KILL_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False, "(sin fichero)"
    except OSError as e:
        return False, f"(ilegible: {e})"
    return KS.is_locked(KILL_FILE), raw[:200]


def do_unlock(actor: str = "usuario-local", confirmed: bool = False) -> dict:
    """Restablece a desbloqueado y lo registra en killswitch_local.log.

    Solo se llama tras confirmacion en consola (o --yes en tests).
    No toca audit.jsonl. Retorna el estado escrito.
    """
    locked_before, _ = current_state()
    state = KS.set_locked(KILL_FILE, False, "local-unlock")
    line = (f"{_now()} unlock-local actor={actor} "
            f"locked_before={locked_before} locked_after=False "
            f"ts={state.get('ts')} boot_ts={int(time.time())}\n")
    LOCAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOCAL_LOG.open("a", encoding="utf-8") as f:
        f.write(line)
    return state


def main(argv: list) -> int:
    yes = "--yes" in (argv or [])
    locked, raw = current_state()
    print(f"kill-switch local: {'BLOQUEADO' if locked else 'desbloqueado'}")
    print(f"fichero: {KILL_FILE} -> {raw}")
    if not locked:
        print("Ya esta desbloqueado: no se hace nada.")
        return 0
    if not yes:
        print()
        print("Vas a RESTABLECER el bloqueo MEDIUM/HIGH de este PC.")
        try:
            answer = input(f"Escribe {CONFIRM_WORD} para confirmar: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelado: sigue BLOQUEADO.")
            return 1
        if answer != CONFIRM_WORD:
            print("No coincide: sigue BLOQUEADO.")
            return 1
        confirmed = True
    else:
        confirmed = True
    do_unlock(confirmed=confirmed)
    print("Desbloqueado. El agente lo aplica SIN reiniciar "
          "(lee el fichero en cada decision MEDIUM/HIGH).")
    print(f"Registrado en {LOCAL_LOG} (audit.jsonl intacto).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
