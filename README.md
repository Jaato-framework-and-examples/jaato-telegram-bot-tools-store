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

### For bots: contribute with `share_tool` (bring your own token)

A jaato bot proposes one of its installed tools by calling its `share_tool` host
tool, which opens the PR for you (fork → branch → PR, provenance-stamped).

The store is **open**, so there is **no shared key**: each bot authenticates as
**its owner's own GitHub account** and forks/PRs as itself.

1. Create a GitHub account for the bot — a normal, **non-admin** account that does
   *not* have write access to this store (so it can fork it).
2. On that account, make a **classic PAT** with the **`public_repo`** scope only.
3. Put it in the bot's environment as **`JAATO_TOOLSTORE_GH_TOKEN`** (the jaato
   Telegram bot's `deploy-vps.sh` prompts for it and preserves it across redeploys).

The bot then forks this repo, commits `tools/<name>.py` to a branch, and opens a
PR as that account; a maintainer reviews + merges. No central key, PRs are
self-attributed, and a leaked token affects only that one bot. (This is also why a
single **GitHub App is deliberately not used** — one app would mean one shared key
across every bot, or every contributor registering their own app.)

## Review-wake (optional): the bot reacts to your PR review automatically

When a maintainer reviews a `share_tool` PR, the bot that opened it can be **woken
to address the feedback on its own** — no human relaying "the reviewers commented,
go fix it". Opt-in, off by default.

**How it works (no secret in the PR).** At share time the bot registers a
*session-scoped* wake binding on its own daemon — declaring the store's **public**
signing key as the trust anchor — and embeds a non-secret routing marker in the PR
body (`<!-- jaato-wake endpoint=... -->`). When a review is submitted, this repo's
`wake-relay` workflow signs a small wake body with the store's **private** key and
POSTs it to that endpoint. The daemon verifies the signature against the key the bot
declared, then wakes the session (reviving it if idle) with the review text —
delivered as **untrusted data**, never as instructions. Full design:
`jaato-client-telegram/docs/design/pr-review-feedback-loop.md`.

**The store keypair.** The **public** half is published here as
[`wake-pubkey.pem`](wake-pubkey.pem); the **private** half lives only as this repo's
`STORE_WAKE_PRIVKEY` Actions secret. Asymmetric by design: holding the public key
lets you *verify* a wake but never *forge* one.

**Enabling it on a bot (both required, else off):**
1. `JAATO_TOOLSTORE_WAKE_PUBKEY` = the contents of `wake-pubkey.pem` — the key the
   bot's session declares it trusts (a deliberate trust decision).
2. `JAATO_WAKE_PUBLIC_ENDPOINT` = the bot's own daemon wake URL, reachable from
   GitHub Actions (e.g. `https://your-host/wake`; the ingress is configured in the
   daemon's `~/.jaato/wake.json`). Safe to expose — every wake is signature-gated.

Trust is **per binding, per session**: a bot is only wakeable for the PRs it opened,
and only by wakes signed with the store key it declared.

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
