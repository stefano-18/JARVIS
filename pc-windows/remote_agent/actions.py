"""Manifiestos: cada accion declara nombre, parametros, risk, timeout y modulo.

Riesgos: system/apps-open/apps-close LOW-MEDIUM segun spec; process.terminate
HIGH; files.delete HIGH (cuarentena); shell.exec es LOW dentro de allowlist
y se escala a HIGH (concesion firmada) fuera de ella (ver execute_action);
system.shutdown/restart/lock/logoff/suspend siempre HIGH.
"""
try:
    from remote_agent import (actions_system, actions_apps, actions_process,
                              actions_files, actions_shell, actions_tasks,
                              actions_desktop, actions_media)
except ImportError:
    import actions_system, actions_apps, actions_process
    import actions_files, actions_shell, actions_tasks
    import actions_desktop
    try:
        import actions_media
    except ImportError:
        actions_media = None

MANIFESTS = [
    {"name": "system.info", "params": {}, "risk": "low",
     "timeout": 15, "module": "system", "scope": "",
     "fn": actions_system.system_info},
    # Energia/sesion: HIGH = concesion firmada obligatoria. Sin grant la
    # politica deniega con error honesto (executed=false); el hub/LLM jamas
    # debe anunciar exito si el resultado no es status ok.
    {"name": "system.shutdown", "params": {}, "risk": "high",
     "timeout": 30, "module": "system", "scope": "",
     "fn": actions_system.system_shutdown},
    {"name": "system.restart", "params": {}, "risk": "high",
     "timeout": 30, "module": "system", "scope": "",
     "fn": actions_system.system_restart},
    {"name": "system.lock", "params": {}, "risk": "high",
     "timeout": 30, "module": "system", "scope": "",
     "fn": actions_system.system_lock},
    {"name": "system.logoff", "params": {}, "risk": "high",
     "timeout": 30, "module": "system", "scope": "",
     "fn": actions_system.system_logoff},
    {"name": "system.suspend", "params": {}, "risk": "high",
     "timeout": 30, "module": "system", "scope": "",
     "fn": actions_system.system_suspend},
    {"name": "apps.open", "params": {"app": "str"}, "risk": "medium",
     "timeout": 15, "module": "apps", "scope": "apps",
     "fn": actions_apps.apps_open},
    {"name": "apps.close", "params": {"app": "str"}, "risk": "medium",
     "timeout": 20, "module": "apps", "scope": "apps",
     "fn": actions_apps.apps_close},
    {"name": "process.list", "params": {"limit": "int?"}, "risk": "low",
     "timeout": 20, "module": "process", "scope": "",
     "fn": actions_process.process_list},
    {"name": "process.info", "params": {"pid": "int"}, "risk": "low",
     "timeout": 20, "module": "process", "scope": "",
     "fn": actions_process.process_info},
    {"name": "process.terminate", "params": {"pid": "int"}, "risk": "high",
     "timeout": 20, "module": "process", "scope": "",
     "fn": actions_process.process_terminate},
    {"name": "files.list", "params": {"path": "str"}, "risk": "low",
     "timeout": 15, "module": "files", "scope": "files",
     "fn": actions_files.files_list},
    {"name": "files.search", "params": {"path": "str", "pattern": "str"},
     "risk": "low", "timeout": 20, "module": "files", "scope": "files",
     "fn": actions_files.files_search},
    {"name": "files.read", "params": {"path": "str"}, "risk": "low",
     "timeout": 15, "module": "files", "scope": "files",
     "fn": actions_files.files_read},
    {"name": "files.write", "params": {"path": "str", "content": "str"},
     "risk": "medium", "timeout": 15, "module": "files", "scope": "files",
     "fn": actions_files.files_write},
    {"name": "files.copy", "params": {"src": "str", "dst": "str"},
     "risk": "medium", "timeout": 30, "module": "files", "scope": "files",
     "fn": actions_files.files_copy},
    {"name": "files.move", "params": {"src": "str", "dst": "str"},
     "risk": "medium", "timeout": 30, "module": "files", "scope": "files",
     "fn": actions_files.files_move},
    {"name": "files.delete", "params": {"path": "str"}, "risk": "high",
     "timeout": 20, "module": "files", "scope": "files",
     "fn": actions_files.files_delete},
    {"name": "shell.exec", "params": {"cmd": "str", "args": "list",
                                      "timeout": "float?"}, "risk": "low",
     "timeout": 30, "module": "shell", "scope": "shell",
     "fn": actions_shell.shell_exec},
    {"name": "tasks.stub", "params": {}, "risk": "low",
     "timeout": 5, "module": "tasks", "scope": "",
     "fn": actions_tasks.tasks_stub},
    # Computer use avanzado (ver actions_desktop.py). screen/clipboard y
    # cambios de estado de ventanas son HIGH = concesion firmada obligatoria;
    # window.list es solo enumeracion (LOW, como process.list).
    {"name": "screen.capture", "params": {"monitor": "int?", "format": "str?",
                                          "max_width": "int?", "quality": "int?"},
     "risk": "high", "timeout": 30, "module": "desktop", "scope": "",
     "fn": actions_desktop.screen_capture},
    {"name": "window.list", "params": {}, "risk": "low",
     "timeout": 20, "module": "desktop", "scope": "",
     "fn": actions_desktop.window_list},
    {"name": "window.focus", "params": {"hwnd": "int?", "title": "str?"},
     "risk": "high", "timeout": 20, "module": "desktop", "scope": "",
     "fn": actions_desktop.window_focus},
    {"name": "window.minimize", "params": {"hwnd": "int?", "title": "str?"},
     "risk": "high", "timeout": 20, "module": "desktop", "scope": "",
     "fn": actions_desktop.window_minimize},
    {"name": "window.maximize", "params": {"hwnd": "int?", "title": "str?"},
     "risk": "high", "timeout": 20, "module": "desktop", "scope": "",
     "fn": actions_desktop.window_maximize},
    {"name": "clipboard.read", "params": {}, "risk": "high",
     "timeout": 15, "module": "desktop", "scope": "",
     "fn": actions_desktop.clipboard_read},
    {"name": "clipboard.write", "params": {"text": "str"},
     "risk": "high", "timeout": 15, "module": "desktop", "scope": "",
     "fn": actions_desktop.clipboard_write},
    {"name": "window.move", "params": {"hwnd": "int?", "title": "str?",
                                      "x": "int", "y": "int",
                                      "w": "int?", "h": "int?"},
     "risk": "high", "timeout": 20, "module": "desktop", "scope": "",
     "fn": actions_desktop.window_move},
    {"name": "ui.click", "params": {"x": "int", "y": "int", "button": "str?"},
     "risk": "high", "timeout": 20, "module": "desktop", "scope": "",
     "fn": actions_desktop.ui_click},
    {"name": "ui.keypress", "params": {"keys": "str"},
     "risk": "high", "timeout": 20, "module": "desktop", "scope": "",
     "fn": actions_desktop.ui_keypress},
    {"name": "files.mkdir", "params": {"path": "str"},
     "risk": "medium", "timeout": 15, "module": "files", "scope": "files",
     "fn": actions_files.files_mkdir},
    {"name": "files.hash", "params": {"path": "str"},
     "risk": "low", "timeout": 20, "module": "files", "scope": "files",
     "fn": actions_files.files_hash},
]

if actions_media is not None:
    MANIFESTS += [
        {"name": "media.play_pause", "params": {},
         "risk": "medium", "timeout": 10, "module": "media",
         "scope": "media", "fn": actions_media.media_play_pause},
        {"name": "media.next", "params": {},
         "risk": "medium", "timeout": 10, "module": "media",
         "scope": "media", "fn": actions_media.media_next},
        {"name": "media.previous", "params": {},
         "risk": "medium", "timeout": 10, "module": "media",
         "scope": "media", "fn": actions_media.media_previous},
        {"name": "volume.get", "params": {},
         "risk": "medium", "timeout": 10, "module": "media",
         "scope": "media", "fn": actions_media.volume_get},
        {"name": "volume.set", "params": {"level": "int"},
         "risk": "medium", "timeout": 10, "module": "media",
         "scope": "media", "fn": actions_media.volume_set},
        {"name": "volume.mute", "params": {"muted": "bool?"},
         "risk": "medium", "timeout": 10, "module": "media",
         "scope": "media", "fn": actions_media.volume_mute},
    ]

BY_NAME = {m["name"]: m for m in MANIFESTS}


def verify_sync(expected: dict = None) -> tuple:
    """Manifiestos sincronizados (B4): compara riesgos actuales vs esperados.

    expected {name: risk}. Si None, usa la tabla canonica de este agente.
    Retorna (ok, diff). La laptop debe espejar esta tabla.
    """
    canon = {m["name"]: m["risk"] for m in MANIFESTS}
    exp = expected if expected is not None else dict(canon)
    diff = {}
    for k, v in exp.items():
        if canon.get(k) != v:
            diff[k] = {"esperado": v, "local": canon.get(k)}
    for k in canon:
        if k not in exp:
            diff[k] = {"esperado": None, "local": canon[k]}
    return (len(diff) == 0, diff)
