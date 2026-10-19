"""Verifica sincronía de manifiestos y riesgos entre este repo y el PC.

Compara remote_agent/actions.py (repo) contra la copia del PC
(--pc-path, por defecto remote_agent/ local). Falla si difieren nombres,
parámetros, riesgos, timeouts o módulos.

Uso:
  python agent_pc/verify_sync.py [--pc-path C:\\JARVIS-PC\\remote_agent]
"""
import argparse
import importlib.util
import sys
from pathlib import Path

JROOT = Path(__file__).resolve().parent.parent
if str(JROOT) not in sys.path:
    sys.path.insert(0, str(JROOT))


def _load_manifests(actions_path: Path) -> dict:
    # La carpeta del actions.py también al path: el fichero del PC trae
    # fallback a imports directos (asi los resuelve el PC con cwd=agent_pc).
    _dir = str(actions_path.parent)
    if _dir not in sys.path:
        sys.path.insert(0, _dir)
    spec = importlib.util.spec_from_file_location("_cmp_actions",
                                                 str(actions_path))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        print(f"ERROR cargando {actions_path}: {e}")
        raise SystemExit(2)
    out = {}
    for m in getattr(mod, "MANIFESTS", []) or []:
        out[m.get("name", "?")] = {
            "params": m.get("params", {}),
            "risk": str(m.get("risk", "")),
            "timeout": m.get("timeout"),
            "module": m.get("module", ""),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pc-path", default=str(JROOT / "remote_agent"),
                    help="carpeta remote_agent del PC (o local)")
    args = ap.parse_args()
    repo_actions = JROOT / "remote_agent" / "actions.py"
    pc_actions = Path(args.pc_path) / "actions.py"
    if not pc_actions.exists():
        print(f"FALTA: {pc_actions} (¿--pc-path mal?)")
        return 2
    repo = _load_manifests(repo_actions)
    pc = _load_manifests(pc_actions)
    only_repo = sorted(set(repo) - set(pc))
    only_pc = sorted(set(pc) - set(repo))
    diffs = []
    for name in sorted(set(repo) & set(pc)):
        if repo[name] != pc[name]:
            diffs.append((name, repo[name], pc[name]))
    print(f"repo manifiestos: {len(repo)}  pc manifiestos: {len(pc)}")
    if only_repo:
        print(f"solo en repo: {only_repo}")
    if only_pc:
        print(f"solo en PC: {only_pc}")
    for name, r, p in diffs:
        print(f"DIFIERE {name}: repo={r} pc={p}")
    if only_repo or only_pc or diffs:
        print("RESULTADO: OUT OF SYNC (actualiza ambos lados a la vez)")
        return 1
    print("RESULTADO: SYNC OK (manifiestos y riesgos idénticos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
