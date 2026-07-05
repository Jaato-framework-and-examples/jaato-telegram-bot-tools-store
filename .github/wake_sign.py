"""Store review-wake relay — STAGE 2 (sign + POST).

Runs on ``workflow_run`` after STAGE 1 (``wake-relay``) completes. Unlike
``pull_request_review`` on a fork PR, ``workflow_run`` runs in the TRUSTED base-repo
context WITH repository secrets — so the Ed25519 signing key (``STORE_WAKE_PRIVKEY``)
is available here and only here. It reads the ``wake_payload.json`` artifact STAGE 1
produced, signs the RAW body bytes, and POSTs the wake to the bot's daemon. No
artifact => STAGE 1 had nothing to relay => skip.

The daemon verifies the signature over the raw body against the PUBLIC key the bot
declared per-binding (session-scoped trust). The key is stored base64-encoded on a
single line (proven to survive GitHub's secret->env injection; set with
``base64 -w0 key.pem | gh secret set``).
See jaato-client-telegram/docs/design/pr-review-feedback-loop.md.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives.serialization import load_pem_private_key

_PAYLOAD = "wake_payload.json"


def main() -> int:
    if not os.path.exists(_PAYLOAD):
        print("no wake payload artifact; nothing to sign")
        return 0
    p = json.load(open(_PAYLOAD, encoding="utf-8"))
    endpoint = p["endpoint"]

    # Body B: sign the RAW bytes we POST; never reserialize between sign and send.
    body = json.dumps({
        "wake_ref": p["wake_ref"],
        "text": p["text"],
        "source": p["source"],
        "event_id": p["event_id"],
        "ts": int(time.time()),
    }).encode("utf-8")

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
        # 4xx = permanent (bad sig / unknown-or-expired binding); 5xx = transient.
        klass = "transient (retryable)" if e.code >= 500 else "permanent"
        print(f"wake POST {e.code} [{klass}]: {detail}")
        return 1
    except Exception as e:  # noqa: BLE001 — network / endpoint unreachable
        print(f"wake POST failed to reach {endpoint}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
