"""Verificacion post-08:05: dice ENVIADO o NO ENVIADO Y POR QUÉ.

Fuentes (cada una con fecha propia salvo jarvis.log, que solo trae hora):
- jarvis2 data/briefing.json ......... marca del nativo (fecha + intentos).
- jarvis2 logs/health.jsonl .......... aviso de salud (fecha + notified).
- jarvis2 logs/jarvis.log ............ lineas "briefing voice"/"motivo".
- V1 logs/scheduler.log .............. jobs morning_0755/briefing_0900.
- V2 logs/main.stderr.log ............ GOAL briefing con executed.
- Procesos ........................... pollers Telegram vivos (debe ser 1).

Uso:  python scripts/check_briefing.py   (despues de las 08:05)
Retorna 0 si el briefing de hoy fue ENVIADO (1 solo audio nativo),
1 si NO fue enviado (siempre con el motivo).
Nunca muestra contenido del briefing ni secretos: solo horas y motivos.
"""
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_JROOT = Path(__file__).resolve().parent.parent
if str(_JROOT) not in sys.path:
    sys.path.insert(0, str(_JROOT))

ROME = ZoneInfo("Europe/Rome")
V1_SCHED = Path(r"{{WIN_HOME}}\Jarvis\logs\scheduler.log")
V2_MAIN = Path(r"{{WIN_HOME}}\Jarvis-v2\logs\main.stderr.log")


def today() -> str:
    return datetime.now(ROME).strftime("%Y-%m-%d")


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def jarvis2_state() -> dict:
    import json
    try:
        st = json.loads((_JROOT / "data" / "briefing.json").read_text(
            encoding="utf-8"))
        return {"last_sent": st.get("last_sent"),
                "attempts": st.get("attempts", [])}
    except Exception:
        return {"last_sent": None, "attempts": []}


def health_today(day: str) -> dict:
    import json
    rows = []
    for line in _read(_JROOT / "logs" / "health.jsonl").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("date") == day:
            rows.append(row)
    if not rows:
        return {"ran": False}
    last = rows[-1]
    return {"ran": True, "ok": last.get("ok"),
            "notified": last.get("notified", None),
            "failures": last.get("failures", [])}


def jarvis2_voice_lines() -> dict:
    ok, fail, motives = [], [], {}
    for line in _read(_JROOT / "logs" / "jarvis.log").splitlines():
        if "briefing voice" not in line:
            continue
        m = re.match(r"\[(\d\d:\d\d:\d\d)\]", line)
        hhmm = m.group(1)[:5] if m else "??:??"
        if "ok=True" in line:
            ok.append(hhmm)
        elif "ok=False" in line:
            fail.append(hhmm)
            mo = re.search(r"motivo=([^\n]{1,120})", line)
            key = (mo.group(1)[:80] if mo else "sin-motivo-en-log"
                   "(codigo anterior a la correccion)")
            motives[key] = motives.get(key, 0) + 1
    return {"ok": ok, "fail": fail, "motives": motives}


def v1_fires(day: str) -> list:
    out = []
    for line in _read(V1_SCHED).splitlines():
        if day in line and ("morning_0755" in line or "briefing_0900" in line
                            or "Morning voice enviado" in line
                            or "Briefing voice enviado" in line):
            out.append(line[:160])
    return out


def v2_fires(day: str) -> list:
    out = []
    for line in _read(V2_MAIN).splitlines():
        if day in line and "briefing" in line.lower() and \
                ("executed': True" in line or '"executed": true' in line
                 or "announce" in line.lower()):
            out.append(line[:160])
    return out


def pollers() -> list:
    found = []
    try:
        import subprocess
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
             "Select-Object -ExpandProperty CommandLine"],
            capture_output=True, text=True, timeout=30)
        for line in ps.stdout.splitlines():
            if "telegram" in line.lower() and "listener" not in line.lower():
                found.append(line.strip()[:120])
            if "telegram_listener" in line:
                found.append("V1-LISTENER-VIVO: " + line.strip()[:120])
    except Exception as e:
        found.append(f"no se pudo listar: {e}")
    return found


def main() -> int:
    day = today()
    print(f"Fecha (Europe/Rome): {day}")
    st = jarvis2_state()
    print(f"jarvis2 briefing.json last_sent: {st['last_sent']}")
    if st["attempts"]:
        print(f"  intentos con backoff hoy: {len(st['attempts'])}")
    h = health_today(day)
    if h.get("ran"):
        print(f"salud 07:30: corrio ok={h.get('ok')} "
              f"avisado={h.get('notified')}")
    else:
        print("salud 07:30: aun no corre hoy (o sin registro)")
    v = jarvis2_voice_lines()
    print(f"audios briefing ok (jarvis.log SIN fecha: acumulado, "
          f"informativo): {len(v['ok'])}")
    print(f"intentos briefing fallidos (acumulado): {len(v['fail'])}")
    for mot, n in sorted(v["motives"].items(), key=lambda kv: -kv[1])[:6]:
        print(f"  motivo x{n}: {mot}")
    v1 = v1_fires(day)
    print(f"V1 scheduler disparos hoy: {len(v1)}")
    v2 = v2_fires(day)
    print(f"V2 briefing ejecutados hoy: {len(v2)}")
    pl = pollers()
    print(f"pollers Telegram vivos: {len(pl)}")
    # --- Veredicto (la marca manda; el log no tiene fecha) ---
    if st["last_sent"] == day:
        print(f"BRIEFING: ENVIADO hoy (marca {day}).")
        return 0
    print("BRIEFING: NO ENVIADO hoy. Por qué:")
    print(f"  - briefing.json sigue en {st['last_sent']} (la marca solo se "
          "pone tras ok:true de Telegram).")
    if v["fail"]:
        top = sorted(v["motives"].items(), key=lambda kv: -kv[1])
        print(f"  - intentos fallidos acumulados: {len(v['fail'])}; "
              f"motivo principal: {top[0][0] if top else '?'}")
    else:
        print("  - sin intentos registrados "
              "(poller caído o fuera de ventana).")
    if v1:
        print(f"  - V1 disparó {len(v1)} vez/veces (debía estar muerto).")
    if v2:
        print("  - V2 ejecutó briefing (fase A debía bloquearlo).")
    if len([p for p in pl if not p.startswith("V1-LISTENER")]) != 1:
        print("  - no hay exactamente 1 poller jarvis2.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
