"""Auditoria JSONL append-only con cadena de hashes (ambos lados).

Entrada: {seq, ts, side, trace_id, action, risk, grant_id, result, prev, hash}
hash = sha256(prev + canonico(resto)). verify() recalcula toda la cadena.
"""
import json
import time
from pathlib import Path

try:
    from remote_agent import protocol as P
except ImportError:
    import protocol as P


class AuditLog:
    def __init__(self, path: str | Path, side: str):
        self.path = Path(path)
        self.side = side
        if self.path.parent and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = self._last_seq()
        self._prev = self._last_hash()

    def _read(self) -> list:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def _last_seq(self) -> int:
        rows = self._read()
        return rows[-1]["seq"] if rows else 0

    def _last_hash(self) -> str:
        rows = self._read()
        return rows[-1]["hash"] if rows else "GENESIS"

    def append(self, action: str, risk: str, result: str,
               trace_id: str = "-", grant_id: str = "-",
               src: str = "-", **extra) -> dict:
        self._seq += 1
        entry = {
            "seq": self._seq,
            "ts": int(time.time()),
            "side": self.side,
            "trace_id": trace_id,
            "action": action,
            "risk": risk,
            "grant_id": grant_id,
            "src": src,
            "result": result,
            "prev": self._prev,
        }
        entry.update(extra)
        entry["hash"] = P.sha256_hex(entry["prev"] + P.canonical(entry))
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._prev = entry["hash"]
        return entry

    def verify(self) -> tuple[bool, str]:
        prev = "GENESIS"
        for row in self._read():
            expect = P.sha256_hex(prev + P.canonical(
                {k: v for k, v in row.items() if k != "hash"}))
            if row.get("prev") != prev or row.get("hash") != expect:
                return False, f"manipulacion en seq={row.get('seq')}"
            prev = row["hash"]
        return True, "ok"
