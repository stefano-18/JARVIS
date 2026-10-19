"""OAuth local Google (una vez por usuario/máquina).

1. Pon tus credenciales OAuth Desktop en config/google_credentials.json
   (Google Cloud Console -> APIs & Services -> Credentials).
2. Ejecuta:  python scripts/google_auth.py
3. Se abre el navegador: autoriza con tu cuenta de Google.
4. Se guarda config/google_token.json (git-ignorado, NUNCA commitear).

Scopes pedidos (ver integrations/): calendar.events + gmail.compose.
Para revocar: https://myaccount.google.com/permissions.
"""
import sys
from pathlib import Path

_JROOT = Path(__file__).resolve().parent.parent
if str(_JROOT) not in sys.path:
    sys.path.insert(0, str(_JROOT))

from integrations import _auth as A  # noqa: E402
from integrations import google_calendar as _CAL  # noqa: E402
from integrations import google_gmail as _GM  # noqa: E402


def main() -> int:
    try:
        import googleapiclient  # noqa: F401
    except ImportError:
        print("Falta paquete: pip install google-api-python-client "
              "google-auth-oauthlib")
        return 2
    if not A.CRED_PATH.exists():
        print(f"Falta {A.CRED_PATH}: descargalo de Google Cloud Console "
              "(OAuth client tipo Desktop).")
        return 2
    from google_auth_oauthlib.flow import InstalledAppFlow
    scopes = sorted(set(_CAL.SCOPES + _GM.SCOPES))
    print(f"Scopes: {', '.join(scopes)}")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(A.CRED_PATH), scopes)
    creds = flow.run_local_server(port=0)
    A.TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"OK: token guardado en {A.TOKEN_PATH} (no lo commitees).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
