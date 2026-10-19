"""jr_presence: {idle_seconds, session_locked, ts}. LOW, sin contenido
de pantalla ni teclado. Detras del flag PRESENCE=1 (apagado por defecto).
"""
import time


def get_idle_seconds() -> int:
    """Segundos desde ultima entrada (GetLastInputInfo). -1 si no disponible."""
    try:
        import ctypes
        from ctypes import wintypes

        class _LII(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT),
                        ("dwTime", wintypes.DWORD)]
        lii = _LII()
        lii.cbSize = ctypes.sizeof(lii)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            tick = ctypes.windll.kernel32.GetTickCount()
            return max(0, int((tick - int(lii.dwTime)) / 1000))
        return -1
    except Exception:
        return -1


def is_session_locked() -> bool:
    """True si la sesion esta bloqueada. False si no (o si no se sabe)."""
    try:
        import ctypes
        # 0x0101 = WTS_SESSIONSTATE_LOCK / WTS_SESSIONSTATE_UNLOCK via
        # WTSQuerySessionInformationW (WTS_SESSIONSTATE). Fallback simple:
        # OpenInputDesktop falla cuando la estacion esta bloqueada.
        try:
            h = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0100)
            if h:
                ctypes.windll.user32.CloseDesktop(h)
                return False
                # desktop abrio -> no bloqueada
        except Exception:
            pass
        # Si no pudimos abrir, intentamos GetForegroundWindow==0 como indicio.
        try:
            fg = ctypes.windll.user32.GetForegroundWindow()
            locked = int(fg or 0) == 0
            return bool(locked)
        except Exception:
            return False
    except Exception:
        return False


def make_presence_payload(idle_seconds: int = None,
                          session_locked: bool = None,
                          ts: int = None) -> dict:
    if idle_seconds is None:
        idle_seconds = get_idle_seconds()
    if session_locked is None:
        session_locked = is_session_locked()
    if ts is None:
        ts = int(time.time())
    try:
        idle_seconds = int(idle_seconds)
    except Exception:
        idle_seconds = -1
    return {"idle_seconds": idle_seconds,
            "session_locked": bool(session_locked), "ts": int(ts)}


def changed(a: dict, b: dict) -> bool:
    if not a or not b:
        return True
    return bool(a.get("idle_seconds") != b.get("idle_seconds")
                or a.get("session_locked") != b.get("session_locked"))
