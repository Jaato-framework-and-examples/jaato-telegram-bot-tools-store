#!/usr/bin/env python3
"""Generate registry.json from tools/*.py.

The registry is the machine-readable index bots read to browse + install tools.
It is AUTO-GENERATED — never hand-edit registry.json; edit the tool files and let
this run (a GitHub Action regenerates + commits it on merge to main; see
.github/workflows/registry.yml).

For each tools/<name>.py it derives, WITHOUT importing the file (AST only, so a
tool's third-party imports don't need to be installed here):
  - name         module-level TOOL_SCHEMA["name"] (must equal the file stem)
  - description  TOOL_SCHEMA["description"]
  - deps         module-level TOOL_DEPS = [...] if declared, else []  (PyPI names
                 the tool imports; a bot installs them into its tool-venv)
  - sha256       hash of the exact file bytes (the installer re-verifies this)
  - provenance   PRESERVED from the existing registry.json for known tools; a
                 minimal stub for new ones (a maintainer can enrich it).

Usage:  python generate_registry.py [--check]
  (no args)  write registry.json
  --check    exit 1 if registry.json is out of date (CI/preview), don't write
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "tools"
REGISTRY = ROOT / "registry.json"


def _tool_schema(tree: ast.Module) -> ast.Dict | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "TOOL_SCHEMA" for t in node.targets
        ):
            return node.value if isinstance(node.value, ast.Dict) else None
    return None


def _dict_get(dnode: ast.Dict, key: str):
    for k, v in zip(dnode.keys, dnode.values):
        if isinstance(k, ast.Constant) and k.value == key:
            try:
                return ast.literal_eval(v)
            except Exception:
                return None
    return None


def _tool_deps(tree: ast.Module) -> list:
    """Module-level TOOL_DEPS = [...] (PyPI deps the tool imports), else []."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "TOOL_DEPS" for t in node.targets
        ):
            try:
                val = ast.literal_eval(node.value)
                return [str(d) for d in val] if isinstance(val, (list, tuple)) else []
            except Exception:
                return []
    return []


def build() -> dict:
    prev = {}
    if REGISTRY.is_file():
        try:
            for e in json.loads(REGISTRY.read_text()).get("tools", []):
                prev[e["name"]] = e.get("provenance", {})
        except Exception:
            pass

    entries, problems = [], []
    for path in sorted(TOOLS.glob("*.py")):
        if path.name.startswith("_"):
            continue
        src = path.read_text()
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            problems.append(f"{path.name}: syntax error: {e}")
            continue
        schema = _tool_schema(tree)
        if schema is None:
            problems.append(f"{path.name}: no module-level TOOL_SCHEMA dict")
            continue
        name = _dict_get(schema, "name")
        keys = [k.value for k in schema.keys if isinstance(k, ast.Constant)]
        if not name or "parameters" not in keys:
            problems.append(f"{path.name}: TOOL_SCHEMA needs name + parameters")
            continue
        if name != path.stem:
            problems.append(f"{path.name}: name {name!r} must equal file stem")
            continue
        entries.append({
            "name": name,
            "file": f"tools/{path.name}",
            "description": (_dict_get(schema, "description") or "").strip(),
            "deps": _tool_deps(tree),
            "sha256": hashlib.sha256(src.encode()).hexdigest(),
            "provenance": prev.get(name, {"contributed_by": "community", "added": ""}),
        })

    if problems:
        sys.stderr.write("registry: problems found:\n  " + "\n  ".join(problems) + "\n")
        raise SystemExit(2)

    entries.sort(key=lambda e: e["name"])
    return {"version": 1, "tools": entries}


def main() -> int:
    registry = build()
    rendered = json.dumps(registry, indent=2, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        current = REGISTRY.read_text() if REGISTRY.is_file() else ""
        if current != rendered:
            sys.stderr.write("registry.json is OUT OF DATE — run: python generate_registry.py\n")
            return 1
        print("registry.json is up to date")
        return 0
    REGISTRY.write_text(rendered)
    print(f"wrote {REGISTRY.name}: {len(registry['tools'])} tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
