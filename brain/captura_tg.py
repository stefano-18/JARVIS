#!/usr/bin/env python3
"""JARVIS (arreglo 66): manda al señor, SOLO a su propio chat de Telegram, una foto de las pantallas del PC.
Uso: captura_tg.py ["texto opcional"]"""
import io, json, os, re, sys, urllib.request, uuid

HOME = os.path.expanduser("~")
VENV = os.path.join(HOME, "jarvis2/.venv/bin/python")
if os.path.exists(VENV) and os.path.realpath(sys.executable) != os.path.realpath(VENV):
    os.execv(VENV, [VENV] + sys.argv)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys_argv, sys.argv = sys.argv, ["pantalla.py"]
import pantalla as P  # noqa: E402


def _env():
    d = {}
    for l in open(os.path.join(HOME, ".hermes/.env"), encoding="utf-8"):
        m = re.match(r"\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*['\"]?([^'\"\n]*)", l)
        if m:
            d[m.group(1)] = m.group(2).strip()
    return d


def main(texto):
    e = _env()
    token = next((v for k, v in e.items() if "TELEGRAM" in k and "TOKEN" in k and v), "")
    chat = (e.get("TELEGRAM_HOME_CHANNEL") or e.get("TELEGRAM_ALLOWED_USERS", "")).split(",")[0].strip()
    if not token or not chat:
        print("No encuentro el bot o el chat del señor en la configuración.")
        return 1
    img = P._img(0)
    if img.size[0] > 3200:
        img = img.resize((3200, round(img.size[1] * 3200 / img.size[0])))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    b = uuid.uuid4().hex
    partes = [(f'--{b}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat}\r\n').encode(),
              (f'--{b}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{texto}\r\n').encode(),
              (f'--{b}\r\nContent-Disposition: form-data; name="photo"; filename="pantallas.jpg"\r\n'
               'Content-Type: image/jpeg\r\n\r\n').encode() + buf.getvalue() + b"\r\n",
              f"--{b}--\r\n".encode()]
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendPhoto", b"".join(partes),
                                 {"Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            ok = json.load(r).get("ok")
    except Exception as ex:  # noqa: BLE001
        print(f"No he podido mandar la captura ({str(ex).replace(token, '***')[:100]}).")
        return 1
    print("Captura enviada a su Telegram, señor." if ok else "Telegram no aceptó la captura.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(" ".join(sys_argv[1:]).strip() or "Así están sus pantallas ahora, señor."))
