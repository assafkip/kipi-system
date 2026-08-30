#!/usr/bin/env python3
"""The ONE way anything in this repo puts a message in front of the founder.

## Why this is not slack-notify.sh

`slack-notify.sh` is the FLEET ALERT PATH. Founder-directed 2026-08-10 ("I dont
want to see any of these. Any of the ones that need attention should go to Sana
- not me"), it was repointed to file a Linear ticket, and its own header says
"Nothing in this file sends to Slack." It exits 0 on a ticket, which is a true
statement about a different action than the one intended. Routing the founder's
morning brief through it would drop his day into Sana's triage queue.

## Why a module and not a second copy of founder_notify.sh

`cole-gtm/gtm/scripts/lib/founder_notify.sh` already does this correctly for the
podcast lane: bot token, `chat.postMessage`, channel C04Q71LA283 (#general in
assafspace, the channel `slack_listener/poll.py` reads his replies FROM, so it is
proven two-way), and it reads `"ok":true` out of the BODY. That script lives in
another repo and cannot be imported. This is the skeleton's copy of that
mechanism so the fleet has one, rather than a third variant appearing next month.

## Two transports, in this order, and why BOTH

1. **Incoming webhook** (`~/.config/kipi/slack-webhook`). This is the mechanism
   `daily-linear-digest.py` uses and the one the plan named.
2. **Bot token + chat.postMessage** (`~/.config/kipi/slack-bot-token`).

Transport 2 is not a nicety. Measured 2026-08-30: the webhook file does not
exist. It was retired on 2026-08-19 (`slack-webhook.retired-2026-08-19` is still
on disk beside an older `slack-webhook.old-workspace`), and NOTHING was
repointed. `daily-linear-digest.py`'s own log for that day ends:

    [send] {'delivered': False, 'reason': 'no webhook (env or ~/.config/kipi/slack-webhook)'}

So the founder-directed daily digest has been building a correct message and
delivering it nowhere for eleven days, and the only reason anyone can say that
is that it records the send result separately from the attempt. A webhook-only
brief would have shipped into the same hole on day one. The bot token is live
(`auth.test` -> `{'ok': True, 'team': 'Assaf', 'user': 'colenotify'}`, probed
2026-08-30).

## The one rule

**Delivery is what Slack said, never what the process exited with.** Slack
answers HTTP 200 with the literal body `ok` on a webhook, and HTTP 200 with
`{"ok": false, "error": "..."}` on a rejected `chat.postMessage`. Both look
green to a status code and to `$?`. So every function here returns a dict
carrying Slack's own answer, and the caller records it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# #general in assafspace. Same channel cole-gtm's founder_notify.sh posts to and
# the listener reads from, so a reply is possible rather than a broadcast.
FOUNDER_CHANNEL = os.environ.get("KIPI_FOUNDER_SLACK_CHANNEL", "C04Q71LA283")

STATE_DIR = Path(os.environ.get("KIPI_STATE_DIR", os.path.expanduser("~/.config/kipi")))
WEBHOOK_FILE = Path(os.environ.get("KIPI_SLACK_WEBHOOK_FILE", STATE_DIR / "slack-webhook"))
BOT_TOKEN_FILE = Path(os.environ.get("KIPI_SLACK_BOT_TOKEN_FILE",
                                     STATE_DIR / "slack-bot-token"))

SLACK_POST_URL = "https://slack.com/api/chat.postMessage"


def _read_secret(path: Path) -> str:
    """A secret file's contents, or "". Never raises; a missing credential is a
    reportable state, not a crash inside a 7am job."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _default_opener(req, timeout):
    import urllib.request
    return urllib.request.urlopen(req, timeout=timeout)


def _post(url: str, data: bytes, headers: dict, opener, timeout: int):
    """(body, http_status, transport_error). Never raises."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    opener = opener or _default_opener
    try:
        with opener(req, timeout) as resp:
            return resp.read().decode(errors="replace").strip(), resp.status, None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:200]
        return body, exc.code, None
    except Exception as exc:  # noqa: BLE001
        return "", None, f"{type(exc).__name__}: {str(exc)[:160]}"


def post_webhook(url: str, message: str, opener=None, timeout: int = 30) -> dict:
    """Slack incoming webhook. Success is the literal body `ok`, nothing else."""
    body, status, transport_error = _post(
        url, json.dumps({"text": message}).encode(),
        {"Content-Type": "application/json"}, opener, timeout)
    if transport_error:
        return {"delivered": False, "transport": "webhook", "reason": transport_error}
    return {"delivered": body == "ok", "transport": "webhook",
            "http": status, "body": body[:200]}


def post_bot(token: str, channel: str, message: str, opener=None,
             timeout: int = 30) -> dict:
    """chat.postMessage. Slack returns HTTP 200 for a REFUSED post, with
    `{"ok": false, "error": "channel_not_found"}` in the body. Reading the status
    line alone reports that refusal as a delivered message."""
    payload = json.dumps({"channel": channel, "text": message}).encode()
    headers = {"Authorization": f"Bearer {token}",
               "Content-type": "application/json; charset=utf-8"}
    body, status, transport_error = _post(SLACK_POST_URL, payload, headers,
                                          opener, timeout)
    if transport_error:
        return {"delivered": False, "transport": "bot", "reason": transport_error}
    try:
        answer = json.loads(body)
    except ValueError:
        return {"delivered": False, "transport": "bot", "http": status,
                "reason": f"unparseable Slack answer: {body[:120]}"}
    out = {"delivered": answer.get("ok") is True, "transport": "bot",
           "http": status, "channel": channel}
    if not out["delivered"]:
        out["error"] = answer.get("error") or body[:120]
    return out


def deliver(message: str, webhook: str | None = None, token: str | None = None,
            channel: str | None = None, opener=None, timeout: int = 30) -> dict:
    """Put `message` in front of the founder. Returns Slack's verdict.

    THE FIXTURE REFUSAL, and it lives here rather than in per-test stubs.
    Settled twice already in this fleet (`founder_notify.sh`,
    `alert-to-linear.py`, `tests/test_no_test_can_file_a_ticket.py`): per-test
    stubbing only protects the tests somebody remembered to fix, never the one
    written tomorrow. Scar 2026-08-28: a new test called a live episode lookup
    and posted six duplicate alerts to #general about July episodes; the founder
    saw the spam and asked what it was.

    `refused: True` and `delivered: False` are separate keys on purpose. A
    refusal that read as a delivery would let a suite satisfy a delivery
    assertion without a message existing.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"delivered": False, "refused": True,
                "reason": "running under pytest; the founder is never paged by a test"}

    webhook = webhook if webhook is not None else (
        os.environ.get("KIPI_SLACK_WEBHOOK") or _read_secret(WEBHOOK_FILE))
    token = token if token is not None else (
        os.environ.get("KIPI_SLACK_BOT_TOKEN") or _read_secret(BOT_TOKEN_FILE))
    channel = channel or FOUNDER_CHANNEL

    attempts = []
    if webhook.startswith("https://hooks.slack.com/"):
        result = post_webhook(webhook, message, opener=opener, timeout=timeout)
        if result.get("delivered"):
            return result
        attempts.append(result)
    elif webhook:
        attempts.append({"delivered": False, "transport": "webhook",
                         "reason": "configured value is not a Slack incoming-webhook URL"})

    if token:
        result = post_bot(token, channel, message, opener=opener, timeout=timeout)
        if result.get("delivered"):
            # Say which transport carried it. A silent failover is how a dead
            # primary stays dead: the webhook has been broken since 2026-08-19
            # precisely because nothing reported which path was in use.
            result["fallback_after"] = attempts or None
            return result
        attempts.append(result)

    if not attempts:
        return {"delivered": False,
                "reason": f"no Slack credential (env, {WEBHOOK_FILE}, {BOT_TOKEN_FILE})"}
    return {"delivered": False, "attempts": attempts,
            "reason": "; ".join(str(a.get("reason") or a.get("error") or a)
                                for a in attempts)}


def main(argv=None) -> int:
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: slack_founder.py \"message\"", file=sys.stderr)
        return 2
    result = deliver(" ".join(argv))
    print(json.dumps(result))
    return 0 if result.get("delivered") else 1


if __name__ == "__main__":
    raise SystemExit(main())
