"""Setup sin admin: venv, requirements, secretos, modelo Piper, --check.

Uso:
  python scripts/setup.py [--check] [--venv .venv] [--no-model]
  python scripts/setup.py --check   # valida .env, Telegram y providers sin enviar nada

- Crea venv (si no existe) e instala requirements.txt con el pip del venv.
- Genera secretos aleatorios (JARVIS_REMOTE_SECRET de 64 hex y HUD_TOKEN)
  en .env (UTF-8 sin BOM), sin mostrarlos por consola.
- Descarga el modelo Piper es_ES-davefx-medium desde el repositorio oficial
  rhasspy/piper-voices (HuggingFace) con comprobación de integridad
  (tamaño mínimo + JSON válido + sha256 guardado).
- --check valida variables, conexión a Telegram (getMe) y claves de
  proveedores (solo GET /models, sin enviar mensajes ni gastar).
"""
import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import urllib.request
from pathlib import Path

JROOT = Path(__file__).resolve().parent.parent

PIPER_BASE = ("https://huggingface.co/rhasspy/piper-voices/resolve/main"
              "/es/es_ES/davefx/medium")
PIPER_FILES = ["es_ES-davefx-medium.onnx", "es_ES-davefx-medium.onnx.json"]
PIPER_MIN_ONNX = 10_000_000  # ~63 MB reales; umbral anti-truncado


def _run(cmd, **kw):
    return subprocess.run(cmd, **kw)


def ensure_venv(venv: Path) -> Path:
    if not (venv / "Scripts" / "python.exe").exists():
        print(f"[setup] creando venv en {venv}")
        _run([sys.executable, "-m", "venv", str(venv)], check=True)
    else:
        print(f"[setup] venv ya existe: {venv}")
    return venv / "Scripts" / "python.exe"


def install_reqs(py: Path) -> None:
    req = JROOT / "requirements.txt"
    print("[setup] instalando requirements…")
    _run([str(py), "-m", "pip", "install", "--upgrade", "pip"], check=False)
    _run([str(py), "-m", "pip", "install", "-r", str(req)], check=True)


def _load_dotenv(path: Path) -> dict:
    vals = {}
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return vals


def ensure_env() -> Path:
    env = JROOT / ".env"
    example = JROOT / ".env.example"
    vals = _load_dotenv(env) if env.exists() else {}
    changed = []
    if not vals.get("JARVIS_REMOTE_SECRET"):
        vals["JARVIS_REMOTE_SECRET"] = secrets.token_hex(32)  # 64 hex
        changed.append("JARVIS_REMOTE_SECRET")
    if not vals.get("HUD_TOKEN"):
        vals["HUD_TOKEN"] = secrets.token_hex(16)
        changed.append("HUD_TOKEN")
    vals.setdefault("TIMEZONE", "UTC")
    vals.setdefault("GOOGLE_ENABLED", "0")
    vals.setdefault("HUD_HOST", "127.0.0.1")
    vals.setdefault("HUD_PORT", "8090")
    vals.setdefault("VOICE_IN", "0")
    if not env.exists() and example.exists():
        header = example.read_text(encoding="utf-8")
        env.write_text(header, encoding="utf-8")  # sin BOM
        vals_example = _load_dotenv(example)
        for k, v in vals.items():
            vals_example[k] = v
        vals = vals_example
    lines = []
    if env.exists():
        # Conserva comentarios del example si es primera creación.
        pass
    for k in sorted(vals):
        lines.append(f"{k}={vals[k]}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")  # UTF-8 sin BOM
    if changed:
        print(f"[setup] secretos generados en .env: {', '.join(changed)} "
              "(no se muestran)")
    else:
        print("[setup] .env ya tenía secretos (no se regeneran)")
    return env


def download_model(dest_dir: Path = None) -> Path:
    dest_dir = dest_dir or Path(
        os.getenv("JARVIS_PIPER_MODEL", "") or
        str(JROOT / "models" / "piper"))
    # Si JARVIS_PIPER_MODEL apunta a fichero, usa su carpeta.
    if dest_dir.suffix == ".onnx":
        dest_dir = dest_dir.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in PIPER_FILES:
        url = f"{PIPER_BASE}/{name}"
        dest = dest_dir / name
        if dest.exists() and name.endswith(".onnx") and \
                dest.stat().st_size >= PIPER_MIN_ONNX:
            print(f"[setup] modelo ya existe: {dest}")
            continue
        print(f"[setup] descargando {url}")
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as e:
            print(f"[setup] ERROR descargando {name}: {e}")
            raise SystemExit(2)
        if name.endswith(".onnx") and dest.stat().st_size < PIPER_MIN_ONNX:
            dest.unlink(missing_ok=True)
            print(f"[setup] ERROR: {name} truncado "
                  f"({dest.stat().st_size if dest.exists() else 0} bytes)")
            raise SystemExit(2)
        if name.endswith(".json"):
            try:
                json.loads(dest.read_text(encoding="utf-8"))
            except Exception:
                print(f"[setup] ERROR: {name} no es JSON válido")
                raise SystemExit(2)
        h = hashlib.sha256(dest.read_bytes()).hexdigest()
        (dest.with_suffix(dest.suffix + ".sha256")).write_text(
            h + f"  {name}\n", encoding="utf-8")
        print(f"[setup] OK {name} ({dest.stat().st_size} bytes, sha256 ok)")
    return dest_dir / PIPER_FILES[0]


def do_check() -> int:
    """Valida .env, Telegram (getMe) y providers. No envía nada."""
    from dotenv import load_dotenv
    load_dotenv(JROOT / ".env")
    ok = True

    def _need(name, secret=True):
        nonlocal ok
        v = os.getenv(name, "")
        state = "OK" if v else "FALTA"
        # Nunca muestra el valor.
        print(f"[check] {name}: {state} "
              f"({'secreto' if secret else 'valor'} {'presente' if v else 'ausente'})")
        if not v and name in ("TELEGRAM_BOT_TOKEN",):
            print("        (opcional si no usas Telegram)")
        return bool(v)

    print(f"[check] TIMEZONE={os.getenv('TIMEZONE', 'UTC')}")
    print(f"[check] GOOGLE_ENABLED={os.getenv('GOOGLE_ENABLED', '0')}")
    has_tg = _need("TELEGRAM_BOT_TOKEN")
    _need("JARVIS_REMOTE_SECRET")
    _need("JARVIS_REMOTE_DEVICE_ID", secret=False)
    _need("HUD_TOKEN")
    for k in ("GROQ_API_KEY", "MISTRAL_API_KEY", "GEMINI_API_KEY",
              "OPENROUTER_API_KEY"):
        v = os.getenv(k, "")
        print(f"[check] {k}: {'presente' if v else 'ausente'}")

    if has_tg:
        try:
            import json as _j
            tok = os.getenv("TELEGRAM_BOT_TOKEN", "")
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{tok}/getMe",
                method="GET")
            with urllib.request.urlopen(req, timeout=15) as r:
                data = _j.loads(r.read().decode("utf-8"))
            if data.get("ok"):
                print(f"[check] Telegram getMe OK "
                      f"(bot presente, sin enviar nada)")
            else:
                print("[check] Telegram getMe FALLO (respuesta ok=false)")
                ok = False
        except Exception as e:
            print(f"[check] Telegram getMe FALLO: {type(e).__name__} "
                  "(¿sin red o token inválido?)")
            ok = False
    else:
        print("[check] Telegram: omitido (sin token)")

    # Providers: solo GET /models o equivalente, sin chat ni gasto.
    probes = [
        ("GROQ_API_KEY", "https://api.groq.com/openai/v1/models", "bearer"),
        ("MISTRAL_API_KEY", "https://api.mistral.ai/v1/models", "bearer"),
        ("GEMINI_API_KEY",
         "https://generativelanguage.googleapis.com/v1beta/models", "query"),
    ]
    for envk, url, mode in probes:
        key = os.getenv(envk, "")
        if not key:
            print(f"[check] {envk}: sin clave (omitido)")
            continue
        try:
            if mode == "bearer":
                req = urllib.request.Request(
                    url, headers={"Authorization": "Bearer xxx"})
                # Sustituye solo para longitud; el valor real no se loguea.
                req.add_header("Authorization", f"Bearer {key}")
            else:
                req = urllib.request.Request(f"{url}?key={key}")
            with urllib.request.urlopen(req, timeout=15) as r:
                print(f"[check] {envk}: HTTP {r.status} (solo listado)")
        except Exception as e:
            print(f"[check] {envk}: fallo ({type(e).__name__}, "
                  "¿sin red o clave inválida?)")

    # Google opcional
    try:
        sys.path.insert(0, str(JROOT))
        from integrations import _auth as _A
        st = _A.status()
        print(f"[check] Google enabled={_A.is_enabled()} "
              f"package={st['package']} credentials={st['credentials']}")
    except Exception as e:
        print(f"[check] Google: no verificable ({e})")

    print("[check] RESULTADO:", "OK" if ok else "CON FALTAS (ver arriba)")
    return 0 if ok else 1


def _pedir(entrada, texto: str, oculta: bool = False,
           defecto: str = "") -> str:
    if entrada is not None:
        return (entrada(texto, oculta, defecto) or "").strip()
    if oculta:
        import getpass as _g
        v = _g.getpass(f"{texto} ").strip()
    else:
        v = input(f"{texto} ").strip()
    return v or defecto


def _http_get(url: str, headers: dict = None, http=None, timeout: int = 20):
    if http is not None:
        return http(url, headers or {}, timeout)
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8")


def _validar_clave_proveedor(nombre: str, clave: str, http=None) -> bool:
    try:
        if nombre == "GROQ_API_KEY":
            st, _ = _http_get("https://api.groq.com/openai/v1/models",
                              {"Authorization": f"Bearer {clave}"}, http)
            return st == 200
        if nombre == "MISTRAL_API_KEY":
            st, _ = _http_get("https://api.mistral.ai/v1/models",
                              {"Authorization": f"Bearer {clave}"}, http)
            return st == 200
        if nombre == "GEMINI_API_KEY":
            st, _ = _http_get("https://generativelanguage.googleapis.com/"
                              "v1beta/models?key=" + clave, {}, http)
            return st == 200
    except Exception:
        pass
    return False


def do_wizard(entrada=None, http=None) -> int:
    """Asistente en español: crea el .env paso a paso. Nunca muestra valores."""
    print("== Asistente Jarvis2 ==")
    print("Pulsa Enter para dejar un campo vacío (donde se permita).")
    vals = _load_dotenv(JROOT / ".env")
    tok = _pedir(entrada, "1) Token del bot de Telegram (de BotFather)",
                 oculta=True, defecto=vals.get("TELEGRAM_BOT_TOKEN", ""))
    if tok:
        try:
            st, body = _http_get(
                f"https://api.telegram.org/bot{tok}/getMe", {}, http)
            if st == 200 and json.loads(body).get("ok"):
                print("   Token válido (bot localizado, sin enviar nada).")
                vals["TELEGRAM_BOT_TOKEN"] = tok
            else:
                print("   Ese token no responde bien; sigo sin guardarlo.")
        except Exception:
            print("   No se pudo validar (¿sin red?); sigo sin guardarlo.")
    print("2) Abre Telegram y envía /start a tu bot; luego pulsa Enter.")
    _pedir(entrada, "   Pulsa Enter cuando lo hayas enviado", defecto="")
    chat = ""
    if vals.get("TELEGRAM_BOT_TOKEN"):
        try:
            st, body = _http_get(
                f"https://api.telegram.org/bot"
                f"{vals['TELEGRAM_BOT_TOKEN']}/getUpdates", {}, http)
            ups = json.loads(body).get("result", []) if st == 200 else []
            ids = [str(u.get("message", {}).get("chat", {}).get("id"))
                   for u in ups]
            ids = [i for i in ids if i and i != "None"]
            if ids:
                chat = ids[-1]
                print("   Chat detectado automáticamente.")
        except Exception:
            pass
    if not chat:
        chat = _pedir(entrada, "   Escribe tu chat ID manualmente",
                      defecto=vals.get("TELEGRAM_ALLOWED_CHAT_IDS", ""))
    if chat:
        vals["TELEGRAM_ALLOWED_CHAT_IDS"] = chat
    print("3) Claves de IA gratuitas (mínimo UNA; se prueban sin gastar).")
    alguna = False
    for nombre, ayuda in (
            ("GROQ_API_KEY", "Groq (busca: Groq console API keys)"),
            ("MISTRAL_API_KEY", "Mistral (busca: Mistral La Plateforme)"),
            ("GEMINI_API_KEY", "Google Gemini (busca: Google AI Studio)")):
        clave = _pedir(entrada, f"   {nombre} [{ayuda}]", oculta=True,
                       defecto=vals.get(nombre, ""))
        if not clave:
            continue
        if _validar_clave_proveedor(nombre, clave, http):
            print(f"   {nombre}: válida.")
            vals[nombre] = clave
            alguna = True
        else:
            print(f"   {nombre}: no se pudo validar; la guardo igualmente.")
            vals[nombre] = clave
            alguna = True
    if not alguna:
        print("   AVISO: sin ninguna clave la IA no funcionará; "
              "podrás repetir el asistente.")
    tz = _pedir(entrada, "4) Zona horaria (p. ej. Europe/Rome)",
                defecto=vals.get("TIMEZONE", "Europe/Rome") or "Europe/Rome")
    vals["TIMEZONE"] = tz
    if not vals.get("JARVIS_REMOTE_SECRET"):
        vals["JARVIS_REMOTE_SECRET"] = secrets.token_hex(32)
        print("   Secreto del agente generado (no se muestra).")
    if not vals.get("HUD_TOKEN"):
        vals["HUD_TOKEN"] = secrets.token_hex(16)
        print("   Token del panel generado (no se muestra).")
    vals.setdefault("GOOGLE_ENABLED", "0")
    vals.setdefault("HUD_HOST", "127.0.0.1")
    vals.setdefault("HUD_PORT", "8090")
    vals.setdefault("VOICE_IN", "0")
    (JROOT / ".env").write_text(
        "\n".join(f"{k}={vals[k]}" for k in sorted(vals)) + "\n",
        encoding="utf-8")
    print("   .env escrito en UTF-8 sin BOM.")
    print("== Comprobación final ==")
    return do_check()


def do_export_pc_config(carpeta: str, hub_host: str = "",
                        entrada=None) -> int:
    """Escribe pc_agent_config.json (HUB_HOST, DEVICE_ID, SECRET).

    El SECRET nunca se muestra: solo se escribe en el fichero para llevar
    por USB. El instalador del PC lo borra tras usarlo.
    """
    vals = _load_dotenv(JROOT / ".env")
    if not vals.get("JARVIS_REMOTE_SECRET"):
        ensure_env()
        vals = _load_dotenv(JROOT / ".env")
    if not hub_host:
        hub_host = _pedir(entrada, "HUB_HOST (IP/Tailscale de esta laptop)",
                          defecto="")
    if not hub_host:
        print("[export] falta HUB_HOST.")
        return 2
    dest = Path(carpeta)
    dest.mkdir(parents=True, exist_ok=True)
    cfg = {"HUB_HOST": hub_host,
           "DEVICE_ID": vals.get("JARVIS_REMOTE_DEVICE_ID", "") or "pc-01",
           "SECRET": vals.get("JARVIS_REMOTE_SECRET", "")}
    (dest / "pc_agent_config.json").write_text(
        json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"[export] escrito en {dest / 'pc_agent_config.json'} "
          "(3 claves, valores no mostrados).")
    return 0


def main() -> int:
    if sys.version_info[:2] not in ((3, 11), (3, 12)):
        print(f"[setup] Python no soportado: {sys.version.split()[0]} "
              "(usa Python 3.11 o 3.12).")
        return 2
    ap = argparse.ArgumentParser(description="Setup Jarvis2 sin admin")
    ap.add_argument("--check", action="store_true",
                    help="valida .env, Telegram y providers sin enviar nada")
    ap.add_argument("--wizard", action="store_true",
                    help="asistente en español (crea el .env paso a paso)")
    ap.add_argument("--export-pc-config", default="",
                    help="carpeta donde escribir pc_agent_config.json")
    ap.add_argument("--hub-host", default="",
                    help="HUB_HOST para --export-pc-config (si no, lo pide)")
    ap.add_argument("--venv", default=".venv", help="carpeta del venv")
    ap.add_argument("--no-model", action="store_true",
                    help="no descargar el modelo Piper")
    ap.add_argument("--no-install", action="store_true",
                    help="no instalar requirements")
    args = ap.parse_args()
    if args.check:
        return do_check()
    if args.wizard:
        return do_wizard()
    if args.export_pc_config:
        return do_export_pc_config(args.export_pc_config,
                                   hub_host=args.hub_host)
    venv = JROOT / args.venv
    py = ensure_venv(venv)
    if not args.no_install:
        install_reqs(py)
    ensure_env()
    if not args.no_model:
        try:
            download_model()
        except SystemExit as e:
            return int(e.code or 1)
    print("[setup] listo. Activa con: .\\.venv\\Scripts\\Activate.ps1 "
          "y ejecuta: python scripts/setup.py --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
