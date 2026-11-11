#!/usr/bin/env python3
"""The ONE way anything in this repo puts a message in front of the founder.

RULE-2026-11-11-A (founder, 2026-11-11: "No bots should be there"). This module
replaces slack_founder.py, which posted to Slack by webhook or bot token. Every byte
of that wire code is gone. A founder message now goes to Telegram through chief's
`telegram_out.post_to`.

## Chief's phone gate runs on every message

Half of the gate is skipped and half is not. `ping_gate._gated` returns False because
nothing here sets `CHIEF_JOB`, so the repeat and affordance rules of `ping_gate.post`
do not apply. But `_post`'s own `send()` calls `ping_gate.check_whatsapp` on every
line, with no `alert_class` (post_to passes none). A line carrying engineering text
(an ASK id, a PR number, a test name, a path, an exit code), a dash or a line over
160 characters is refused, and an engineering refusal is filed to Sana by chief's
`_sana`. The founder gets nothing. That is how the 4pm Linear digest reached nobody
and became a Sana ticket every day (consulting PR #519 review, major).

So a caller hands this module only text written for his phone, and
`test_founder_message_census.py` runs each caller's real message through that same
gate sequence. An engineering signal never comes here: it goes to Sana through
`engineering_route.file`, on purpose, instead of being bounced by chief.

WHY THE `deliver()` SHAPE STAYED. The callers load a sibling module and call
`deliver(message)`, then record the returned dict. Keeping the verb and the dict
(`delivered`, `reason`, `refused`) means each caller changed one filename and nothing
about how it treats a failure.

## A long report: the phone line plus `detail`

`deliver(message, detail=text)` saves `detail` to his app Chat with chief's own
`phone_text.save_long`, then sends `message` with one more line, the app link to that
row (`with_detail`). The phone line is gated as above. The saved detail is a report he
asked for and opens on purpose (the daily digest's issue list, founder 2026-08-13),
never a phone line. If the save fails, the phone line says so instead of a link.

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
reads the JSON. No parseable verdict is not a delivery, even at exit 0: that read as
delivered once, and the morning-brief deadman would have stayed quiet over a brief
that never arrived (PR #519 review, minor).

## The seam, and why it is not a machine path

The public skeleton must not hardcode where chief lives.
  KIPI_FOUNDER_NOTIFY_CMD  test seam: an argv whose last argument is the phone
                           message (a `detail` is chief's to save, so the seam never
                           sees one); its stdout JSON is the verdict.
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

#: The line after a message whose `detail` was saved, and the line when it was not.
#: Passed to the child as arguments so `with_detail` and the child use one wording.
DETAIL_SAVED = "Full list in the app Chat: {link}"
DETAIL_UNSAVED = "The full list could not be saved to the app today."

#: chief's post_to is a FUNCTION with package-relative imports, so it is called as
#: a module from chief's own root. Running telegram_out.py as a file dies with
#: ImportError (the same first-live-run scar fleet-api-report.py records).
#: The detail branch mirrors `with_detail` line for line;
#: test_founder_notify.TestDetail runs it against a fake chief and compares.
_SNIPPET = (
    "import json, sys\n"
    "from chief import telegram_out, phone_text\n"
    "chat, text, label, detail, saved_line, unsaved_line = sys.argv[1:7]\n"
    "kept = None\n"
    "if detail:\n"
    "    kept = phone_text.save_long(detail)\n"
    "    where = ('/chat?m=%s' % kept) if isinstance(kept, str) else '/chat'\n"
    "    text = text.rstrip() + '\\n' + (saved_line.format(link=phone_text.APP_LINK + where)\n"
    "                                   if kept else unsaved_line)\n"
    "saves = []\n"
    "def saver(t):\n"
    "    got = phone_text.save_long(t)\n"
    "    saves.append(bool(got))\n"
    "    return got\n"
    "res = dict(telegram_out.post_to(chat, text, label, saver=saver))\n"
    "if saves:\n"
    "    res.update(collapsed=True, saved=saves[-1], link=phone_text.APP_LINK + '/chat')\n"
    "if detail:\n"
    "    res['detail_saved'] = bool(kept)\n"
    "print(json.dumps(res, sort_keys=True, default=str))\n"
    "ok = res.get('delivered') or res.get('held') or res.get('queued')\n"
    "sys.exit(0 if ok else 1)\n"
)


def with_detail(message: str, saved, app_link: str) -> str:
    """The text post_to receives when `detail` was given. `saved` is save_long's
    answer: a row id, True (saved, no id) or a falsy value (not saved). Pure."""
    if saved:
        where = f"/chat?m={saved}" if isinstance(saved, str) else "/chat"
        return message.rstrip() + "\n" + DETAIL_SAVED.format(link=app_link + where)
    return message.rstrip() + "\n" + DETAIL_UNSAVED


def _argv(message, chat, detail):
    raw = os.environ.get("KIPI_FOUNDER_NOTIFY_CMD")
    if raw:
        return shlex.split(raw) + [message], None
    root = os.environ.get("KIPI_CHIEF_ROOT") or DEFAULT_CHIEF_ROOT
    return ["python3", "-c", _SNIPPET, chat, message, LABEL, detail or "",
            DETAIL_SAVED, DETAIL_UNSAVED], root


def _under_test() -> bool:
    """The one place the pytest guard is read, so a test that injects a runner can
    lift it for its case. pytest re-sets PYTEST_CURRENT_TEST at the start of each
    phase, so deleting the env var in a fixture does not survive into the call."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def deliver(message: str, chat: str | None = None, runner=None, timeout: int = 60,
            detail: str | None = None) -> dict:
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
    argv, cwd = _argv(message, chat, detail)
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
    # No `or not answer`: an empty or unparseable verdict is chief saying nothing.
    delivered = rc == 0 and bool(answer.get("delivered") or answer.get("held") or answer.get("queued"))
    result = {"delivered": delivered, "transport": "telegram", "chat": chat}
    if answer.get("held"):
        result["held"] = True
    if answer.get("collapsed"):
        result["collapsed"] = True
        result["saved"] = bool(answer.get("saved"))
        result["link"] = str(answer.get("link") or "")
    if "detail_saved" in answer:
        result["detail_saved"] = bool(answer["detail_saved"])
    if not delivered:
        why = answer.get("reason") or (f"exit {rc}, no delivery verdict from chief" if not answer
                                       else f"exit {rc}, chief did not report a delivery")
        result["reason"] = str(why)[:200]
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
