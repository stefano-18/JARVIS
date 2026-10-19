"""Tests computer use: screen.capture, window.*, clipboard.* (todo mockeado)."""
import asyncio
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions
import actions_desktop as D
import policy


def run(coro):
    return asyncio.run(coro)


# --- Registro y riesgos ---

def test_manifests_registered_with_expected_risk():
    expect = {
        "screen.capture": "high",
        "window.list": "low",
        "window.focus": "high",
        "window.minimize": "high",
        "window.maximize": "high",
        "window.move": "high",
        "ui.click": "high",
        "ui.keypress": "high",
        "clipboard.read": "high",
        "clipboard.write": "high",
    }
    for name, risk in expect.items():
        assert name in actions.BY_NAME, f"falta {name}"
        assert actions.BY_NAME[name]["risk"] == risk, name


def test_high_requires_grant_clipboard_and_screen():
    for name in ("screen.capture", "clipboard.read", "clipboard.write",
                 "window.focus", "window.minimize", "window.maximize",
                 "window.move", "ui.click", "ui.keypress"):
        m = actions.BY_NAME[name]
        ok, why = policy.evaluate(m, {}, None, {}, "s3cr3t", set())
        assert ok is False and "concesion" in why, (name, why)


def test_window_list_low_passes():
    m = actions.BY_NAME["window.list"]
    ok, _ = policy.evaluate(m, {}, None, {}, "s3cr3t", set())
    assert ok is True


# --- screen.capture (shot mockeado) ---

def test_screen_capture_png_mock(monkeypatch):
    rgb = b"\x10\x20\x30" * (16 * 8)

    def fake_shot(monitor):
        assert monitor == 1
        return rgb, (16, 8)

    monkeypatch.setattr(D, "_shot_mss", fake_shot)
    res = run(D.screen_capture({"monitor": 1, "format": "png"}, {}))
    assert res["status"] == "ok", res
    assert (res["width"], res["height"]) == (16, 8)
    raw = base64.b64decode(res["data_b64"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n" and res["bytes"] == len(raw)


def test_screen_capture_bad_format():
    res = run(D.screen_capture({"format": "bmp"}, {}))
    assert res["status"] == "error"


def test_screen_capture_bad_monitor(monkeypatch):
    def boom(monitor):
        raise ValueError("monitor 9 fuera de rango (0..2)")
    if D._mss is None:
        monkeypatch.setattr(D, "_mss", object())
    monkeypatch.setattr(D, "_shot_mss", boom)
    res = run(D.screen_capture({"monitor": 9}, {}))
    assert res["status"] == "error" and "rango" in res["error"]
    assert res.get("code") == "bad_monitor", res


# --- ventanas (GUI stub) ---

class _Gui:
    def __init__(self):
        self.calls = []
        self.fg = 777

    def EnumWindows(self, cb, _):
        for h in (111, 222):
            cb(h, None)
        return True

    def GetWindowText(self, h):
        return {111: "Bloc de notas", 222: ""}[h]

    def IsWindowVisible(self, h):
        return True

    def IsWindow(self, h):
        return h in (111, 222)

    def IsIconic(self, h):
        return h == 111

    def IsZoomed(self, h):
        return False

    def GetWindowPlacement(self, h):
        return (0, getattr(self, "show_cmd", 1), (0, 0), (0, 0), (0, 0, 0, 0))

    def __init_rects__(self):
        if not hasattr(self, "rects"):
            self.rects = {111: [10, 10, 210, 160], 222: [0, 0, 100, 100]}

    def GetWindowRect(self, h):
        self.__init_rects__()
        return tuple(self.rects[h])

    def SetWindowPos(self, h, _after, x, y, w, hh, _flags):
        self.__init_rects__()
        self.calls.append(("pos", h, x, y, w, hh))
        self.rects[h] = [x, y, x + w, y + hh]
        return True

    def ShowWindow(self, h, _):
        self.calls.append(h)
        return True

    def SetForegroundWindow(self, h):
        self.fg = h
        return True

    def BringWindowToTop(self, h):
        return True

    def GetForegroundWindow(self):
        return self.fg


class _Con:
    SW_RESTORE = 9
    SW_MINIMIZE = 6
    SW_MAXIMIZE = 3
    SW_SHOWMAXIMIZED = 3
    SW_SHOWNORMAL = 1
    SWP_NOZORDER = 4
    SWP_NOACTIVATE = 16
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79
    MOUSEEVENTF_LEFTDOWN = 2
    MOUSEEVENTF_LEFTUP = 4
    MOUSEEVENTF_RIGHTDOWN = 8
    MOUSEEVENTF_RIGHTUP = 16
    MOUSEEVENTF_MIDDLEDOWN = 32
    MOUSEEVENTF_MIDDLEUP = 64
    CF_UNICODETEXT = 13


class _Api:
    def __init__(self):
        self.pos = None
        self.mouse = []
        self.kbd = []

    def GetSystemMetrics(self, n):
        return {76: 0, 77: 0, 78: 1920, 79: 1080}[n]

    def SetCursorPos(self, xy):
        self.pos = tuple(xy)

    def mouse_event(self, flags, * _):
        self.mouse.append(flags)

    def VkKeyScan(self, ch):
        if len(ch) == 1 and ch.isprintable():
            return ord(ch.upper())
        return -1

    def keybd_event(self, vk, _scan, flags, _extra):
        self.kbd.append((vk, flags))


class _WProc:
    @staticmethod
    def GetWindowThreadProcessId(h):
        return (0, 1000 + h)


def _patch_gui(monkeypatch):
    g = _Gui()
    monkeypatch.setattr(D, "_gui", g)
    monkeypatch.setattr(D, "_con", _Con())
    monkeypatch.setattr(D, "_wproc", _WProc())
    monkeypatch.setattr(D, "_psutil", None)
    return g


def test_window_list_mock(monkeypatch):
    _patch_gui(monkeypatch)
    res = run(D.window_list({}, {}))
    assert res["status"] == "ok", res
    assert res["count_total"] == 2
    assert res["count_visible_titled"] == 1
    assert res["windows"][0]["title"] == "Bloc de notas"


def test_window_focus_by_title_mock(monkeypatch):
    _patch_gui(monkeypatch)
    res = run(D.window_focus({"title": "bloc"}, {}))
    assert res["status"] == "ok" and res["hwnd"] == 111, res


def test_window_focus_missing_mock(monkeypatch):
    _patch_gui(monkeypatch)
    res = run(D.window_focus({"title": "no-existe-xyz"}, {}))
    assert res["status"] == "error"


def test_window_minimize_mock(monkeypatch):
    g = _patch_gui(monkeypatch)
    g.IsIconic = lambda h: True  # tras ShowWindow ya esta minimizada
    res = run(D.window_minimize({"hwnd": 222}, {}))
    assert res["status"] == "ok" and res["minimized"] is True, res


def test_window_maximize_mock(monkeypatch):
    g = _patch_gui(monkeypatch)
    g.show_cmd = 3  # SW_SHOWMAXIMIZED tras ShowWindow
    res = run(D.window_maximize({"hwnd": 222}, {}))
    assert res["status"] == "ok" and res["maximized"] is True, res


# --- portapapeles (clipboard stub) ---

class _Clip:
    data = {"text": "hola-portapapeles"}

    def OpenClipboard(self, _):
        return True

    def CloseClipboard(self):
        return True

    def EmptyClipboard(self):
        type(self).data["text"] = ""
        return True

    def SetClipboardData(self, _fmt, text):
        type(self).data["text"] = text
        return True

    def IsClipboardFormatAvailable(self, _fmt):
        return bool(type(self).data["text"])

    def GetClipboardData(self, _fmt):
        return type(self).data["text"] or None


def _patch_clip(monkeypatch, text="hola-portapapeles"):
    _Clip.data["text"] = text
    monkeypatch.setattr(D, "_gui", _Gui())
    monkeypatch.setattr(D, "_con", _Con())
    monkeypatch.setattr(D, "_clip", _Clip())
    monkeypatch.setattr(D, "_clip_open", lambda: True)


def test_clipboard_roundtrip_mock(monkeypatch):
    _patch_clip(monkeypatch)
    r = run(D.clipboard_read({}, {}))
    assert r["status"] == "ok" and r["text"] == "hola-portapapeles", r
    w = run(D.clipboard_write({"text": "nuevo-valor"}, {}))
    assert w["status"] == "ok" and w["chars"] == 11, w
    r2 = run(D.clipboard_read({}, {}))
    assert r2["text"] == "nuevo-valor"


def test_clipboard_empty_mock(monkeypatch):
    _patch_clip(monkeypatch, text="")
    r = run(D.clipboard_read({}, {}))
    assert r["status"] == "error"


def test_clipboard_write_needs_text(monkeypatch):
    _patch_clip(monkeypatch)
    r = run(D.clipboard_write({}, {}))
    assert r["status"] == "error"


# --- regla scope clipboard espejada del laptop (limite 64KB) ---

def test_clipboard_scope_rule_mirrored():
    med_write = {"name": "clipboard.write", "risk": "medium", "scope": "clipboard"}
    ok, _ = policy.evaluate(med_write, {"text": "corto"}, None, {}, "s", set())
    assert ok is True
    ok, why = policy.evaluate(med_write, {"text": "x" * (64 * 1024 + 1)},
                              None, {}, "s", set())
    assert ok is False and "64KB" in why
    ok, _ = policy.evaluate(med_write, {}, None, {}, "s", set())
    assert ok is False
    med_read = {"name": "clipboard.read", "risk": "medium", "scope": "clipboard"}
    ok, _ = policy.evaluate(med_read, {}, None, {}, "s", set())
    assert ok is True


# --- window.move (mock) ---

def test_window_move_keeps_size_mock(monkeypatch):
    _patch_gui(monkeypatch)
    res = run(D.window_move({"hwnd": 111, "x": 50, "y": 60}, {}))
    assert res["status"] == "ok", res
    assert res["rect"] == [50, 60, 250, 210], res  # 200x150 conservados


def test_window_move_resize_mock(monkeypatch):
    _patch_gui(monkeypatch)
    res = run(D.window_move({"title": "bloc", "x": 0, "y": 0, "w": 400, "h": 300}, {}))
    assert res["status"] == "ok" and res["rect"] == [0, 0, 400, 300], res


def test_window_move_needs_xy():
    res = run(D.window_move({"hwnd": 111}, {}))
    assert res["status"] == "error"


def test_window_move_half_size_rejected():
    res = run(D.window_move({"hwnd": 111, "x": 0, "y": 0, "w": 100}, {}))
    assert res["status"] == "error" and "juntos" in res["error"]


# --- ui.click (mock) ---

def _patch_api(monkeypatch):
    a = _Api()
    monkeypatch.setattr(D, "_gui", _Gui())
    monkeypatch.setattr(D, "_con", _Con())
    monkeypatch.setattr(D, "_api", a)
    return a


def test_ui_click_left_mock(monkeypatch):
    a = _patch_api(monkeypatch)
    res = run(D.ui_click({"x": 100, "y": 200}, {}))
    assert res["status"] == "ok" and res["button"] == "left", res
    assert a.pos == (100, 200)
    assert a.mouse == [2, 4], a.mouse  # down, up


def test_ui_click_right_mock(monkeypatch):
    a = _patch_api(monkeypatch)
    res = run(D.ui_click({"x": 10, "y": 10, "button": "right"}, {}))
    assert res["status"] == "ok", res
    assert a.mouse == [8, 16], a.mouse


def test_ui_click_out_of_bounds_mock(monkeypatch):
    _patch_api(monkeypatch)
    res = run(D.ui_click({"x": 5000, "y": 5000}, {}))
    assert res["status"] == "error" and "fuera" in res["error"]


def test_ui_click_bad_button(monkeypatch):
    _patch_api(monkeypatch)
    res = run(D.ui_click({"x": 1, "y": 1, "button": "telepatia"}, {}))
    assert res["status"] == "error"


# --- ui.keypress (mock) ---

def test_ui_keypress_combo_mock(monkeypatch):
    a = _patch_api(monkeypatch)
    res = run(D.ui_keypress({"keys": "ctrl+s"}, {}))
    assert res["status"] == "ok", res
    assert res["pressed"] == ["ctrl", "s"], res
    downs = [vk for vk, fl in a.kbd if fl == 0]
    ups = [vk for vk, fl in a.kbd if fl == 2]
    assert downs == [0x11, 0x53] and ups == [0x53, 0x11], a.kbd


def test_ui_keypress_single_named_mock(monkeypatch):
    _patch_api(monkeypatch)
    res = run(D.ui_keypress({"keys": "Enter"}, {}))
    assert res["status"] == "ok" and res["pressed"] == ["Enter"], res


def test_ui_keypress_unknown_mock(monkeypatch):
    _patch_api(monkeypatch)
    res = run(D.ui_keypress({"keys": "hipertornillo"}, {}))
    assert res["status"] == "error"


def test_ui_keypress_bad_modifier_mock(monkeypatch):
    _patch_api(monkeypatch)
    res = run(D.ui_keypress({"keys": "cosa+s"}, {}))
    assert res["status"] == "error" and "modificador" in res["error"]


def test_ui_keypress_empty():
    res = run(D.ui_keypress({"keys": "  "}, {}))
    assert res["status"] == "error"
