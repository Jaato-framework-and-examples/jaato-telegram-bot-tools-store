"""Store review-wake relay — STAGE 1 (prepare).

Runs on ``pull_request_review`` which, for a FORK PR, has NO access to repo secrets
(GitHub withholds them from fork-PR-associated events). Store contributed-tool PRs
are always from forks, so the signing key is simply never available here. This stage
therefore does only the secret-free work: parse the review event, build the wake
payload (wake_ref, text, event_id) and read the NON-secret endpoint marker the bot
embedded in the PR body, then write ``wake_payload.json`` for STAGE 2 to sign. If
there is nothing to relay (not a submitted review, empty body, or no marker) it
writes no file and STAGE 2 skips.

This runs TRUSTED base code (the workflow checks out ``ref: default_branch``, never
the PR head). The review text is attacker-influenceable but travels as DATA — the
daemon wraps it as untrusted content before the model sees it.
See jaato-client-telegram/docs/design/pr-review-feedback-loop.md.
"""

import json
import os
import re
import sys

_MARKER = re.compile(r"<!--\s*jaato-wake\s+endpoint=(\S+)\s*-->")
_OUT = "wake_payload.json"


def main() -> int:
    event = json.load(open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8"))
    if event.get("action") != "submitted":
        print("not a submitted review; skipping")
        return 0
    review = event.get("review") or {}
    pr = event.get("pull_request") or {}
    repo = event.get("repository") or {}

    body_text = (review.get("body") or "").strip()
    if not body_text:
        print("review carries no body text; nothing to relay")
        return 0

    # Endpoint is a NON-secret routing marker the bot embedded in the PR body at
    # share time. No marker => the bot didn't arm review-wake; nothing to do.
    m = _MARKER.search(pr.get("body") or "")
    if not m:
        print("no jaato-wake endpoint marker in PR body; bot did not arm review-wake")
        return 0

    number = pr.get("number")
    payload = {
        "wake_ref": f"github-pr:{repo.get('full_name')}#{number}",
        # STABLE resource id (the review's own id) so a redelivered review dedups on
        # the daemon (bounded-LRU exact match) — NOT a per-delivery id.
        "event_id": f"review:{review.get('id')}",
        "text": f"Review on PR #{number} by "
                f"{(review.get('user') or {}).get('login', 'a reviewer')}: {body_text}",
        "source": "github-pr",
        "endpoint": m.group(1),
    }
    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    print(f"prepared wake payload for {payload['wake_ref']} -> {payload['endpoint']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
