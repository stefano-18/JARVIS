"""automejora.py — AUTOMEJORA de JARVIS desde Telegram (fase 9).

Flujo: "mejora: X" (solo usuario autorizado) -> worktree
{{HOME}}/automejora/<fecha>-<slug> rama mejora/<slug> -> el codigo
se escribe SOLO ahi -> guardarrailes en codigo + tests (max 3 intentos)
-> resumen a Telegram -> "aprobar <id>" / "rechazar <id>" (24 h = no)
-> merge + reinicio servicio afectado + salud; si falla: revert + aviso.

Uso (lo invoca el agente del gateway o un humano):
  automejora.py proponer --user <tgid> --chat <chatid> --texto "mejora: ..."
  automejora.py verificar <id>          # guardarrailes + tests (1 intento)
  automejora.py solicitar <id>           # manda resumen a Telegram
  automejora.py aprobar --user <tgid> <id>
  automejora.py rechazar --user <tgid> <id>
  automejora.py deshacer --user <tgid> <id>
  automejora.py lista | barrer

PROHIBIDO en codigo (no solo en el prompt): ver _BLOQ_*.
"""
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path("{{HOME}}/automejora")
STORE = BASE / "propuestas.json"
HIST = BASE / "historial.log"
ALLOW = BASE / "allowlist.txt"
REPOS = {"jarvis2": Path("{{HOME}}/jarvis2"),
         "openjarvis": Path("{{HOME}}/OpenJarvis")}
SERVICIO = {"jarvis2": "jarvis2.service",
            "openjarvis": "jarvis-oj.service"}
MAX_DIA = 10
MAX_INTENTOS = 3

_BLOQ_ARCHIVOS = [r"(^|/)\.env(\.|$)", r"\.openclaw", r"backup-pass",
                  r"sudoers", r"sshd_config", r"/etc/systemd",
                  r"/etc/ssh", r"ufw", r"iptables"]
_BLOQ_LINEAS = [r"mark\.skip", r"mark\.skipif", r"apt(-get)?\s+install",
                r"systemctl", r"\bufw\b", r"iptables", r"nft\s",
                r"rm\s+-rf\s+/", r"shutdown", r"reboot", r"poweroff",
                r"0\.0\.0\.0", r"chmod\s+777", r"chmod\s+[0-7]*s",
                r"eval\(.*request", r"exec\(.*request",
                r"\.env\b", r"\.openclaw", r"backup-pass", r"telegram-token",
                r"sudoers", r"\.ssh/", r"id_rsa",
                r"os\.environ\s*\[.*(KEY|TOKEN|SECRET)",
                r"getenv\(.*(KEY|TOKEN|SECRET)"]
_PROV_OK = ["googleapis.com", "api.groq.com", "api.mistral.ai",
            "openrouter.ai", "api.openai.com", "api.anthropic.com",
            "{{RED}}.", "127.0.0.1", "localhost"]


def _log(msg: str) -> None:
    BASE.mkdir(exist_ok=True)
    with HIST.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def _load() -> dict:
    if STORE.exists():
        return json.loads(STORE.read_text(encoding="utf-8"))
    return {"items": []}


def _save(d: dict) -> None:
    BASE.mkdir(exist_ok=True)
    STORE.write_text(json.dumps(d, indent=1, ensure_ascii=False),
                     encoding="utf-8")


def _autorizado(tgid: str) -> bool:
    try:
        ids = {l.strip() for l in ALLOW.read_text().split() if l.strip()}
    except FileNotFoundError:
        ids = set()
    return str(tgid) in ids


def _run(cmd: list, cwd=None, timeout=300) -> tuple:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)[-3000:]


def _tg(token_path: Path, chat: str, texto: str) -> str:
    tok = Path(token_path).read_text(encoding="utf-8").strip()
    body = json.dumps({"chat_id": chat, "text": texto[:3500]}).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + tok + "/sendMessage", data=body,
        headers={"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return str(r.get("result", {}).get("message_id", "?"))


def _slug(texto: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", texto.lower())[:40].strip("-")
    return s or "mejora"


def cmd_proponer(args) -> int:
    if not _autorizado(args.user):
        _log(f"IGNORADO proponer de usuario no autorizado")
        print("IGNORADO: usuario no autorizado (anotado)")
        return 2
    d = _load()
    hoy = datetime.now().strftime("%Y%m%d")
    n_hoy = sum(1 for i in d["items"]
                if i["id"].startswith(f"M-{hoy}") and i["estado"] != "descartada")
    if n_hoy >= MAX_DIA:
        _log(f"LIMITE {args.user}: {MAX_DIA}/dia alcanzado")
        print(f"LIMITE: maximo {MAX_DIA} mejoras/dia")
        return 3
    texto = args.texto
    if texto.lower().startswith("mejora:"):
        texto = texto[7:].strip()
    slug = _slug(texto)
    mid = f"M-{hoy}-{n_hoy + 1:02d}"
    wdir = BASE / f"{hoy}-{slug}"
    if wdir.exists():
        wdir = BASE / f"{hoy}-{slug}-{n_hoy + 1}"
    repos = [r for r in (args.repo or "jarvis2").split(",") if r in REPOS]
    info = {}
    for r in repos:
        repo = REPOS[r]
        rc, rama_base = _run(["git", "branch", "--show-current"], cwd=repo)
        rama_base = rama_base.strip()
        _run(["git", "worktree", "add", "-b", f"mejora/{slug}", str(wdir / r),
              rama_base], cwd=repo)
        rc, sha = _run(["git", "rev-parse", "HEAD"], cwd=repo)
        info[r] = {"rama_base": rama_base, "base_sha": sha.strip(),
                   "rama": f"mejora/{slug}"}
    d["items"].append({"id": mid, "slug": slug, "texto": texto,
                       "user": str(args.user), "chat": str(args.chat),
                       "repos": repos, "info": info,
                       "wdir": str(wdir), "estado": "trabajo",
                       "intentos": 0, "creada": time.time(),
                       "merge": None})
    _save(d)
    _log(f"{mid} propuesta por {args.user}: {texto[:80]}")
    print(f"ID: {mid}")
    print(f"WORKTREE: {wdir} (trabajar SOLO ahi)")
    return 0


def _item(d: dict, mid: str) -> dict:
    for i in d["items"]:
        if i["id"] == mid:
            return i
    raise SystemExit(f"no existe {mid}")


def _base(it: dict, r: str) -> str:
    return it["info"][r].get("base_sha") or it["info"][r]["rama_base"]


def _guardarrailes(it: dict) -> list:
    viol = []
    for r in it["repos"]:
        repo = REPOS[r]
        wd = Path(it["wdir"]) / r
        rc, diff = _run(["git", "diff", "--name-only", _base(it, r)],
                        cwd=wd)
        for f in diff.split():
            if any(re.search(p, f) for p in _BLOQ_ARCHIVOS):
                viol.append(f"{r}:{f} ruta prohibida")
            if re.match(r"tests/test_.*", f):
                rc2, st = _run(["git", "status", "--porcelain", f], cwd=wd)
                if st.strip().startswith("D"):
                    viol.append(f"{r}:{f} borrar tests prohibido")
        rc, patch = _run(["git", "diff", "-U0", _base(it, r)],
                         cwd=wd)
        for line in patch.splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            body = line[1:]
            if any(re.search(p, body) for p in _BLOQ_LINEAS):
                viol.append(f"{r}: linea prohibida: {body[:90]}")
            for m in re.finditer(r"https?://([A-Za-z0-9.\-]+)", body):
                if not any(p in m.group(1) for p in _PROV_OK):
                    viol.append(f"{r}: red fuera de proveedores: {m.group(1)}")
    return viol


def _tests(repo: str, wdir: str) -> tuple:
    wd = str(Path(wdir) / repo)
    if repo == "jarvis2":
        import os
        e = dict(os.environ, PYTHONPATH=wd)
        p = subprocess.run(["{{HOME}}/jarvis2/.venv/bin/python",
                            "-m", "pytest", "tests", "-q"],
                           cwd=wd, capture_output=True, text=True,
                           timeout=600, env=e)
        return p.returncode, (p.stdout + p.stderr)[-3000:]
    env = {"PATH": "{{HOME}}/.local/bin:{{HOME}}/.cargo/bin:"
                   + "/usr/bin:/bin"}
    import os
    e = dict(os.environ, **env)
    import os
    e = dict(os.environ, **env)
    p = subprocess.run(["uv", "run", "pytest", "tests/memory",
                        "tests/traces", "-q"],
                       cwd=str(Path(wdir) / "openjarvis"),
                       capture_output=True, text=True, timeout=600, env=e)
    return p.returncode, (p.stdout + p.stderr)[-3000:]


def cmd_verificar(args) -> int:
    d = _load()
    it = _item(d, args.id)
    if it["estado"] not in ("trabajo", "fallo-test"):
        print(f"estado {it['estado']}: nada que verificar")
        return 1
    it["intentos"] += 1
    viol = _guardarrailes(it)
    if viol:
        it["estado"] = "bloqueada"
        _save(d)
        _log(f"{it['id']} BLOQUEADA: {viol[0]}")
        print("BLOQUEADA:")
        [print(" -", v) for v in viol[:10]]
        return 4
    fails = []
    for r in it["repos"]:
        rc, out = _tests(r, it["wdir"])
        tail = [l for l in out.splitlines()
                if "passed" in l or "failed" in l][-3:]
        print(f"TESTS {r}: rc={rc} {' | '.join(tail)}")
        if rc != 0:
            fails.append(r)
    if fails:
        it["estado"] = "fallo-test"
        _save(d)
        _log(f"{it['id']} fallo-test intento {it['intentos']}: {fails}")
        if it["intentos"] >= MAX_INTENTOS:
            it["estado"] = "descartada"
            _save(d)
            _log(f"{it['id']} DESCARTADA tras {MAX_INTENTOS} intentos")
            print(f"DESCARTADA tras {MAX_INTENTOS} intentos (avisar usuario)")
        return 5
    it["estado"] = "lista"
    _save(d)
    _log(f"{it['id']} lista para aprobacion")
    print("LISTA para solicitar aprobacion")
    return 0


def _resumen(it: dict) -> str:
    tot_a = tot_d = 0
    det = []
    for r in it["repos"]:
        wd = Path(it["wdir"]) / r
        rc, st = _run(["git", "diff", "--stat", _base(it, r)],
                      cwd=wd)
        files = [l.strip() for l in st.splitlines() if "|" in l]
        a = d = 0
        for l in files:
            m = re.search(r"\|\s*(\d+)\s*([+\-]+)?", l)
        rc, num = _run(["git", "diff", "--numstat", _base(it, r)],
                       cwd=wd)
        for l in num.splitlines():
            p = l.split()
            if len(p) == 3:
                a += int(p[0]) if p[0].isdigit() else 0
                dd = int(p[1]) if p[1].isdigit() else 0
                d += dd
        tot_a += a
        tot_d += d
        det.append(f"{r}: {len(files)} archivos")
    return (f"Mejora {it['id']}: {it['texto'][:120]}\n"
            f"Cambia: {'; '.join(det)} (+{tot_a}/-{tot_d})\n"
            f"Tests: pasados (verificado {it['intentos']} intento(s))\n"
            f"Responde \"aprobar {it['id']}\" o \"rechazar {it['id']}\" "
            f"(24 h = rechazado).")


def cmd_solicitar(args) -> int:
    d = _load()
    it = _item(d, args.id)
    if it["estado"] != "lista":
        print(f"estado {it['estado']}: verifica primero")
        return 1
    it["estado"] = "pendiente"
    it["solicitada"] = time.time()
    _save(d)
    mid = _tg(Path("{{HOME}}/.openclaw/telegram-token"), it["chat"],
              _resumen(it))
    _log(f"{it['id']} solicitud enviada (msg {mid})")
    print(f"SOLICITUD enviada (msg {mid}). ID para aprobar: {it['id']}")
    return 0


def _caducada(it: dict) -> bool:
    return time.time() - it.get("solicitada", time.time()) > 24 * 3600


def _restart(svc: str) -> bool:
    rc, _ = _run(["sudo", "-n", "/usr/bin/systemctl", "restart", svc],
                 timeout=60)
    return rc == 0


def _revertir(repo: Path, sha: str) -> bool:
    rc, _ = _run(["git", "revert", "-m", "1", "--no-edit", sha], cwd=repo,
                 timeout=120)
    return rc == 0


def _salud() -> dict:
    out = {}
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=15)
        out["8000"] = r.status == 200
    except Exception:
        out["8000"] = False
    try:
        r = urllib.request.urlopen("http://127.0.0.1:18789/", timeout=15)
        out["gateway"] = r.status == 200
    except Exception:
        out["gateway"] = False
    import socket
    for p in (8765, 18765):
        try:
            s = socket.create_connection(("127.0.0.1", p), timeout=5)
            s.close()
            out[str(p)] = True
        except OSError:
            out[str(p)] = False
    return out


def cmd_aprobar(args) -> int:
    if not _autorizado(args.user):
        _log("IGNORADO aprobar de no autorizado")
        print("IGNORADO")
        return 2
    d = _load()
    it = _item(d, args.id)
    if it["estado"] != "pendiente":
        print(f"estado {it['estado']}: nada que aprobar")
        return 1
    if _caducada(it):
        it["estado"] = "rechazada"
        _save(d)
        _log(f"{it['id']} caducada (>24h) = rechazada")
        print("CADUCADA (>24 h): rechazada")
        return 6
    merges = []
    for r in it["repos"]:
        repo = REPOS[r]
        base = it["info"][r]["rama"]
        rc, _ = _run(["git", "merge", "--no-ff", "-m",
                      f"{it['id']}: {it['texto'][:60]}", base], cwd=repo)
        if rc != 0:
            print(f"MERGE fallo en {r}")
            return 7
        rc, sha = _run(["git", "rev-parse", "HEAD"], cwd=repo)
        merges.append((r, sha.strip()))
    it["merge"] = merges
    it["estado"] = "aplicada"
    _save(d)
    for r, _s in merges:
        ok = _restart(SERVICIO[r])
        _log(f"{it['id']} merge {r} restart={ok}")
    time.sleep(120)
    time.sleep(15)
    s = _salud()
    if not all(s.values()):
        for r, sha in merges:
            ok = _revertir(REPOS[r], sha)
            _restart(SERVICIO[r])
            _log(f"{it['id']} rollback {r} revert={ok}")
        it["estado"] = "revertida"
        _save(d)
        _log(f"{it['id']} ROLLBACK salud={s}")
        print(f"ROLLBACK: salud={s} (avisado en log)")
        return 8
    _log(f"{it['id']} APLICADA salud={s}")
    for r in it["repos"]:
        _run(["git", "worktree", "remove", "--force", str(Path(it["wdir"]) / r)],
             cwd=REPOS[r])
    print(f"APLICADA salud={s}")
    return 0


def cmd_rechazar(args) -> int:
    if not _autorizado(args.user):
        _log("IGNORADO rechazar de no autorizado")
        print("IGNORADO")
        return 2
    d = _load()
    it = _item(d, args.id)
    it["estado"] = "rechazada"
    _save(d)
    for r in it["repos"]:
        _run(["git", "worktree", "remove", "--force", str(Path(it["wdir"]) / r)],
             cwd=REPOS[r])
    _log(f"{it['id']} rechazada por {args.user}")
    print("RECHAZADA, worktree borrado")
    return 0


def cmd_deshacer(args) -> int:
    if not _autorizado(args.user):
        _log("IGNORADO deshacer de no autorizado")
        print("IGNORADO")
        return 2
    d = _load()
    it = _item(d, args.id)
    if it["estado"] != "aplicada" or not it.get("merge"):
        print("solo se deshacen mejoras aplicadas")
        return 1
    ok_all = True
    for r, sha in it["merge"]:
        ok = _revertir(REPOS[r], sha)
        ok_all = ok_all and ok
        _restart(SERVICIO[r])
    if not ok_all:
        print("REVERT fallo (ver log); estado sin cambios")
        _log(f"{it['id']} deshacer FALLO revert")
        return 9
    it["estado"] = "deshecha"
    _save(d)
    _log(f"{it['id']} DESHECHA por {args.user}")
    time.sleep(20)
    print(f"DESHECHA salud={_salud()}")
    return 0


def cmd_lista(_a) -> int:
    d = _load()
    for it in d["items"][-15:]:
        print(f"{it['id']} [{it['estado']}] {it['texto'][:70]}")
    return 0


def cmd_barrer(_a) -> int:
    d = _load()
    n = 0
    for it in d["items"]:
        if it["estado"] == "pendiente" and _caducada(it):
            it["estado"] = "rechazada"
            n += 1
    _save(d)
    print(f"caducadas: {n}")
    return 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="automejora")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("proponer")
    p.add_argument("--user", required=True)
    p.add_argument("--chat", required=True)
    p.add_argument("--texto", required=True)
    p.add_argument("--repo", default="jarvis2")
    v = sub.add_parser("verificar")
    v.add_argument("id")
    s = sub.add_parser("solicitar")
    s.add_argument("id")
    for n in ("aprobar", "rechazar", "deshacer"):
        q = sub.add_parser(n)
        q.add_argument("--user", required=True)
        q.add_argument("id")
    sub.add_parser("lista")
    sub.add_parser("barrer")
    a = ap.parse_args()
    return {"proponer": cmd_proponer, "verificar": cmd_verificar,
            "solicitar": cmd_solicitar, "aprobar": cmd_aprobar,
            "rechazar": cmd_rechazar, "deshacer": cmd_deshacer,
            "lista": cmd_lista, "barrer": cmd_barrer}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
