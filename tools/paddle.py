"""Paddle Tournament Organizer

Manages a pool of 8-10 players for weekly paddle matches (4 pairs per session).
Tracks pair history to avoid repeating couples until unavoidable.

Actions:
  init     - Set up the player pool
  pair     - Generate random pairings for a game day, given who is absent
  history  - Show pairing history and stats
  reset    - Clear all history
"""

import json
import random
from datetime import datetime
from pathlib import Path

TOOL_SCHEMA = {
    "name": "paddle",
    "description": (
        "Organize paddle couples from a pool of 8-10 players. Avoids repeating "
        "pairs until unavoidable. Actions: init (set player pool), pair (generate "
        "weekly couples given absentees), history (show stats), reset (clear history)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["init", "pair", "history", "reset"],
                "description": "What to do."
            },
            "players": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of player names. Required for 'init'."
            },
            "absent": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of absent players this week. For 'pair'."
            },
        },
        "required": ["action"],
    },
}

DATA_DIR = Path.home() / ".jaato" / "paddle"
POOL_FILE = DATA_DIR / "players.json"
HISTORY_FILE = DATA_DIR / "history.json"


def _load_json(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_json(path: Path, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _pair_count(history: list[dict], p1: str, p2: str) -> int:
    key = frozenset([p1, p2])
    return sum(
        1 for rd in history
        for couple in rd.get("pairs", [])
        if frozenset(couple) == key
    )


def _generate_pairs(players: list[str], history: list[dict]) -> list[list[str]]:
    """Try many random shuffles, keep the one with fewest repeat couples."""
    n = len(players)
    best = None
    best_max = float("inf")

    for _ in range(3000):
        shuffled = players[:]
        random.shuffle(shuffled)
        pairs = [[shuffled[i], shuffled[i+1]] for i in range(0, n, 2)]
        mx = max(_pair_count(history, a, b) for a, b in pairs)
        if mx < best_max:
            best_max = mx
            best = [p[:] for p in pairs]
        if best_max == 0:
            break

    return best


def _fmt_pairs(pairs: list[list[str]], history: list[dict]) -> str:
    lines = []
    for i, (a, b) in enumerate(pairs, 1):
        c = _pair_count(history, a, b)
        tag = f" ({c}x before)" if c > 0 else " ✨ new"
        lines.append(f"  🏸 Pair {i}: {a} & {b}{tag}")
    return "\n".join(lines)


async def execute(args: dict, ctx) -> dict:
    action = args["action"]

    # ---- INIT ----
    if action == "init":
        players = args.get("players", [])
        if len(players) < 8 or len(players) > 10:
            return {"error": "Need between 8 and 10 players."}
        if len(set(players)) != len(players):
            return {"error": "Duplicate names found."}
        _save_json(POOL_FILE, {"players": players})
        _save_json(HISTORY_FILE, [])
        return {"result": f"Pool set with {len(players)} players:\n" + "\n".join(f"  {i+1}. {p}" for i, p in enumerate(players))}

    # ---- RESET ----
    if action == "reset":
        _save_json(HISTORY_FILE, [])
        return {"result": "History cleared. All couples are fresh!"}

    # ---- HISTORY ----
    if action == "history":
        history = _load_json(HISTORY_FILE)
        if not history:
            return {"result": "No games played yet."}

        lines = []
        for i, rd in enumerate(history, 1):
            lines.append(f"\n📅 Game {i} ({rd.get('date', '?')})")
            absent = rd.get("absent", [])
            if absent:
                lines.append(f"   Absent: {', '.join(absent)}")
            for j, (a, b) in enumerate(rd.get("pairs", []), 1):
                lines.append(f"   🏸 {a} & {b}")

        lines.append("\n\n📊 Pair frequency:")
        counts = {}
        for rd in history:
            for c in rd.get("pairs", []):
                k = frozenset(c)
                counts[k] = counts.get(k, 0) + 1
        for pair, cnt in sorted(counts.items(), key=lambda x: -x[1]):
            names = sorted(pair)
            lines.append(f"  {names[0]} & {names[1]}: {cnt}x")

        return {"result": "\n".join(lines)}

    # ---- PAIR ----
    if action == "pair":
        pool = _load_json(POOL_FILE)
        all_players = pool.get("players", [])
        if len(all_players) < 8:
            return {"error": "No pool set. Run 'init' first with at least 8 players."}

        absent = args.get("absent", [])
        available = [p for p in all_players if p not in absent]

        if len(available) < 8:
            return {"error": f"Only {len(available)} available — need 8."}

        bench = []
        if len(available) > 8:
            random.shuffle(available)
            bench = available[8:]
            available = available[:8]

        history = _load_json(HISTORY_FILE)
        pairs = _generate_pairs(available, history)

        # Save round
        history.append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "absent": absent,
            "pairs": pairs,
        })
        _save_json(HISTORY_FILE, history)

        # Format output
        lines = ["\nToday's couples:\n"]
        if bench:
            lines.append(f"⚠️ On the bench: {', '.join(bench)}\n")
        lines.append(_fmt_pairs(pairs, history))
        return {"result": "\n".join(lines)}

    return {"error": f"Unknown action: {action}"}
