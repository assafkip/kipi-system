#!/usr/bin/env python3
"""The ONE way anything in this repo puts a message in front of the founder.

RULE-2026-11-11-A (founder, 2026-11-11: "No bots should be there"). This module
replaces slack_founder.py, which posted to Slack by webhook or bot token. Every byte
of that wire code is gone. A founder message now goes to Telegram through chief's
`telegram_out.post_to`, after chief's own ping gate and caps. Same shape as
consulting's `failure_notice.send_telegram`.

WHY THE `deliver()` SHAPE STAYED. Seven scripts load a sibling module and call
`deliver(message)`, then record the returned dict. Keeping the verb and the dict
(`delivered`, `reason`, `refused`) means each caller changed one filename and nothing
about how it treats a failure.

## Why this is not slack-notify.sh / alert-to-linear.py

Those are the FLEET ALERT PATH: an engineering signal becomes a Linear ticket for
Sana, and nobody is paged. A morning brief or a digest the founder asked to read is
the other kind. Routing it through the ticket path drops his day into Sana's triage
queue, which is the defect the old module's header recorded on 2026-08-10.

## The one rule

**Delivery is what chief said, never what the process exited with.** chief's
`post_to` returns a dict whose `delivered` key is the verdict. A message chief held
for retry reports `held` and counts as delivered, the way chief reports it. The
child process prints that dict as JSON and exits 0 only on delivery, and this module
reads the JSON.

## The seam, and why it is not a machine path

The public skeleton must not hardcode where chief lives.
  KIPI_FOUNDER_NOTIFY_CMD  test seam: an argv whose last argument is the text; its
                           stdout JSON (or exit code) is the verdict.
  KIPI_CHIEF_ROOT          chief's checkout; default is home-relative, the same
                           default fleet-api-report.py uses.
  KIPI_FOUNDER_CHAT        which chief chat (default "chief").
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess

DEFAULT_CHIEF_ROOT = os.path.join(os.path.expanduser("~"), "projects", "chief")
DEFAULT_CHAT = "chief"
LABEL = "kipi"

#: chief's post_to is a FUNCTION with package-relative imports, so it is called as
#: a module from chief's own root. Running telegram_out.py as a file dies with
#: ImportError (the same first-live-run scar fleet-api-report.py records).
_SNIPPET = (
    "import json, sys\n"
    "from chief import telegram_out, phone_text\n"
    "saves = []\n"
    "def saver(t):\n"
    "    got = phone_text.save_long(t)\n"
    "    saves.append(bool(got))\n"
    "    return got\n"
    "res = dict(telegram_out.post_to(sys.argv[1], sys.argv[2], sys.argv[3], saver=saver))\n"
    "if saves:\n"
    "    res.update(collapsed=True, saved=saves[-1], link=phone_text.APP_LINK + '/chat')\n"
    "print(json.dumps(res, sort_keys=True, default=str))\n"
    "ok = res.get('delivered') or res.get('held') or res.get('queued')\n"
    "sys.exit(0 if ok else 1)\n"
)


def _argv(message, chat):
    raw = os.environ.get("KIPI_FOUNDER_NOTIFY_CMD")
    if raw:
        return shlex.split(raw) + [message], None
    root = os.environ.get("KIPI_CHIEF_ROOT") or DEFAULT_CHIEF_ROOT
    return ["python3", "-c", _SNIPPET, chat, message, LABEL], root


def _under_test() -> bool:
    """The one place the pytest guard is read, so a test that injects a runner can
    lift it for its case. pytest re-sets PYTEST_CURRENT_TEST at the start of each
    phase, so deleting the env var in a fixture does not survive into the call."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def deliver(message: str, chat: str | None = None, runner=None, timeout: int = 60) -> dict:
    """Put `message` in front of the founder. Returns chief's verdict as a dict.

    THE FIXTURE REFUSAL lives here rather than in per-test stubs. Per-test stubbing
    only protects the tests somebody remembered to fix, never the one written
    tomorrow (scar 2026-08-28: a new test posted six duplicate alerts to the
    founder's channel). `refused: True` and `delivered: False` are separate keys on
    purpose: a refusal that read as a delivery would let a suite satisfy a delivery
    assertion without a message existing.

    `runner` is the injectable subprocess seam (argv, cwd, timeout) -> (rc, stdout).
    """
    if _under_test():
        return {"delivered": False, "refused": True,
                "reason": "running under pytest; the founder is never paged by a test"}
    chat = chat or os.environ.get("KIPI_FOUNDER_CHAT") or DEFAULT_CHAT
    argv, cwd = _argv(message, chat)
    if runner is None:
        def runner(a, c, t):
            done = subprocess.run(a, cwd=c, capture_output=True, text=True, timeout=t)
            return done.returncode, done.stdout or ""
    try:
        rc, out = runner(argv, cwd, timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"delivered": False, "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}
    try:
        answer = json.loads((out or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        answer = {}
    if not isinstance(answer, dict):
        answer = {}
    delivered = rc == 0 and bool(answer.get("delivered") or answer.get("held")
                                 or answer.get("queued") or not answer)
    result = {"delivered": delivered, "transport": "telegram", "chat": chat}
    if answer.get("held"):
        result["held"] = True
    if answer.get("collapsed"):
        result["collapsed"] = True
        result["saved"] = bool(answer.get("saved"))
        result["link"] = str(answer.get("link") or "")
    if not delivered:
        result["reason"] = str(answer.get("reason") or f"exit {rc}, no delivery verdict")[:200]
    return result


def main(argv=None) -> int:
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: founder_notify.py \"message\"", file=sys.stderr)
        return 2
    result = deliver(" ".join(argv))
    print(json.dumps(result))
    return 0 if result.get("delivered") else 1


if __name__ == "__main__":
    raise SystemExit(main())
