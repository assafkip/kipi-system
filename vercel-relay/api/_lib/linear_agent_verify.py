#!/usr/bin/env python3
"""Linear-side front door for the Sana agent. Linear is the INTERFACE; it is not the executor.

WHAT THIS IS
------------
Linear delegation (assign an issue to the Sana app user, or @mention it) arrives here
as an `AgentSessionEvent` webhook. This process verifies it, acknowledges it, and hands
the work to the SAME local runner that already exists (`linear-worker.sh --apply
--issue ASK-N`). It then posts the outcome back into the Linear session as Sana.

WHY NOT LINEAR'S OWN CODING SESSIONS
------------------------------------
Because none of this fleet's gates exist inside Linear's sandbox: the capability gate,
token-guard, destructive-op-deny, the reproducer-first discipline, prd-os receipts, the
scar comments. A Linear-native coding session would be a generic model wearing Sana's
name and would route around every gate that makes this board trustworthy. So the
executor stays local and Linear only carries the conversation.

THE 5-SECOND RULE IS THE ARCHITECTURE
-------------------------------------
Linear retries a webhook that "takes longer than 5 seconds (5000ms) to respond, or
responds with a non-200 HTTP status code". A run takes minutes. So the HTTP handler
MUST return 200 before doing any work -- otherwise Linear retries, and every retry
starts ANOTHER run of the same issue against the same worktree. Ack first, work after,
in a background thread. This ordering is load-bearing, not stylistic.

TEST-ISOLATION SEAMS
--------------------
Same convention linear-worker.sh already uses (KIPI_NOTIFY / KIPI_PR_REVIEWER /
KIPI_STATE_DIR): every outbound edge is overridable so the suite can drive this
end-to-end without touching Linear or spawning a real run. Unset in production; the
defaults are the real API and the real worker.

  KIPI_LINEAR_API             GraphQL endpoint      (default: real Linear)
  KIPI_LINEAR_AGENT_RUNNER    runner command        (default: real linear-worker.sh)
  KIPI_LINEAR_AGENT_STATE     state dir             (default: ~/.config/kipi)
  KIPI_LINEAR_WEBHOOK_SECRET  webhook signing secret
  KIPI_LINEAR_AGENT_TOKEN     OAuth access token for the app user

Usage:
  linear-agent-receiver.py serve [--port 8787]
  linear-agent-receiver.py handle < payload.json     # one event, no socket (testable)
  linear-agent-receiver.py selftest                  # signature negative self-test
"""
import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

LINEAR_API = os.environ.get("KIPI_LINEAR_API", "https://api.linear.app/graphql")
STATE_DIR = Path(os.environ.get("KIPI_LINEAR_AGENT_STATE", os.path.expanduser("~/.config/kipi")))
RUNNER = os.environ.get("KIPI_LINEAR_AGENT_RUNNER", f"bash {SCRIPT_DIR}/linear-worker.sh")

# Linear retries on non-200 or >5s. Anything slower than this budget must happen
# AFTER the response is flushed.
ACK_BUDGET_MS = 5000
# "verify it's within a minute of the time your system sees it to guard against
# replay attacks" -- Linear webhook docs.
MAX_SKEW_MS = 60 * 1000


# ---------------------------------------------------------------- signature

def verify_signature(raw_body: bytes, header_sig: str, secret: str, now_ms: int = None) -> tuple:
    """Return (ok, reason). Verifies BOTH the HMAC and the replay window.

    Linear signs the RAW body -- not a re-serialized dict. Re-encoding json.loads()
    output changes key order and whitespace and the digest stops matching, which is
    the classic way this check silently starts rejecting every real event. Callers
    must pass the bytes exactly as received.
    """
    if not secret:
        return False, "no signing secret configured"
    if not header_sig:
        return False, "missing Linear-Signature header"

    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header_sig):
        return False, "signature mismatch"

    # Replay guard is part of verification, not a separate optional step. A valid
    # signature on a captured old payload is still an attack.
    try:
        ts = json.loads(raw_body).get("webhookTimestamp")
    except (ValueError, AttributeError):
        return False, "body is not JSON"
    if ts is None:
        return False, "no webhookTimestamp"
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    if abs(now - int(ts)) > MAX_SKEW_MS:
        return False, f"stale webhookTimestamp (skew {abs(now - int(ts))}ms)"

    return True, "ok"


# ---------------------------------------------------------------- parsing

def parse_session_event(payload: dict) -> dict:
    """Pull the few fields we act on out of an AgentSessionEvent.

    Defensive by construction: Linear may add fields, and an agent that requires the
    full shape breaks on their next release. We read what we need and ignore the rest.

    THE IDENTIFIER TRAP. The runner takes a human key (`--issue ASK-123`), but the
    webhook's guaranteed fields are UUIDs (`agentSession.issueId`, `issue.id`). The
    published SDL types the issue as IssueWithDescriptionChildWebhookPayload and does
    NOT promise an `identifier`. Passing a UUID to the runner would match no issue and
    the run would silently pick nothing -- the exact "exits 0, does nothing" shape that
    burned a whole budget day (see linear-worker.sh MAX_ATTEMPTS note). So identifier
    is treated as OPTIONAL here and resolved from the UUID when absent.

    Prompt text also differs by action: `created` carries a preformatted
    `promptContext`; `prompted` carries the new message in `agentActivity.content`.
    Docs prose says `agentActivity.body` while the SDL says `content: JSONObject!` --
    they contradict each other, so read both.
    """
    session = payload.get("agentSession") or {}
    issue = session.get("issue") or {}
    activity = payload.get("agentActivity") or {}
    content = activity.get("content") if isinstance(activity.get("content"), dict) else {}

    return {
        "action": payload.get("action"),
        "session_id": session.get("id"),
        "issue_key": issue.get("identifier"),          # may be absent -- resolve below
        "issue_uuid": session.get("issueId") or issue.get("id"),
        "issue_title": issue.get("title"),
        "prompt": (
            payload.get("promptContext")
            or content.get("body")
            or activity.get("body")
            or (session.get("comment") or {}).get("body")
            or ""
        ).strip(),
    }


_IDENTIFIER_QUERY = "query Issue($id: String!) { issue(id: $id) { identifier } }"


def resolve_issue_key(issue_uuid: str, token: str = None) -> str:
    """UUID -> ASK-123. Returns "" on failure; the caller must treat that as fatal.

    Guessing an identifier is worse than failing: a wrong key dispatches the runner at
    the WRONG issue, and that write is not reversible from here.
    """
    token = token or get_token()   # same chokepoint; resolved at call time
    if not (issue_uuid and token):
        return ""
    body = json.dumps({"query": _IDENTIFIER_QUERY, "variables": {"id": issue_uuid}}).encode()
    req = urllib.request.Request(LINEAR_API, data=body, headers={
        "Content-Type": "application/json", "Authorization": token})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return ((data.get("data") or {}).get("issue") or {}).get("identifier") or ""
    except (urllib.error.URLError, ValueError, OSError):
        return ""


# ---------------------------------------------------------------- state

def _state_file() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / "linear-agent-sessions.json"


def record_session(session_id: str, issue_id: str, status: str) -> None:
    """SINGLE WRITER for the session ledger.

    Every mutation of this file goes through this one function under one lock. The
    worker's attempts ledger learned this the expensive way (sp-53b02cc4): six
    functions each doing their own read-modify-write is a corruption waiting for a
    race, and here the race is real because a webhook thread and a dispatch thread
    both want to write.
    """
    with _LEDGER_LOCK:
        path = _state_file()
        try:
            data = json.loads(path.read_text())
        except (FileNotFoundError, ValueError):
            data = {}
        data[session_id] = {"issue": issue_id, "status": status, "ts": int(time.time())}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)  # atomic: a crash mid-write must not truncate the ledger


_LEDGER_LOCK = threading.Lock()


# ---------------------------------------------------------------- linear api

# ONE definition of the mutation, in one place. Verified against
# linear.app/developers/agent-interaction on 2026-08-01.
_ACTIVITY_MUTATION = """
mutation AgentActivityCreate($input: AgentActivityCreateInput!) {
  agentActivityCreate(input: $input) { success }
}
"""

# Session state is derived by Linear from the LAST emitted activity -- there is no
# manual state field to set. That makes the choice of terminal activity a real
# decision, not cosmetics:
#   response    -> session becomes `complete`   (my turn is over)
#   elicitation -> session becomes `awaitingInput` (I need a human)
#   error       -> session becomes `error`
# Emitting `response` when you actually need input strands the thread silently.
TERMINAL_TYPES = {"response", "elicitation", "error"}


def _load_token_module():
    """Import the hyphenated token module. Separate so an import failure is legible."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "linear_agent_token", SCRIPT_DIR / "linear-agent-token.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_token() -> str:
    """The ONE place a token is obtained. Goes through the rotation chokepoint.

    KIPI_LINEAR_AGENT_TOKEN wins so the suite can drive this without a token store.
    In production it is unset and every call reaches ensure_fresh(), which renews an
    hour before the 24h expiry and PAGES if it cannot. Reading a static token here
    would reintroduce the daily silent death the token module exists to prevent --
    the code would look wired while the refresh never ran.
    """
    env_token = os.environ.get("KIPI_LINEAR_AGENT_TOKEN", "")
    if env_token:
        return env_token
    try:
        return _load_token_module().ensure_fresh()
    except Exception as exc:  # noqa: BLE001
        # Surfaced, never swallowed. ensure_fresh has already paged for the cases it
        # owns; this print is the last-resort trace for the ones it does not.
        print(f"token unavailable: {exc}", file=sys.stderr)
        return ""


def post_activity(session_id: str, content: dict, token: str = None) -> tuple:
    """Emit one AgentActivity. Returns (ok, detail).

    Never raises. A failure to talk to Linear must not kill the dispatch thread --
    the local run is the real work and it has its own logging; losing the comment is
    bad but losing the run is worse.
    """
    token = token or get_token()
    if not token:
        return False, "no usable Linear token"

    body = json.dumps({
        "query": _ACTIVITY_MUTATION,
        "variables": {"input": {"agentSessionId": session_id, "content": content}},
    }).encode()

    req = urllib.request.Request(
        LINEAR_API,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read())
        if payload.get("errors"):
            return False, json.dumps(payload["errors"])[:400]
        return True, "ok"
    except (urllib.error.URLError, ValueError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- dispatch

def handle_event(payload: dict) -> dict:
    """Ack, run, report. Runs on a BACKGROUND thread -- never in the HTTP handler.

    Ordering here is the whole contract:
      1. `thought` inside 10s or Linear marks the session unresponsive.
      2. the local runner does the actual work, with all this fleet's gates.
      3. a terminal activity so the thread does not hang in `active` forever.
    """
    ev = parse_session_event(payload)
    session_id = ev["session_id"]

    if not session_id:
        return {"ok": False, "reason": "no agentSession.id"}

    # Step 1 -- beat the 10s unresponsive timer before doing anything slow.
    post_activity(session_id, {
        "type": "thought",
        "body": f"Picked up {ev['issue_key'] or 'this issue'}. Running the local kipi "
                f"worker (gates: capability, token-guard, destructive-op-deny, "
                f"reproducer-first).",
    })
    record_session(session_id, ev["issue_key"] or ev["issue_uuid"], "running")

    # Resolve only if the webhook did not hand us a human key. One network call, and
    # only on the path that needs it.
    issue_id = ev["issue_key"] or resolve_issue_key(ev["issue_uuid"])

    if not issue_id:
        post_activity(session_id, {
            "type": "elicitation",
            "body": "I could not resolve an issue identifier for this session, so I do "
                    "not know what to run. Delegate me an issue directly and I will "
                    "pick it up.",
        })
        record_session(session_id, ev["issue_uuid"], "awaiting_input")
        return {"ok": False, "reason": "no issue identifier"}

    # Step 2 -- the real executor. Unchanged, fully gated, local.
    cmd = f"{RUNNER} --apply --issue {issue_id}"
    post_activity(session_id, {
        "type": "action", "action": "Running", "parameter": cmd,
    })

    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=None)
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()
    tail = "\n".join(tail[-25:]) if tail else "(no output)"

    # Step 3 -- terminal activity. `response` = my turn is done.
    ok = proc.returncode == 0
    post_activity(session_id, {
        "type": "response" if ok else "error",
        "body": (f"Run finished for **{issue_id}** (exit {proc.returncode}).\n\n"
                 f"```\n{tail}\n```"),
    })
    record_session(session_id, issue_id, "done" if ok else "failed")
    return {"ok": ok, "issue": issue_id, "rc": proc.returncode}


# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        sig = self.headers.get("Linear-Signature", "")
        secret = os.environ.get("KIPI_LINEAR_WEBHOOK_SECRET", "")

        ok, reason = verify_signature(raw, sig, secret)
        if not ok:
            # 401 on a bad signature is correct: Linear retries 5xx, and retrying a
            # forged event forever is not a behaviour worth having.
            self.send_response(401)
            self.end_headers()
            self.wfile.write(reason.encode())
            return

        try:
            payload = json.loads(raw)
        except ValueError:
            self.send_response(400); self.end_headers(); return

        # Only agent sessions. Linear will happily send other event types to this
        # URL if the subscription is widened later; silently running the worker on
        # an unrelated Issue event would be a runaway.
        if payload.get("type") != "AgentSessionEvent":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ignored"); return

        # ACK FIRST. Everything slow happens after this flush, or Linear retries at
        # 5s and we get duplicate concurrent runs of the same issue.
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"accepted")
        self.wfile.flush()

        threading.Thread(target=handle_event, args=(payload,), daemon=False).start()

    def log_message(self, *_args):
        pass  # stdout belongs to the run log, not to http chatter


def serve(port: int) -> None:
    print(f"linear-agent-receiver listening on :{port} -> {RUNNER}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


# ---------------------------------------------------------------- cli

def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else "serve"

    if cmd == "serve":
        port = 8787
        if "--port" in argv:
            port = int(argv[argv.index("--port") + 1])
        serve(port)
        return 0

    if cmd == "handle":
        payload = json.loads(sys.stdin.read())
        print(json.dumps(handle_event(payload), indent=2))
        return 0

    if cmd == "selftest":
        return selftest()

    print(__doc__)
    return 1


def selftest() -> int:
    """Negative-first self-test of the signature gate.

    A check that cannot fail is not a check. So this proves the verifier REJECTS
    each bad case before it is allowed to bless the good one.
    """
    secret = "test-secret-not-a-real-one"
    now = int(time.time() * 1000)
    body = json.dumps({"type": "AgentSessionEvent", "webhookTimestamp": now}).encode()
    good = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    stale_body = json.dumps({"type": "AgentSessionEvent", "webhookTimestamp": now - 120000}).encode()
    stale_sig = hmac.new(secret.encode(), stale_body, hashlib.sha256).hexdigest()

    cases = [
        ("rejects wrong signature",   (body, "deadbeef", secret), False),
        ("rejects empty signature",   (body, "", secret), False),
        ("rejects missing secret",    (body, good, ""), False),
        ("rejects tampered body",     (body + b" ", good, secret), False),
        ("rejects stale timestamp",   (stale_body, stale_sig, secret), False),
        ("accepts a valid event",     (body, good, secret), True),
    ]

    failures = 0
    for name, args, want in cases:
        got, reason = verify_signature(*args, now_ms=now)
        mark = "PASS" if got == want else "FAIL"
        if got != want:
            failures += 1
        print(f"[{mark}] {name}: got={got} ({reason})")

    print(f"\n{len(cases) - failures}/{len(cases)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
