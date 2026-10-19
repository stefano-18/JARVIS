"""Acciones files.* LOW leer/listar/buscar; MEDIUM escribir/copiar/mover;
HIGH eliminar (= mover a _jarvis_trash dentro de un allowed_root, jamas borrar)."""
import os
import shutil
import time
from pathlib import Path

try:
    from remote_agent import policy as _pol
except ImportError:
    import policy as _pol


def _err(code: str, msg: str, **extra) -> dict:
    """Error honesto: texto nunca vacio + codigo estable."""
    msg = (msg or "").strip() or f"error desconocido ({code})"
    d = {"status": "error", "error": msg[:300], "code": code}
    d.update(extra)
    return d


def _guarded(path: str, ctx: dict) -> tuple[bool, str, str]:
    return _pol.resolve_in_roots(path, ctx.get("roots", []))


async def files_list(params: dict, ctx: dict) -> dict:
    ok, real, why = _guarded(params.get("path", ""), ctx)
    if not ok:
        return _err("outside_roots", why)
    try:
        items = [{"name": p.name, "dir": p.is_dir(),
                  "size": p.stat().st_size if p.is_file() else 0}
                 for p in sorted(Path(real).iterdir(), key=lambda x: x.name)]
        return {"status": "ok", "path": real, "items": items[:200]}
    except Exception as e:
        return _err("io_error", f"operacion de fichero fallo: {e}")


async def files_search(params: dict, ctx: dict) -> dict:
    ok, real, why = _guarded(params.get("path", ""), ctx)
    if not ok:
        return _err("outside_roots", why)
    pattern = str(params.get("pattern", "*"))
    try:
        hits = [str(p) for p in list(Path(real).rglob(pattern))[:100]]
        return {"status": "ok", "hits": hits}
    except Exception as e:
        return _err("io_error", f"operacion de fichero fallo: {e}")


async def files_read(params: dict, ctx: dict) -> dict:
    ok, real, why = _guarded(params.get("path", ""), ctx)
    if not ok:
        return _err("outside_roots", why)
    try:
        data = Path(real).read_bytes()
        cap = int(ctx.get("output_max", 65536))
        trunc = len(data) > cap
        return {"status": "ok", "path": real, "size": len(data),
                "truncated": trunc,
                "content": data[:cap].decode("utf-8", errors="replace")}
    except Exception as e:
        return _err("io_error", f"operacion de fichero fallo: {e}")


async def files_write(params: dict, ctx: dict) -> dict:
    ok, real, why = _guarded(params.get("path", ""), ctx)
    if not ok:
        return _err("outside_roots", why)
    try:
        p = Path(real)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp-jarvis")
        tmp.write_text(str(params.get("content", "")), encoding="utf-8")
        os.replace(tmp, p)
        return {"status": "ok", "path": real}
    except Exception as e:
        return _err("io_error", f"operacion de fichero fallo: {e}")


async def files_copy(params: dict, ctx: dict) -> dict:
    ok1, src, w1 = _guarded(params.get("src", ""), ctx)
    ok2, dst, w2 = _guarded(params.get("dst", ""), ctx)
    if not ok1:
        return _err("outside_roots", f"origen: {w1}")
    if not ok2:
        return _err("outside_roots", f"destino: {w2}")
    try:
        if str(ctx.get("files_ext", "0")) == "1" and Path(src).is_file():
            try:
                if Path(src).stat().st_size > FILE_MAX_BYTES:
                    return _err("too_large", "origen supera tope 64MB")
            except Exception:
                pass
        if Path(src).is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return {"status": "ok", "dst": dst}
    except Exception as e:
        return _err("io_error", f"operacion de fichero fallo: {e}")


async def files_move(params: dict, ctx: dict) -> dict:
    r = await files_copy(params, ctx)
    if r.get("status") != "ok":
        return r
    try:
        src = str(Path(params["src"]).resolve())
        if Path(src).is_dir():
            shutil.rmtree(src)
        else:
            os.remove(src)
        return {"status": "ok", "dst": r["dst"]}
    except Exception as e:
        return _err("io_error", f"operacion de fichero fallo: {e}")


async def files_delete(params: dict, ctx: dict) -> dict:
    """HIGH: cuarentena, nunca borrado permanente.

    FASE B3: con FILES_EXT=1 la cuarentena es ROOTS/_cuarentena;
    por defecto (flag 0) se conserva _jarvis_trash.
    """
    ok, real, why = _guarded(params.get("path", ""), ctx)
    if not ok:
        return _err("outside_roots", why)
    try:
        roots = ctx.get("roots", [])
        base = str(Path(roots[0]).resolve())
        default_trash = ("_cuarentena" if str(ctx.get("files_ext", "0")) == "1"
                         else ctx.get("trash_dir", "_jarvis_trash"))
        trash = Path(base) / default_trash
        trash.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = trash / f"{Path(real).name}.{stamp}"
        os.replace(real, dest)
        return {"status": "ok", "quarantined": str(dest)}
    except Exception as e:
        return _err("io_error", f"operacion de fichero fallo: {e}")


async def files_mkdir(params: dict, ctx: dict) -> dict:
    """MEDIUM: crea directorio dentro de ROOTS."""
    ok, real, why = _guarded(params.get("path", ""), ctx)
    if not ok:
        return _err("outside_roots", why)
    try:
        Path(real).mkdir(parents=True, exist_ok=True)
        return {"status": "ok", "path": real}
    except Exception as e:
        return _err("mkdir fallo: {e}")


async def files_hash(params: dict, ctx: dict) -> dict:
    """LOW: sha256 de un fichero dentro de ROOTS (tope FILE_MAX_BYTES)."""
    ok, real, why = _guarded(params.get("path", ""), ctx)
    if not ok:
        return _err("outside_roots", why)
    try:
        import hashlib as _hl
        p = Path(real)
        if not p.is_file():
            return _err("not_found", "no es fichero")
        if p.stat().st_size > FILE_MAX_BYTES:
            return _err("too_large", "fichero supera tope 64MB")
        h = _hl.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return {"status": "ok", "path": real, "sha256": h.hexdigest(),
                "size": p.stat().st_size}
    except Exception as e:
        return _err("io_error", f"hash fallo: {e}")


# --- NUEVAS FUNCIONES para Fase 12 ---

async def files_listar(params: dict, ctx: dict) -> dict:
    """Listar archivos en una ruta (risk LOW, scope files).
    Igual que files_list pero con nombre canonical para MANIFESTS."""
    ok, real, why = _guarded(params.get("path", ""), ctx)
    if not ok:
        return _err("outside_roots", why)
    try:
        items = [{"name": p.name, "dir": p.is_dir(),
                  "size": p.stat().st_size if p.is_file() else 0}
                 for p in sorted(Path(real).iterdir(), key=lambda x: x.name)]
        return {"status": "ok", "path": real, "items": items[:200]}
    except Exception as e:
        return _err("io_error", f"operacion de fichero fallo: {e}")


async def files_buscar(params: dict, ctx: dict) -> dict:
    """Buscar archivos con patron en ruta (risk LOW, scope files)."""
    ok, real, why = _guarded(params.get("path", ""), ctx)
    if not ok:
        return _err("outside_roots", why)
    pattern = str(params.get("patron", "*"))
    try:
        hits = [str(p) for p in list(Path(real).rglob(pattern))[:100]]
        return {"status": "ok", "hits": hits}
    except Exception as e:
        return _err("io_error", f"operacion de fichero fallo: {e}")


async def files_copiar(params: dict, ctx: dict) -> dict:
    """Copiar archivo de origen a destino (risk LOW, scope files)."""
    ok1, src, w1 = _guarded(params.get("origen", ""), ctx)
    ok2, dst, w2 = _guarded(params.get("destino", ""), ctx)
    if not ok1:
        return _err("outside_roots", f"origen: {w1}")
    if not ok2:
        return _err("outside_roots", f"destino: {w2}")
    try:
        if str(ctx.get("files_ext", "0")) == "1" and Path(src).is_file():
            try:
                if Path(src).stat().st_size > FILE_MAX_BYTES:
                    return _err("too_large", "origen supera tope 64MB")
            except Exception:
                pass
        if Path(src).is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return {"status": "ok", "dst": dst}
    except Exception as e:
        return _err("io_error", f"operacion de fichero fallo: {e}")


async def files_mover(params: dict, ctx: dict) -> dict:
    """Mover archivo de origen a destino (risk LOW, scope files)."""
    ok1, src, w1 = _guarded(params.get("origen", ""), ctx)
    ok2, dst, w2 = _guarded(params.get("destino", ""), ctx)
    if not ok1:
        return _err("outside_roots", f"origen: {w1}")
    if not ok2:
        return _err("outside_roots", f"destino: {w2}")
    try:
        if str(ctx.get("files_ext", "0")) == "1" and Path(src).is_file():
            try:
                if Path(src).stat().st_size > FILE_MAX_BYTES:
                    return _err("too_large", "origen supera tope 64MB")
            except Exception:
                pass
        shutil.move(src, dst)
        return {"status": "ok", "dst": dst}
    except Exception as e:
        return _err("io_error", f"operacion de fichero fallo: {e}")


async def files_borrar(params: dict, ctx: dict) -> dict:
    """Borrar archivo a la papelera (risk HIGH, scope files).
    Siempre mueve a _jarvis_trash o _cuarentena, nunca borra permanentemente."""
    ok, real, why = _guarded(params.get("path", ""), ctx)
    if not ok:
        return _err("outside_roots", why)
    try:
        roots = ctx.get("roots", [])
        base = str(Path(roots[0]).resolve())
        default_trash = ("_cuarentena" if str(ctx.get("files_ext", "0")) == "1"
                         else ctx.get("trash_dir", "_jarvis_trash"))
        trash = Path(base) / default_trash
        trash.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = trash / f"{Path(real).name}.{stamp}"
        os.replace(real, dest)
        return {"status": "ok", "quarantined": str(dest)}
    except Exception as e:
        return _err("io_error", f"operacion de fichero fallo: {e}")


FILE_MAX_BYTES = 64 * 1024 * 1024
SEARCH_MAX = 100