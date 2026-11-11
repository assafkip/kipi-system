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

So a caller hands this module text written for his phone, and
`test_founder_message_census.py` runs each caller's real message through
`phone_gate`, the same gate sequence. An engineering signal never comes here: it goes
to Sana through `engineering_route.to_sana`, on purpose, instead of being bounced by
chief.

## When chief would refuse anyway: the fallback line

Some messages carry other people's words: a mail subject like "Re: ASK-4479 invoice
question" in the morning brief. Chief refuses the whole brief for that id (PR #749
review, major 2). So the child runs `plan` BEFORE `post_to`: `phone_gate` on the exact
texts `_post` will check. On a refusal it never calls `post_to` with that text (that
call is what files the Sana ticket). It saves the full text with chief's
`phone_text.save_long` and sends one line, "<kind> is in the app Chat: <link>", which
passes the gate. The verdict says `fallback: true`, with chief's reasons in
`gate_reasons`. A caller names its kind (`deliver(..., kind="Morning brief")`).

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
DEFAULT_KIND = "A kipi message"

#: The line after a message whose `detail` was saved, and the line when it was not.
DETAIL_SAVED = "Full list in the app Chat: {link}"
DETAIL_UNSAVED = "The full list could not be saved to the app today."
#: The one line sent instead of a text chief's gate would refuse.
FALLBACK_LINE = "{kind} is in the app Chat: {link}"

#: The child loads THIS file by path and runs `child()` inside chief's checkout (its
#: cwd), so `from chief import ...` resolves there. Code, not a string: the pre-check
#: and the fallback are too much logic to keep untested in a `-c` literal, and one
#: `phone_gate` serves both the child and the census. chief's post_to is a FUNCTION
#: with package-relative imports, so it is never run as a file (ImportError, the
#: fleet-api-report.py first-live-run scar).
_SNIPPET = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('founder_notify_child', sys.argv[1])\n"
    "mod = importlib.util.module_from_spec(spec)\n"
    "sys.modules['founder_notify_child'] = mod\n"
    "spec.loader.exec_module(mod)\n"
    "sys.exit(mod.child(sys.argv[2:]))\n"
)


def _link(app_link: str, saved) -> str:
    """save_long's answer as a link: a row id deep-links (DEC-58), True is the plain Chat."""
    return app_link + (f"/chat?m={saved}" if isinstance(saved, str) else "/chat")


def with_detail(message: str, saved, app_link: str) -> str:
    """The text post_to receives when `detail` was given. `saved` is save_long's
    answer: a row id, True (saved, no id) or a falsy value (not saved). Pure."""
    if saved:
        return message.rstrip() + "\n" + DETAIL_SAVED.format(link=_link(app_link, saved))
    return message.rstrip() + "\n" + DETAIL_UNSAVED


def fallback_line(kind: str, saved, app_link: str) -> str:
    return FALLBACK_LINE.format(kind=kind, link=_link(app_link, saved))


def phone_gate(ping_gate, phone_text, text: str, label: str = LABEL, saver=None) -> tuple:
    """(send, reasons, words): chief's telegram_out._post send(), call for call.

    Label prefix, plain_links, the whole-text engineering check when the text does
    not fit, the probe of the cut line, dm_length, then the final check_whatsapp
    with the app link standing for the action (DEC-68). post_to passes no
    alert_class, so neither does this.

    `saver` is the one dm_length uses for the final line, as `_post` passes its own.
    The child passes chief's real save_long (cached), so a failed save yields the
    long cut text `_post` would gate, not a link (PR #749 review round 2, minor 3).
    None is a stand-in that assumes the save succeeds: pure, and what the census
    uses. The probe's stand-in is chief's own (`lambda _t: True` in `_post`)."""
    link = phone_text.APP_LINK
    t = phone_text.plain_links((text or "").strip())
    if not t:
        return False, ["empty"], []
    shown = f"{label}: {ping_gate.unquote(t).strip()}"
    quoted = f"{label}: {t.strip()}"
    if not phone_text.fits(shown):
        whole = ping_gate.check_whatsapp(f"{quoted} {link}", alert_class=None)
        if "engineering-on-whatsapp" in (whole.get("reasons") or []):
            return False, whole.get("reasons"), whole.get("words")
        probe = ping_gate.check_whatsapp(f"{phone_text.dm_length(shown, saver=lambda _t: True)} {link}",
                                         alert_class=None)
        if not probe.get("send"):
            return False, probe.get("reasons"), probe.get("words")
    line = phone_text.dm_length(shown, saver=saver or (lambda _t: "row1"))
    gate = ping_gate.check_whatsapp(f"{quoted if line == shown else line} {link}", alert_class=None)
    return bool(gate.get("send")), gate.get("reasons"), gate.get("words")


def plan(ping_gate, phone_text, text: str, kind: str = DEFAULT_KIND, save=None, label: str = LABEL,
         saver=None) -> dict:
    """What post_to receives, decided before post_to runs. `text` None: send nothing.

    A text the gate passes goes as is. A refused one is saved whole with `save`
    (chief's save_long by default) and replaced by the fallback line, which is gated
    too. A save that fails, or a fallback line the gate refuses, sends nothing and
    says why: a refused text is never handed to post_to. An empty message sends and
    saves nothing (PR #749 review round 2, minor 4: it became a link to a blank note).
    `saver` goes to phone_gate, see there."""
    if not (text or "").strip():
        return {"text": None, "fallback": False, "reason": "empty message: nothing sent or saved"}
    ok, reasons, words = phone_gate(ping_gate, phone_text, text, label, saver=saver)
    if ok:
        return {"text": text, "fallback": False}
    kept = (save or phone_text.save_long)(text)
    out = {"fallback": True, "gate_reasons": list(reasons or []), "gate_words": list(words or [])[:6],
           "full_saved": bool(kept)}
    if not kept:
        return {**out, "text": None,
                "reason": "chief's phone gate refused it and the full text could not be saved to the app"}
    line = fallback_line(kind, kept, phone_text.APP_LINK)
    ok2, reasons2, _ = phone_gate(ping_gate, phone_text, line, label)
    if not ok2:
        return {**out, "text": None, "reason": "the fallback line was refused too: " + ", ".join(reasons2 or [])}
    return {**out, "text": line}


def child(argv) -> int:
    """Runs inside chief's checkout as `python3 -c _SNIPPET`. Prints chief's verdict as JSON.

    The call stays `post_to(chat, text, "kipi", saver=saver)`, the shape chief's
    tests/test_post_to_consumer_contract.py pins (chief #374)."""
    from chief import phone_text, ping_gate, telegram_out
    chat, text, label, detail, kind = (list(argv) + [""] * 5)[:5]
    kept = None
    if detail:
        kept = phone_text.save_long(detail)
        text = with_detail(text, kept, phone_text.APP_LINK)
    # ONE saver for the pre-check and for post_to, cached by text. The pre-check then
    # cuts the final line exactly as _post will, failed save included, and _post
    # reuses the answer instead of saving the same text twice.
    kept_long = {}

    def saver(t):
        if t not in kept_long:
            kept_long[t] = phone_text.save_long(t)
        return kept_long[t]

    p = plan(ping_gate, phone_text, text, kind or DEFAULT_KIND, label=label, saver=saver)
    if p["text"] is None:
        res = {"delivered": False, "refused": True, "reason": p["reason"]}
    else:
        asked = []

        def post_saver(t):
            asked.append(t)
            return saver(t)

        res = dict(telegram_out.post_to(chat, p["text"], label, saver=post_saver))
        if asked:
            res.update(collapsed=True, saved=bool(saver(asked[-1])), link=phone_text.APP_LINK + "/chat")
    if p["fallback"]:
        res.update({k: p[k] for k in ("fallback", "gate_reasons", "full_saved")})
    if detail:
        res["detail_saved"] = bool(kept)
    print(json.dumps(res, sort_keys=True, default=str))
    return 0 if (res.get("delivered") or res.get("held") or res.get("queued")) else 1


def _argv(message, chat, detail, kind):
    raw = os.environ.get("KIPI_FOUNDER_NOTIFY_CMD")
    if raw:
        return shlex.split(raw) + [message], None
    root = os.environ.get("KIPI_CHIEF_ROOT") or DEFAULT_CHIEF_ROOT
    return ["python3", "-c", _SNIPPET, os.path.abspath(__file__), chat, message, LABEL,
            detail or "", kind or DEFAULT_KIND], root


def _under_test() -> bool:
    """The one place the pytest guard is read, so a test that injects a runner can
    lift it for its case. pytest re-sets PYTEST_CURRENT_TEST at the start of each
    phase, so deleting the env var in a fixture does not survive into the call."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def deliver(message: str, chat: str | None = None, runner=None, timeout: int = 60,
            detail: str | None = None, kind: str | None = None) -> dict:
    """Put `message` in front of the founder. Returns chief's verdict as a dict.

    THE FIXTURE REFUSAL lives here rather than in per-test stubs. Per-test stubbing
    only protects the tests somebody remembered to fix, never the one written
    tomorrow (scar 2026-08-28: a new test posted six duplicate alerts to the
    founder's channel). `refused: True` and `delivered: False` are separate keys on
    purpose: a refusal that read as a delivery would let a suite satisfy a delivery
    assertion without a message existing.

    `runner` is the injectable subprocess seam (argv, cwd, timeout) -> (rc, stdout).
    `kind` names the message in the fallback line ("Morning brief").
    """
    if _under_test():
        return {"delivered": False, "refused": True,
                "reason": "running under pytest; the founder is never paged by a test"}
    chat = chat or os.environ.get("KIPI_FOUNDER_CHAT") or DEFAULT_CHAT
    argv, cwd = _argv(message, chat, detail, kind)
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
    if answer.get("fallback"):
        result["fallback"] = True
        result["full_saved"] = bool(answer.get("full_saved"))
        result["gate_reasons"] = [str(r) for r in (answer.get("gate_reasons") or [])][:8]
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
