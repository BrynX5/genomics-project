#!/usr/bin/env python3
"""
PostToolUse hook: after Claude writes or edits a file under data/, validate it against its contract.

Exit 0  -> fine (or the file has no contract)
Exit 2  -> contract broken; stderr goes back to Claude, which must fix the data before moving on
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path(__file__).resolve().parents[2]))
VENV_PY = ROOT / ".venv" / "bin" / "python"


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    path = (event.get("tool_input") or {}).get("file_path") or ""
    if not path:
        return 0
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    try:
        rel = p.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return 0
    if rel.parts[:1] != ("data",) or p.suffix != ".csv":
        return 0

    py = str(VENV_PY) if VENV_PY.exists() else sys.executable
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "RXGENOME_ROOT": str(ROOT)}
    r = subprocess.run([py, "-m", "rxgenome.validate", "--path", str(p)],
                       capture_output=True, text=True, env=env, cwd=ROOT)
    if r.returncode == 0:
        return 0
    print(f"{rel} breaks its data contract. Fix the data (not the contract) before continuing.\n"
          f"Run `make describe` for the rules.\n{r.stdout}{r.stderr}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
