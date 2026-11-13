#!/usr/bin/env python3
"""Census: every message a kipi script hands founder_notify passes chief's real phone gate.

ASK-4479 S2, consulting PR #519 review (major). founder_notify reaches the founder
through chief's `telegram_out.post_to`, and `_post`'s inner `send()` runs
`ping_gate.check_whatsapp` on every line, whatever `CHIEF_JOB` says. A line it
refuses as `engineering-on-whatsapp` reaches nobody and becomes a Sana ticket through
chief's `_sana`. The 4pm Linear digest did exactly that, every day, while its caller
logged "not delivered" to a file nobody reads.

So each caller is in exactly one of two places:
  CASES           founder-facing. Its real message, built by its own code, must pass
                  the same gate sequence `send()` runs.
  ROUTED_TO_SANA  an engineering signal. Its code must reach Sana through the fleet
                  alert path (engineering_route) and never name founder_notify.
A script whose code names founder_notify and is in neither place fails the census.

Chief is imported from KIPI_CHIEF_ROOT or founder_notify's home-relative default and
never written. This repo is public and its CI has no chief checkout, so the gate tests
skip there with that reason; the routing tests run everywhere.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import os
import sys
import tokenize
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"


def _load(stem, filename):
    path = SCRIPTS / filename
    assert path.is_file(), f"missing script: {path}"
    spec = importlib.util.spec_from_file_location(stem, path)
    mod = importlib.util.module_from_spec(spec)
    # Registered: a module never put in sys.modules breaks dataclasses and typing
    # (the browser_session_health loader scar).
    sys.modules[stem] = mod
    spec.loader.exec_module(mod)
    return mod


FN = _load("founder_notify_census", "founder_notify.py")


def _code(path: Path) -> str:
    """Executable source only: comments and docstrings dropped. A module that
    explains why it does NOT use founder_notify is not a caller of it."""
    out, prev = [], None
    with open(path, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and prev in (None, tokenize.INDENT, tokenize.NEWLINE, tokenize.NL,
                                                        tokenize.DEDENT, tokenize.ENCODING):
                prev = tok.type
                continue
            out.append(tok.string)
            prev = tok.type
    return "\n".join(out)


def founder_callers() -> list:
    return sorted(p.name for p in SCRIPTS.glob("*.py")
                  if p.name != "founder_notify.py" and "founder_notify" in _code(p))


@pytest.fixture(scope="module")
def chief(tmp_path_factory):
    root = os.environ.get("KIPI_CHIEF_ROOT") or FN.DEFAULT_CHIEF_ROOT
    if not os.path.isfile(os.path.join(root, "chief", "ping_gate.py")):
        pytest.skip("no chief checkout (KIPI_CHIEF_ROOT unset and the default is absent); "
                    "this public repo's CI has none, so the gate census runs only where chief lives")
    saved = os.environ.get("CHIEF_CONFIG_DIR")
    os.environ["CHIEF_CONFIG_DIR"] = str(tmp_path_factory.mktemp("chief-config"))
    sys.path.insert(0, root)
    from chief import phone_text, ping_gate
    if not os.path.realpath(ping_gate.__file__).startswith(os.path.realpath(root)):
        pytest.skip(f"a different chief package was already imported: {ping_gate.__file__}")
    yield ping_gate, phone_text
    if saved is None:
        os.environ.pop("CHIEF_CONFIG_DIR", None)
    else:
        os.environ["CHIEF_CONFIG_DIR"] = saved


def verdict(chief, text):
    """(send, reasons, words): chief's telegram_out._post send(), call for call.

    Label prefix, plain_links, the whole-text engineering check when the text does
    not fit, the probe of the cut line, dm_length, then the final check_whatsapp
    with the app link standing for the action (DEC-68). post_to passes no
    alert_class, so neither does this."""
    # One replica, the one the child runs before post_to: a second copy here could
    # agree with chief while the child's disagreed.
    return FN.phone_gate(chief[0], chief[1], text)


# ---- the founder-facing callers, each built by its own code --------------------

#: Real worker-log lines (2026-11-11), the shapes the digest's patterns read.
_BLOCKED = (
    "3 issue(s) held at blocked:capability -- the specs are sound, the runner is missing something "
    "it cannot grant itself (ASK-4309 ASK-142 ASK-141)",
    "147 ready-shaped issue(s) UNREACHABLE: no local checkout for (unset), Chief, cole-GTM -- no "
    "dispatcher on this machine can reach them until those repos are cloned and registered",
    "471 ready-shaped issue(s) REFUSED by preflight: the checkout exists but the gate will not let a "
    "dispatcher in -- accountant (remote,credentials,branch-protection)",
)
#: Titles carrying every engineering marker chief refuses: an id, a PR number, a
#: test name, a path, an exit code.
_TITLES = (
    "gate_draft: one number tokenizer reads years and ranges (ASK-4515)",
    "skeleton off Slack, census test (PR #746)",
    "test_no_slack_bots skip list misses the secret scanners",
    "q-system/.q-system/scripts/founder_notify.py says the gate does not run",
    "dispatch exits with exit 2 on a capped round",
)


def _digest(tmp_path, monkeypatch, phone_text):
    mod = _load("daily_linear_digest_census", "daily-linear-digest.py")
    now = dt.datetime.now().astimezone()
    stamp = now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    worker = tmp_path / "linear-worker.log"
    worker.write_text("".join(f"{stamp} worker: {b}\n" for b in _BLOCKED))
    monkeypatch.setattr(mod, "WORKER_LOG", worker)
    monkeypatch.setattr(mod, "DISPATCH_LOG", tmp_path / "dispatch.log")
    monkeypatch.setattr(mod, "BLOCKED_SOURCES", (worker, tmp_path / "dispatch.log"))
    since = now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    nodes = [{"identifier": f"ASK-{4500 + i}", "title": t, "url": "https://linear.app/x/issue/ASK-1",
              "createdAt": since, "completedAt": since} for i, t in enumerate(_TITLES)]
    sent = []
    monkeypatch.setattr(mod, "send", lambda message, detail=None: sent.append((message, detail))
                        or {"delivered": True})
    monkeypatch.setattr(sys, "argv", ["daily-linear-digest.py"])
    for fetched in ((nodes, nodes, None), ([], [], "HTTPError: HTTP Error 401: Unauthorized")):
        monkeypatch.setattr(mod, "fetch", lambda _since, f=fetched: f)
        mod.main()
    assert len(sent) == 2, sent
    return _texts(sent, phone_text)


def _texts(sent, phone_text):
    """What post_to receives for each captured deliver(message, detail) call."""
    texts = []
    for message, detail in sent:
        if detail:
            # Both shapes the child can hand post_to: the full list saved, and not.
            texts += [FN.with_detail(message, "row1", phone_text.APP_LINK),
                      FN.with_detail(message, None, phone_text.APP_LINK)]
        else:
            texts.append(message)
    return texts


#: A mail subject the way Gmail hands it over: other people's words, with a ticket id.
_TICKET_SUBJECT = "Re: ASK-4479 invoice question"


def _morning_brief(tmp_path, monkeypatch, phone_text):
    mod = _load("morning_brief_census", "morning-brief.py")
    now = dt.datetime(2026, 11, 11, 7, 0, tzinfo=dt.timezone.utc).astimezone()
    empty = {k: ([], None) for k in ("calendar", "mail", "owed", "overnight")}
    full = dict(empty, calendar=(["09:30 Call with Lee (Zoom)"], None),
                mail=(["Lee at Portant: SOW questions"], None))
    broken = dict(full, mail=([], "HTTPError: 401"))
    # Clean data only: the brief's OWN wording must pass as is. Other people's words
    # (a subject naming a ticket) are test_a_brief_naming_a_ticket_reaches_him_through_the_fallback.
    return [mod.build(now, s)[0] for s in (full, empty, broken)]


def _browser_health(tmp_path, monkeypatch, phone_text):
    mod = _load("browser_session_health_census", "browser_session_health.py")
    prof = {"name": "research", "identity": "assaf research", "dir": str(tmp_path)}
    surf = {"name": "linkedin", "url": "https://www.linkedin.com/feed/", "logged_in_marker": "Start a post"}
    return [mod._message(prof, surf, {"reason": "signed-in marker absent"}, "dead"),
            mod._message(prof, surf, {"at": "2026-11-11T09:00:00-08:00"}, "alive")]


#: A friction line naming a file, the way a real one does. The path sits inside the
#: 60-character excerpt, after a space: chief's code-path marker needs the space.
_FRICTION_PATH = ".q-system/scripts/morning-brief.py"


def _weekly_improve(tmp_path, monkeypatch, phone_text):
    """main() itself, with founder_notify swapped for a recorder, so the census reads
    exactly what weekly-improve hands deliver()."""
    mod = _load("weekly_improve_census", "weekly-improve.py")
    at = (dt.datetime.now().astimezone() - dt.timedelta(days=1)).isoformat(timespec="seconds")
    ledger = tmp_path / "friction.jsonl"
    ledger.write_text("".join(json.dumps(r) + "\n" for r in (
        {"id": "fr-2026-11-10-01", "at": at, "target": "rule",
         "text": "the brief lists Sana's tickets as mine, change the owner rule"},
        {"id": "fr-2026-11-10-03", "at": at, "target": "rule",
         "text": f"the owner rule in {_FRICTION_PATH} shows Sana's tickets as mine"},
        {"id": "fr-2026-11-10-02", "at": at, "target": "rule",
         "text": "sell the brief as a product to founders"})))
    sent, real = [], mod._load_sibling

    class _Recorder:
        @staticmethod
        def deliver(message, detail=None):
            sent.append((message, detail))
            return {"delivered": True}

    monkeypatch.setattr(mod, "_load_sibling",
                        lambda stem, filename: _Recorder if stem == "founder_notify" else real(stem, filename))
    for friction in (ledger, tmp_path / "absent.jsonl"):
        mod.main(["--friction", str(friction), "--inbox", str(tmp_path / "no-inbox")])
    assert len(sent) == 2, sent
    # Not vacuous: the path line was proposed, so its excerpt is in what went out.
    assert any(_FRICTION_PATH in (detail or message) for message, detail in sent), sent
    return _texts(sent, phone_text)


def _cap_ladder(tmp_path, monkeypatch, phone_text):
    mod = _load("cap_ladder_census", "cap-ladder.py")
    return _texts([(mod.founder_ask_message(n), "the asks") for n in (1, 2, 9)], phone_text)


CASES = {
    "daily-linear-digest.py": _digest,
    "morning-brief.py": _morning_brief,
    "browser_session_health.py": _browser_health,
    "weekly-improve.py": _weekly_improve,
    "cap-ladder.py": _cap_ladder,
}

#: Engineering signals (founder 2026-08-10: "should go to Sana - not me"). Each one
#: is a job or a checker reporting on itself, which the founder cannot fix.
ROUTED_TO_SANA = (
    "morning-brief-deadman.py",     # the brief job did not run or was not delivered
    "browser_session_deadman.py",   # the session checker itself stopped running
    "lessons-drift-report.py",      # file-path drift between the skeleton and a hub
)


def test_every_founder_notify_caller_has_a_census_case():
    callers = founder_callers()
    assert callers, "found no founder_notify caller at all: the discovery is broken, not the tree clean"
    missing = [c for c in callers if c not in CASES]
    assert not missing, (f"{missing} hand messages to founder_notify with no census case. Add its real "
                         "message to CASES, or route it to Sana and list it in ROUTED_TO_SANA")
    stale = [c for c in CASES if c not in callers]
    assert not stale, f"{stale} have a census case but no longer call founder_notify"


@pytest.mark.parametrize("caller", sorted(CASES))
def test_every_founder_message_passes_chiefs_phone_gate(caller, chief, tmp_path, monkeypatch):
    """Claim (a): each caller's own template on clean data passes chief DIRECTLY.
    Never through plan(): the fallback makes any text deliverable, so a census run
    through it cannot fail on the caller's own wording (PR #749 review round 2,
    major 1). A caller whose own words are engineering-shaped is red here."""
    texts = CASES[caller](tmp_path, monkeypatch, chief[1])
    assert texts, f"{caller}: the census built no message"
    refused = []
    for text in texts:
        ok, reasons, words = verdict(chief, text)
        if not ok:
            refused.append(f"{reasons} {words}\n  {text[:300]!r}")
    assert not refused, (f"{caller}: chief would refuse {len(refused)} of {len(texts)} message(s); "
                         "a refusal reaches nobody and becomes a Sana ticket:\n" + "\n".join(refused))


@pytest.mark.parametrize("caller", ROUTED_TO_SANA)
def test_an_engineering_caller_goes_to_sana_on_purpose(caller):
    code = _code(SCRIPTS / caller)
    assert "founder_notify" not in code, f"{caller} still hands its engineering signal to the founder path"
    assert "engineering_route" in code, f"{caller} does not reach Sana through engineering_route"
    assert caller not in CASES


def test_the_replica_refuses_what_chief_refuses(chief):
    """A gate check that cannot fail is not one. The digest's old first line with an
    id, a dash and a PR number is refused; a plain count line passes."""
    bad = "Closed today\n  ASK-4479 skeleton off Slack -- see PR #746"
    ok, reasons, _ = verdict(chief, bad)
    assert not ok and "engineering-on-whatsapp" in reasons, reasons
    long_bad = "\n".join([f"row {i} ASK-{i}" for i in range(30)])
    ok, reasons, _ = verdict(chief, long_bad)
    assert not ok and "engineering-on-whatsapp" in reasons, "the whole-text check before the app save"
    ok, reasons, _ = verdict(chief, "Linear today: 4 closed, 3 opened.")
    assert ok, reasons


def test_digest_blocked_wording_cannot_drift(tmp_path):
    """PR #749 review, minor: a 7th BLOCKED_PATTERNS entry with no BLOCKED_PLAIN
    wording crashed phone() with an IndexError inside the 4pm run, and no test saw
    it. It must fail at import instead, where any test that loads the file sees it."""
    src = (SCRIPTS / "daily-linear-digest.py").read_text()
    anchor = "BLOCKED_PATTERNS = (\n"
    assert src.count(anchor) == 1
    drifted = tmp_path / "daily_linear_digest_drifted.py"
    drifted.write_text(src.replace(anchor, anchor + '    re.compile(r"[0-9]+ issue[(]s[)] PARKED awaiting budget.*"),\n'))
    spec = importlib.util.spec_from_file_location("digest_drifted", drifted)
    with pytest.raises(RuntimeError, match="BLOCKED_PLAIN"):
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    _load("daily_linear_digest_aligned", "daily-linear-digest.py")  # the shipped tuples load


def test_a_brief_naming_a_ticket_reaches_him_through_the_fallback(chief):
    """PR #749 review, major 2: a mail subject carrying a Linear id made chief refuse
    the whole brief; it reached nobody and became a Sana ticket. Now the child sees the
    refusal first, saves the full brief to the app and sends one line that passes."""
    mod = _load("morning_brief_fallback", "morning-brief.py")
    now = dt.datetime(2026, 11, 11, 7, 0, tzinfo=dt.timezone.utc).astimezone()
    sources = {k: ([], None) for k in ("calendar", "mail", "owed", "overnight")}
    sources["mail"] = ([_TICKET_SUBJECT], None)
    message = mod.build(now, sources)[0]
    assert not verdict(chief, message)[0], "the fixture must be one chief refuses, or this proves nothing"
    # Control: the same brief with a clean subject passes as is, so the refusal comes
    # from the third-party subject and not from the brief's own wording.
    clean = mod.build(now, dict(sources, mail=(["Lee at Portant: SOW questions"], None)))[0]
    assert verdict(chief, clean)[0], "the brief's own wording is refused; that is claim (a), not a fallback"
    saved = []
    p = FN.plan(chief[0], chief[1], message, "Morning brief", save=lambda t: saved.append(t) or "row1")
    assert p["fallback"] and p["full_saved"] and saved == [message], p
    assert p["text"] == FN.fallback_line("Morning brief", "row1", chief[1].APP_LINK)
    assert verdict(chief, p["text"])[0], p["text"]
    assert '"Morning brief"' in _code(SCRIPTS / "morning-brief.py"), "morning-brief does not name its kind"
