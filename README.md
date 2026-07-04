# jaato-telegram-bot-tools-store

Curated, shareable **host tools** for [jaato](https://github.com/Jaato-framework-and-examples)
Telegram bots. Bots browse this store, install a tool (with their user's
acceptance), and contribute new ones back **via pull request**.

A "host tool" is a small Python file a bot loads to extend itself — it runs
**unconfined in the bot process**, so every tool here is human-reviewed before it
lands. Full design: `jaato-client-telegram/docs/design/tool-sharing-marketplace.md`.

## Trust model — why this is a *curated, PR-gated* store

Installing a host tool is arbitrary code execution with the bot's full
privileges. So the store's security *is* its review process:

1. **A bot can only propose.** New tools arrive as PRs. A **human reviews and
   merges** — that review is the security gate. Bots never merge.
2. **Installs are pinned + verified.** A bot installs a tool at a specific
   tagged commit and checks the file against the `sha256` in `registry.json`.
3. **The user always accepts.** Even from this reviewed store, a bot shows the
   tool's code and asks its user before installing.
4. **Provenance is recorded** per tool (who contributed, when).

## Layout

```
tools/                 one <name>.py per tool (module-level TOOL_SCHEMA + async execute)
registry.json          the index — AUTO-GENERATED, never hand-edit (see below)
generate_registry.py   builds registry.json from tools/
.github/workflows/     regenerates + commits registry.json on merge to main
```

## registry.json (auto-generated)

**Do not hand-edit `registry.json`.** `generate_registry.py` builds it from
`tools/` (name + description via AST, `deps` from each tool's `TOOL_DEPS`, and a
`sha256` of the file), and a GitHub Action regenerates + commits it whenever a PR
merges to `main`. Provenance is preserved across regenerations.

```json
{
  "version": 1,
  "tools": [
    {
      "name": "weather",
      "file": "tools/weather.py",
      "description": "Get the weather forecast for today (and tomorrow).",
      "deps": [],
      "sha256": "<hex of tools/weather.py>",
      "provenance": { "contributed_by": "curated", "added": "2026-07-04" }
    }
  ]
}
```

- `deps`: third-party PyPI packages the tool imports — declared in the tool file
  as `TOOL_DEPS = ["skyfield", ...]` (empty/absent = stdlib-only). A bot installs
  them into its per-workspace tool-venv on first use.
- `sha256`: hash of the exact file bytes — the installer re-hashes and refuses on
  mismatch.

## For bots: browse & install

1. `browse_tools` reads `registry.json` (no clone) and lists tools to the user.
2. `install_tool <name>` fetches `tools/<name>.py` at the pinned ref, verifies its
   `sha256`, shows the code, and — on the user's acceptance — installs it through
   the bot's normal approval-gated `register_tool` path.

(These are themselves host tools in `jaato-client-telegram`; see the design doc.)

## Contributing a tool

Because this is its own small repo, a fork is lightweight and structurally scoped
to tools only.

1. **Fork** this repo.
2. Add `tools/<name>.py` — a module-level `TOOL_SCHEMA` (`name` == the file stem,
   `description`, JSON-schema `parameters`) plus `async def execute(args, ctx)`.
   If it imports third-party packages, declare them: `TOOL_DEPS = ["skyfield"]`.
3. **Don't touch `registry.json`** — it's generated. (Optional: run
   `python generate_registry.py` to preview your entry locally.)
4. Open a **pull request**. A maintainer reviews the code (the trust gate) and
   merges. On merge, a workflow regenerates `registry.json` and every bot can
   install your tool.

Model-authored tools are welcome, but **the code is reviewed as code** — write it
to be read.

## Tool contract (host tools)

```python
TOOL_SCHEMA = {
    "name": "example",                       # must equal the file stem
    "description": "What it does.",
    "parameters": {"type": "object", "properties": {...}},
}

async def execute(args: dict, ctx) -> dict:
    # ctx.bot -> aiogram Bot, ctx.chat_id -> int, ctx.ask(...), ctx.wake(text)
    return {"result": "..."}                 # or {"error": "..."}
```

Tools run in the bot process (unconfined). Keep them small, single-purpose, and
readable.
