#!/usr/bin/env python3
"""Calendar y Gmail para JARVIS. Salida JSON de una linea."""
import base64, datetime as dt, json, os, sys
from email.mime.text import MIMEText

CRED = os.path.expanduser("~/.config/jarvis/google-credentials.json")
TOKEN = os.path.expanduser("~/.config/jarvis/google-token.json")
SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/gmail.modify"]


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(0 if obj.get("ok") else 1)


def creds(interactive=False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    c = Credentials.from_authorized_user_file(TOKEN, SCOPES) if os.path.exists(TOKEN) else None
    if c and c.expired and c.refresh_token:
        c.refresh(Request())
    if not c or not c.valid:
        if not interactive:
            out({"ok": False, "error": "Google no esta conectado. Hay que repetir la autorizacion."})
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(CRED, SCOPES)
        c = flow.run_local_server(port=8899, open_browser=False, prompt="consent",
                                  authorization_prompt_message="Abra este enlace en el navegador del PC:\n{url}\n",
                                  success_message="Listo. JARVIS ya tiene acceso. Puede cerrar esta pestaña.")
    with open(TOKEN, "w") as f:
        f.write(c.to_json())
    os.chmod(TOKEN, 0o600)
    return c


def svc(name, ver):
    from googleapiclient.discovery import build
    return build(name, ver, credentials=creds(), cache_discovery=False)


def tz():
    return dt.datetime.now().astimezone().tzinfo


def cal_list(days="7"):
    now = dt.datetime.now(tz())
    r = svc("calendar", "v3").events().list(calendarId="primary", timeMin=now.isoformat(),
        timeMax=(now + dt.timedelta(days=int(days))).isoformat(), singleEvents=True, orderBy="startTime", maxResults=50).execute()
    ev = [{"id": e["id"], "titulo": e.get("summary", "(sin titulo)"),
           "inicio": e["start"].get("dateTime", e["start"].get("date")), "lugar": e.get("location", "")} for e in r.get("items", [])]
    out({"ok": True, "eventos": ev})


def cal_add(titulo, inicio, minutos="60", descripcion=""):
    start = dt.datetime.fromisoformat(inicio)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz())
    end = start + dt.timedelta(minutes=int(minutos))
    e = svc("calendar", "v3").events().insert(calendarId="primary", body={
        "summary": titulo, "description": descripcion,
        "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}).execute()
    out({"ok": True, "id": e["id"], "titulo": titulo, "inicio": start.isoformat()})


def cal_del(event_id):
    svc("calendar", "v3").events().delete(calendarId="primary", eventId=event_id).execute()
    out({"ok": True, "borrado": event_id})


def mail_list(query="is:unread in:inbox", n="10"):
    g = svc("gmail", "v1")
    ids = g.users().messages().list(userId="me", q=query, maxResults=int(n)).execute().get("messages", [])
    res = []
    for m in ids:
        d = g.users().messages().get(userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"]).execute()
        h = {x["name"]: x["value"] for x in d["payload"].get("headers", [])}
        res.append({"id": m["id"], "de": h.get("From", ""), "asunto": h.get("Subject", ""), "fecha": h.get("Date", ""), "resumen": d.get("snippet", "")})
    out({"ok": True, "correos": res})


def _body(p):
    if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(p["body"]["data"]).decode("utf-8", "replace")
    for sub in p.get("parts", []) or []:
        t = _body(sub)
        if t:
            return t
    return ""


def mail_read(msg_id):
    d = svc("gmail", "v1").users().messages().get(userId="me", id=msg_id, format="full").execute()
    h = {x["name"]: x["value"] for x in d["payload"].get("headers", [])}
    out({"ok": True, "de": h.get("From", ""), "asunto": h.get("Subject", ""), "texto": _body(d["payload"])[:6000]})


def _raw(to, subject, body):
    m = MIMEText(body, "plain", "utf-8")
    m["to"], m["subject"] = to, subject
    return base64.urlsafe_b64encode(m.as_bytes()).decode()


def mail_draft(to, subject, body):
    d = svc("gmail", "v1").users().drafts().create(userId="me", body={"message": {"raw": _raw(to, subject, body)}}).execute()
    out({"ok": True, "borrador": d["id"]})


def _visto_bueno():
    p = os.path.expanduser("~/jarvis-control/.visto-bueno")
    try:  # arreglo 86: firmada con firma.key, reciente (5 min) y del propio usuario
        import hashlib, hmac
        st = os.stat(p)
        ms, firma = open(p).read().strip().split(":", 1)
        k = open(os.path.expanduser("~/.config/jarvis/firma.key")).read().strip().encode()
        buena = hmac.compare_digest(firma, hmac.new(k, ms.encode(), hashlib.sha256).hexdigest())
        ok = buena and st.st_uid == os.getuid() and (dt.datetime.now().timestamp() * 1000 - int(ms)) < 5 * 60 * 1000
    except Exception:
        ok = False
    if ok:
        os.remove(p)
    return ok


def mail_send(to, subject, body):
    if not _visto_bueno():
        out({"ok": False, "error": "Falta el visto bueno del usuario. Ensena destinatario, asunto y resumen y espera su si."})
    m = svc("gmail", "v1").users().messages().send(userId="me", body={"raw": _raw(to, subject, body)}).execute()
    out({"ok": True, "enviado": m["id"]})


CMDS = {"cal-list": cal_list, "cal-add": cal_add, "cal-del": cal_del, "mail-list": mail_list,
        "mail-read": mail_read, "mail-draft": mail_draft, "mail-send": mail_send}

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        creds(interactive=True)
        print("AUTORIZADO OK")
        sys.exit(0)
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        out({"ok": False, "error": "uso: auth|" + "|".join(CMDS)})
    try:
        CMDS[sys.argv[1]](*sys.argv[2:])
    except TypeError:
        out({"ok": False, "error": "faltan o sobran datos para " + sys.argv[1]})
    except Exception as e:
        out({"ok": False, "error": str(e)[:300]})
