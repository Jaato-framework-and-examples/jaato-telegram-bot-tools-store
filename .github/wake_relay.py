"""Store-side review-wake relay: on a PR review, sign a wake and POST it to the
contributing bot's daemon so the bot's session is woken to address the feedback.

Runs as a GitHub Action step (see .github/workflows/wake-relay.yml) triggered by
``pull_request_review``. The daemon verifies the Ed25519 signature over the RAW
body bytes against the PUBLIC key the bot declared per-binding (session-scoped
trust); this script holds the matching PRIVATE key as the ``STORE_WAKE_PRIVKEY``
Actions secret. See jaato-client-telegram/docs/design/pr-review-feedback-loop.md.

SECURITY: this workflow runs with the store's secret, so the workflow + this file
MUST come from the trusted base branch (the workflow checks out
``ref: default_branch``), never the PR head — we never execute fork-supplied code.
The wake ``text`` (a reviewer's words) is attacker-influenceable, but it travels as
DATA: the daemon wraps it as untrusted content before the model sees it.
"""

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives.serialization import load_pem_private_key

_MARKER = re.compile(r"<!--\s*jaato-wake\s+endpoint=(\S+)\s*-->")


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
    # share time. No marker ⇒ the bot didn't arm review-wake; nothing to do.
    m = _MARKER.search(pr.get("body") or "")
    if not m:
        print("no jaato-wake endpoint marker in PR body; bot did not arm review-wake")
        return 0
    endpoint = m.group(1)

    number = pr.get("number")
    wake_ref = f"github-pr:{repo.get('full_name')}#{number}"
    author = (review.get("user") or {}).get("login", "a reviewer")
    text = f"Review on PR #{number} by {author}: {body_text}"
    # STABLE resource id (the review's own id) — NOT the per-delivery id — so a
    # redelivered review dedups on the daemon (bounded-LRU exact match).
    event_id = f"review:{review.get('id')}"

    # Body B: sign the RAW bytes we POST; never reserialize between sign and send.
    body = json.dumps({
        "wake_ref": wake_ref,
        "text": text,
        "source": "github-pr",
        "event_id": event_id,
        "ts": int(time.time()),
    }).encode("utf-8")

    # The secret is stored base64-encoded on a SINGLE line: a multi-line PEM does
    # not survive GitHub's secret->env injection intact (framing breaks). Decode
    # back to the raw PEM bytes here. Set it with: base64 -w0 key.pem | gh secret set.
    priv = load_pem_private_key(base64.b64decode(os.environ["STORE_WAKE_PRIVKEY"]), password=None)
    sig = base64.b64encode(priv.sign(body)).decode()

    req = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Jaato-Wake-Signature": sig,
            "X-Jaato-Wake-Key-Id": "store-ed25519-1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 — operator-declared endpoint
            print(f"wake POST {r.status}: {r.read().decode()[:200]}")
            return 0  # 2xx (incl. idempotent duplicate) = delivered
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:200]
        # 4xx = permanent (bad sig / unknown-or-expired binding / malformed) — a
        # re-run won't help; 5xx = transient (revive/drive failed) — worth a re-run.
        klass = "transient (retryable)" if e.code >= 500 else "permanent"
        print(f"wake POST {e.code} [{klass}]: {detail}")
        return 1  # non-zero flags the run red for visibility
    except Exception as e:  # noqa: BLE001 — network / endpoint unreachable
        print(f"wake POST failed to reach {endpoint}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
