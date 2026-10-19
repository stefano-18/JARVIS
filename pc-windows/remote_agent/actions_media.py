"""Acciones media.* y volume.* (FASE B2, MEDIUM, mockeadas en tests).

Manifiestos (identicos a la laptop):
  media.play_pause { } MEDIUM
  media.next { } MEDIUM
  media.previous { } MEDIUM
  volume.get { } MEDIUM
  volume.set {level: int 0-100} MEDIUM
  volume.mute {muted: bool} MEDIUM

Media via teclas multimedia Win32 (VK_MEDIA_*). Volumen via pycaw.
Detras del flag MEDIA_VOLUME=1 (0 = denegado con feature_disabled).
"""
import sys

_VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1}


def _err(code: str, msg: str, **extra) -> dict:
    msg = (msg or "").strip() or f"error desconocido ({code})"
    d = {"status": "error", "error": msg[:300], "code": code}
    d.update(extra)
    return d


def _media_key(which: str) -> dict:
    try:
        import win32api as _api  # type: ignore
    except Exception:
        _api = None  # type: ignore
    if _api is None:
        return _err("gui_unavailable", "win32api no disponible",
                    executed=False)
    vk = _VK.get(which)
    if vk is None:
        return _err("bad_param", f"media desconocido: {which}",
                    executed=False)
    try:
        _api.keybd_event(vk, 0, 0, 0)
        import time as _t
        _t.sleep(0.03)
        _api.keybd_event(vk, 0, 2, 0)
        return {"status": "ok", "media": which}
    except Exception as e:
        return _err("media_failed", f"media {which} fallo: {e}",
                    executed=False)


async def media_play_pause(params: dict, ctx: dict) -> dict:
    return _media_key("play_pause")


async def media_next(params: dict, ctx: dict) -> dict:
    return _media_key("next")


async def media_previous(params: dict, ctx: dict) -> dict:
    return _media_key("previous")


def _vol_iface():
    try:
        from pycaw.pycaw import AudioUtilities  # type: ignore
        from pycaw.api_endpointvolume import AudioEndpointVolume  # noqa
        speakers = AudioUtilities.GetSpeakers()
        from comtypes import CLSCTX_ALL as _CTX  # type: ignore
        from ctypes import cast, POINTER  # noqa
        return speakers
    except Exception as e:
        raise RuntimeError(f"pycaw no disponible: {e}")


async def volume_get(params: dict, ctx: dict) -> dict:
    try:
        from pycaw.pycaw import AudioUtilities
        from comtypes import CLSCTX_ALL
        from ctypes import cast, POINTER
        from pycaw.api_endpointvolume import IAudioEndpointVolume
        spk = AudioUtilities.GetSpeakers()
        iface = spk.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(iface, POINTER(IAudioEndpointVolume))
        level = int(round(float(vol.GetMasterVolumeLevelScalar()) * 100))
        muted = bool(vol.GetMute())
        return {"status": "ok", "level": level, "muted": muted}
    except Exception as e:
        return _err("volume_failed", f"volume.get fallo: {e}")


async def volume_set(params: dict, ctx: dict) -> dict:
    try:
        level = int(params.get("level"))
    except (TypeError, ValueError):
        return _err("bad_param", "level debe ser int 0-100")
    if not 0 <= level <= 100:
        return _err("bad_param", "level debe ser 0-100")
    try:
        from pycaw.pycaw import AudioUtilities
        from comtypes import CLSCTX_ALL
        from ctypes import cast, POINTER
        from pycaw.api_endpointvolume import IAudioEndpointVolume
        spk = AudioUtilities.GetSpeakers()
        iface = spk.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(iface, POINTER(IAudioEndpointVolume))
        vol.SetMasterVolumeLevelScalar(level / 100.0, None)
        return {"status": "ok", "level": level}
    except Exception as e:
        return _err("volume_failed", f"volume.set fallo: {e}")


async def volume_mute(params: dict, ctx: dict) -> dict:
    v = params.get("muted", True)
    if isinstance(v, str):
        muted = v.strip().lower() in ("1", "true", "yes", "on")
    else:
        muted = bool(v)
    try:
        from pycaw.pycaw import AudioUtilities
        from comtypes import CLSCTX_ALL
        from ctypes import cast, POINTER
        from pycaw.api_endpointvolume import IAudioEndpointVolume
        spk = AudioUtilities.GetSpeakers()
        iface = spk.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(iface, POINTER(IAudioEndpointVolume))
        vol.SetMute(1 if muted else 0, None)
        return {"status": "ok", "muted": bool(muted)}
    except Exception as e:
        return _err("volume_failed", f"volume.mute fallo: {e}")
