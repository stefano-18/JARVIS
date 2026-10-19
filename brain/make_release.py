"""Genera el release compartible en UN comando (1 commit, sin remoto).

Fases (FAIL si alguna falla; nunca crea remotos ni hace push):
  1. aborta si producción tiene cambios sin commit.
  2. exporta HEAD (git archive) y aplica scripts/release_rules.yaml
     (exclusiones, sustituciones exactas, referencias prohibidas).
  3. integra agent_pc desde _incoming/agent_pc.zip (si existe) +
     plantillas INTEGRACION.md/verify_sync.py + pie en README del PC.
  4. sincroniza remote_agent/actions.py con los manifiestos del PC
     (regla @SYNC_FROM_PC) y verifica SYNC OK.
  5. recrea el repo del release con 1 commit ("Initial release").
  6. coincidencia exacta de secretos vivos (árbol e historial = 0).
  7. gitleaks (solo permite los triados en la YAML).
  8. prueba limpia (venv nuevo, setup real, --check, suite completa).

Uso:  python scripts/make_release.py [--solo-chequeo]
"""
import fnmatch
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

JROOT = Path(__file__).resolve().parent.parent
RULES = JROOT / "scripts" / "release_rules.yaml"

SECRET_KEYS = {
    'TELEGRAM_BOT_TOKEN', 'TELEGRAM_ALLOWED_CHAT_IDS',
    'GROQ_API_KEY', 'MISTRAL_API_KEY', 'COHERE_API_KEY', 'GEMINI_API_KEY',
    'OPENROUTER_API_KEY', 'OBSIDIAN_REST_TOKEN', 'OBSIDIAN_API_KEY',
    'SPOTIFY_CLIENT_SECRET', 'SPOTIFY_CLIENT_ID',
    'HUD_TOKEN', 'JARVIS_REMOTE_SECRET', 'JARVIS_REMOTE_DEVICE_ID',
}
LIVE_ENVS = [r'{{WIN_HOME}}\Jarvis\.env',
             r'{{WIN_HOME}}\Jarvis-v2\.env',
             r'{{WIN_HOME}}\jarvis2\.env']

README_SYNC_FOOTER = """
## Sincronía con la laptop

El espejo de la laptop es `remote_agent/` (stubs). Integración y
verificación en `INTEGRACION.md`: `python agent_pc/verify_sync.py --pc-path agent_pc` debe decir SYNC OK.
"""


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.stdout is None:
        r.stdout = ""
    if r.stderr is None:
        r.stderr = ""
    return r


def fase(nombre):
    print(f"[release] == {nombre} ==")


def fail(msg):
    print(f"[release] FAIL: {msg}")
    raise SystemExit(1)


def load_rules():
    import yaml
    try:
        return yaml.safe_load(RULES.read_text(encoding='utf-8'))
    except Exception as e:
        fail(f"no se pudo leer release_rules.yaml: {e}")


def paso_arbol_limpio():
    r = sh(['git', '-C', str(JROOT), 'status', '--porcelain'])
    if r.stdout.strip():
        fail("producción tiene cambios sin commit:\n" + r.stdout)


def paso_exportar(dest: Path):
    r = sh(['git', '-C', str(JROOT), 'archive', 'HEAD', '-o',
            str(dest / 'head.zip')])
    if r.returncode != 0 or not (dest / 'head.zip').exists():
        fail("git archive HEAD falló")
    tree = dest / 'tree'
    tree.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest / 'head.zip') as z:
        z.extractall(tree)
    return tree


def _excluido(rel: str, patrones: list) -> bool:
    rel = rel.replace('\\', '/')
    for pat in patrones:
        if pat.endswith('/'):
            nombre = pat[:-1]
            if rel == nombre or rel.startswith(pat) or \
               ('/' + nombre + '/') in ('/' + rel) or \
               rel.endswith('/' + nombre):
                return True
        elif fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(
                rel.split('/')[-1], pat):
            return True
    return False


def paso_excluir(tree: Path, patrones: list) -> int:
    n = 0
    for p in sorted(tree.rglob('*')):
        rel = p.relative_to(tree).as_posix()
        if _excluido(rel, patrones):
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
            n += 1
    return n


def paso_sustituir(tree: Path, reglas: list, pc_dir: Path | None) -> None:
    for i, r in enumerate(reglas):
        rel = (r.get('archivo') or '').replace('\\', '/')
        target = tree / rel
        if not target.exists():
            fail(f"sustitución {i} ({rel}): fichero ausente")
        txt = target.read_text(encoding='utf-8')
        old = r.get('buscar', '')
        new = r.get('reemplazo', '')
        veces = int(r.get('veces', 1))
        n = txt.count(old)
        if n != veces:
            fail(f"sustitución {i} ({rel}): encontrado {n} veces, "
                 f"esperado {veces} (actualiza release_rules.yaml)")
        if new == '@SYNC_FROM_PC':
            if pc_dir is None:
                fail("regla @SYNC_FROM_PC sin agent_pc integrado")
            new = _bloque_stubs_desde_pc(pc_dir)
        target.write_text(txt.replace(old, new), encoding='utf-8')
        print(f"[release] sustitución {i} {rel}: OK")


def _manifiestos(actions_py: Path) -> dict:
    spec = importlib.util.spec_from_file_location('_rel_actions',
                                                 str(actions_py))
    mod = importlib.util.module_from_spec(spec)
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    out = {}
    for m in getattr(mod, 'MANIFESTS', []) or []:
        out[m.get('name', '?')] = {
            'params': m.get('params', {}),
            'risk': str(m.get('risk', '')),
            'timeout': m.get('timeout'),
            'module': m.get('module', ''),
        }
    return out


def _bloque_stubs_desde_pc(pc_dir: Path) -> str:
    sys.path.insert(0, str(pc_dir))
    try:
        mani = _manifiestos(pc_dir / 'actions.py')
    finally:
        try:
            sys.path.remove(str(pc_dir))
        except ValueError:
            pass
    comp = {k: v for k, v in mani.items() if v.get('module') == 'desktop'}
    if not comp:
        fail("el PC no trae manifiestos desktop para sincronizar")
    lin = []
    lin.append('    # Fase 9 Computer Use (riesgos IDENTICOS a los manifiestos del PC).')
    lin.append('    # fn: stub local — en el laptop nunca se ejecuta (solo se envia jr_req')
    lin.append('    # al PC via pc_proxy); el PC usa su propia copia con fn reales en')
    lin.append('    # actions_desktop.py bajo modulo "desktop". Ver agent_pc/README.md y')
    lin.append('    # agent_pc/INTEGRACION.md; sincronia con agent_pc/verify_sync.py.')
    for name, m in comp.items():
        lin.append(f'    {{"name": {name!r}, "params": {m["params"]!r}, '
                   f'"risk": {m["risk"]!r}, "timeout": {m["timeout"]!r}, '
                   f'"module": "desktop", "scope": "",')
        lin.append('     "fn": None},')
    return '\n'.join(lin) + '\n'


def paso_agent_pc(tree: Path, zip_rel: str) -> Path | None:
    zf = JROOT / zip_rel
    if not zf.exists():
        print(f"[release] sin {zip_rel}: se omite agent_pc")
        return None
    apc = tree / 'agent_pc'
    if apc.exists():
        shutil.rmtree(apc)
    apc.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zf) as z:
        for info in z.infolist():
            if not info.filename.startswith('agent_pc/'):
                continue
            rel = info.filename[len('agent_pc/'):]
            if not rel:
                continue
            tgt = apc / rel
            if info.is_dir():
                tgt.mkdir(parents=True, exist_ok=True)
            else:
                tgt.parent.mkdir(parents=True, exist_ok=True)
                tgt.write_bytes(z.read(info.filename))
    (apc / 'INTEGRACION.md').write_bytes(
        (JROOT / 'scripts' / 'release_integracion.md').read_bytes())
    shutil.copyfile(JROOT / 'scripts' / 'release_verify_sync.py',
                    apc / 'verify_sync.py')
    for d in list(apc.rglob('__pycache__')):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
    for p in list(apc.rglob('*.pyc')):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    rd = apc / 'README.md'
    if 'Sincronía con la laptop' not in rd.read_text(encoding='utf-8'):
        with rd.open('a', encoding='utf-8') as f:
            f.write(README_SYNC_FOOTER)
    print("[release] agent_pc integrado desde el zip")
    return apc


def paso_verify_sync(tree: Path, pc_dir: Path) -> None:
    # pc_dir también en el path: el actions.py del PC trae
    # `from remote_agent import ... actions_desktop` (inexistente en el
    # espejo) con fallback a imports directos, que son EXACTAMENTE así
    # como los resuelve el PC (cwd=agent_pc). Sin esto, la carga muere
    # con ModuleNotFoundError en vez de comparar.
    sys.path.insert(0, str(pc_dir))
    sys.path.insert(0, str(JROOT))
    try:
        repo = _manifiestos(tree / 'remote_agent' / 'actions.py')
        pc = _manifiestos(pc_dir / 'actions.py')
    finally:
        for _p in (str(JROOT), str(pc_dir)):
            try:
                sys.path.remove(_p)
            except ValueError:
                pass
    if repo != pc:
        solo_r = sorted(set(repo) - set(pc))
        solo_p = sorted(set(pc) - set(repo))
        dif = sorted(k for k in set(repo) & set(pc) if repo[k] != pc[k])
        fail(f"OUT OF SYNC solo_repo={solo_r} solo_pc={solo_p} difieren={dif}")
    print(f"[release] SYNC OK ({len(repo)} manifiestos)")


def paso_aplicar_overlays(pc_dir: Path) -> None:
    """Aplica overlays desde _incoming/overlay/agent_pc sobre el agent_pc integrado."""
    overlay_root = JROOT / '_incoming' / 'overlay' / 'agent_pc'
    if not overlay_root.exists():
        print("[release] sin overlays para agent_pc")
        return
    count = 0
    for overlay_file in overlay_root.rglob('*'):
        if overlay_file.is_file():
            rel = overlay_file.relative_to(overlay_root)
            target = pc_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(overlay_file.read_bytes())
            count += 1
            print(f"[release] overlay aplicado: {rel}")
    if count:
        print(f"[release] overlays aplicados: {count}")
    else:
        print("[release] sin overlays para agent_pc")


def paso_prohibido(tree: Path, patrones: list) -> None:
    mal = []
    for p in tree.rglob('*'):
        if p.is_dir() or '.git' in p.parts:
            continue
        try:
            if p.stat().st_size > 2_000_000:
                continue
            t = p.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        for pat in patrones:
            if re.search(pat, t):
                mal.append(f"{p.relative_to(tree).as_posix()} :: {pat}")
    if mal:
        fail("referencias prohibidas:\n" + "\n".join(mal[:20]))
    print("[release] prohibido: 0")


def _vaciar(d: Path) -> None:
    import stat as _st
    def _rw(func, path, _exc):
        try:
            os.chmod(path, _st.S_IWRITE)
            func(path)
        except Exception:
            pass
    if d.exists():
        shutil.rmtree(d, ignore_errors=False, onerror=_rw)
    d.mkdir(parents=True, exist_ok=True)


def paso_recrear_repo(release_dir: Path, tree: Path) -> None:
    _vaciar(release_dir)
    for item in tree.iterdir():
        dst = release_dir / item.name
        if item.is_dir() and not item.is_symlink():
            shutil.copytree(item, dst)
        else:
            shutil.copy2(item, dst)
    r = sh(['git', '-C', str(release_dir), 'init'])
    if r.returncode != 0:
        fail("git init falló")
    sh(['git', '-C', str(release_dir), 'config', 'user.name', 'jarvis'])
    sh(['git', '-C', str(release_dir), 'config', 'user.email', 'jarvis@local'])
    r = sh(['git', '-C', str(release_dir), 'add', '-A'])
    if r.returncode != 0:
        fail("git add falló")
    r = sh(['git', '-C', str(release_dir), 'commit', '-m', 'Initial release'])
    if r.returncode != 0:
        fail("git commit falló: " + r.stderr[-500:])
    n = sh(['git', '-C', str(release_dir), 'rev-list', '--count', 'HEAD'])
    if n.stdout.strip() != '1':
        fail("el release no tiene 1 commit")
    print("[release] repo nuevo: 1 commit")


def _secretos_vivos() -> tuple:
    vals = []
    for ep in LIVE_ENVS:
        try:
            txt = Path(ep).read_text(encoding='utf-8-sig', errors='replace')
        except Exception:
            continue
        for line in txt.splitlines():
            s = line.strip()
            if not s or s.startswith('#') or '=' not in s:
                continue
            k, v = s.split('=', 1)
            k, v = k.strip().lstrip('﻿'), v.strip().strip('"').strip("'")
            if k in SECRET_KEYS and len(v) >= 4:
                if k == 'TELEGRAM_ALLOWED_CHAT_IDS':
                    vals += [x.strip() for x in v.replace(',', ' ').split()
                             if len(x.strip()) >= 4]
                else:
                    vals.append(v)
    uniq = sorted(set(vals), key=len, reverse=True)
    return uniq, [s[:12] for s in uniq if len(s) >= 12]


def paso_secretos(release_dir: Path) -> None:
    uniq, prefs = _secretos_vivos()
    print(f"[release] secretos en memoria: {len(uniq)} (sin mostrar)")
    mal_arbol, mal_hist = [], 0
    for p in release_dir.rglob('*'):
        if p.is_dir() or '.git' in p.parts:
            continue
        try:
            if p.stat().st_size > 2_000_000:
                continue
            t = p.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        if any(len(s) >= 8 and s in t for s in uniq) or \
           any(pr in t for pr in prefs):
            mal_arbol.append(p.relative_to(release_dir).as_posix())
    blob = sh(['git', '-C', str(release_dir), 'log', '--all', '-p',
               '--no-color']).stdout or ""
    if any(len(s) >= 8 and s in blob for s in uniq) or \
       any(pr in blob for pr in prefs):
        mal_hist = 1
    print(f"[release] exacta árbol={len(mal_arbol)} historial={mal_hist}")
    if mal_arbol:
        fail("secretos en árbol: " + ", ".join(mal_arbol[:10]))
    if mal_hist:
        fail("secretos en historial")
    print("[release] exacta: 0 y 0")


def _gitleaks_bin() -> str | None:
    w = shutil.which('gitleaks')
    if w:
        return w
    cands = glob.glob(str(Path(
        os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/WinGet/Packages/'
        'Gitleaks.Gitleaks_*/gitleaks.exe'))
    return cands[0] if cands else None


def paso_gitleaks(release_dir: Path, permitidos: list) -> None:
    exe = _gitleaks_bin()
    if not exe:
        fail("gitleaks no instalado")
    rep = str(Path(tempfile.gettempdir()) / 'rel_gitleaks.json')
    r = sh([exe, 'detect', '--source', str(release_dir), '--redact',
            '--format', 'json', '--report', rep, '-v'])
    try:
        findings = json.loads(Path(rep).read_text(encoding='utf-8'))
    except Exception:
        findings = []
    print(f"[release] gitleaks hallazgos={len(findings)}")
    for f in findings:
        ok = any((f.get('File', '').replace('\\', '/').endswith(p['fichero'])
                  and f.get('RuleID') == p['regla']) for p in permitidos)
        print(f"  - {f.get('File')} :: {f.get('RuleID')} "
              f"({'triado' if ok else 'NO TRIADO'})")
        if not ok:
            fail("gitleaks con hallazgo no triado")
    print("[release] gitleaks: solo triados")


def paso_prueba_limpia(release_dir: Path, clean_dir: str) -> None:
    cd = Path(clean_dir)
    if cd.exists():
        shutil.rmtree(cd, ignore_errors=True)
    shutil.copytree(release_dir, cd,
                    ignore=shutil.ignore_patterns('.git', '__pycache__'))
    py = sys.executable
    venv_py = cd / '.venv' / 'Scripts' / 'python.exe'
    r = sh([py, '-m', 'venv', str(cd / '.venv')])
    if r.returncode != 0 or not venv_py.exists():
        fail("venv falló")
    pelvis = [str(venv_py), '-m', 'pip', 'install', '-r',
              str(cd / 'requirements.txt')]
    r = subprocess.run(pelvis, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        fail("pip install falló:\n" + r.stdout[-2000:])
    r = subprocess.run([str(venv_py), 'scripts/setup.py'], cwd=str(cd),
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        fail("setup.py falló:\n" + r.stdout[-2000:] + r.stderr[-500:])
    print("[release] setup real OK")
    r = subprocess.run([str(venv_py), 'scripts/setup.py', '--check'],
                       cwd=str(cd), capture_output=True, text=True,
                       timeout=300)
    if r.returncode != 0:
        fail("--check falló:\n" + r.stdout[-2000:])
    print("[release] --check OK")
    r = subprocess.run([str(venv_py), '-m', 'pytest', '-q'], cwd=str(cd),
                       capture_output=True, text=True, timeout=1200)
    tail = (r.stdout + r.stderr)[-1500:]
    if r.returncode != 0:
        fail("suite falló:\n" + tail)
    print("[release] suite: " + tail.strip().splitlines()[-1])
    r = subprocess.run(
        [str(venv_py), '-m', 'pip', 'install', 'mss', 'Pillow', 'pywin32'],
        capture_output=True, text=True, timeout=600)
    r = subprocess.run([str(venv_py), '-m', 'pytest', 'agent_pc/tests',
                        '-q'], cwd=str(cd), capture_output=True, text=True,
                       timeout=600)
    if r.returncode != 0:
        fail("agent_pc/tests falló:\n" + (r.stdout + r.stderr)[-1500:])
    print("[release] agent_pc/tests OK")


def main() -> int:
    solo = '--solo-chequeo' in sys.argv
    rules = load_rules()
    release_dir = Path(rules['release_dir'])
    clean_dir = rules.get('clean_test_dir',
                          '{{WIN_HOME_BARRA}}/jarvis-clean-test')
    fase('1/8 árbol limpio')
    paso_arbol_limpio()
    with tempfile.TemporaryDirectory(prefix='mkrel_') as tmp:
        tmp = Path(tmp)
        fase('2/8 export + reglas')
        tree = paso_exportar(tmp)
        n = paso_excluir(tree, rules.get('excluir', []))
        print(f"[release] excluidos: {n}")
        pc = paso_agent_pc(tree, rules.get('pc_zip',
                                           '_incoming/agent_pc.zip'))
        paso_sustituir(tree, rules.get('sustituir', []), pc)
        if pc is not None:
            paso_aplicar_overlays(pc)
            paso_verify_sync(tree, pc)
        for d in list(tree.rglob('__pycache__')):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
        for p in list(tree.rglob('*.pyc')):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        paso_prohibido(tree, rules.get('prohibido', []))
        if solo:
            print("[release] --solo-chequeo: PASS (sin recrear ni probar)")
            return 0
        fase('5/8 repo nuevo')
        paso_recrear_repo(release_dir, tree)
    fase('6/8 secretos')
    paso_secretos(release_dir)
    fase('7/8 gitleaks')
    paso_gitleaks(release_dir, rules.get('gitleaks_permitido', []))
    fase('8/8 prueba limpia')
    paso_prueba_limpia(release_dir, clean_dir)
    print("[release] RESULTADO: PASS")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
