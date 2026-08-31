#!/usr/bin/env python3
"""The six hard constraints of the persistent-browsing capability, as checks.

Every test here was written and watched FAIL before the modules existed, and
each constraint check was then mutation-tested by restoring the violation it
forbids. A constraint check that has never been red is decoration.

WHY THE CHECKS ARE STRUCTURAL AND NOT NAME GREPS. A grep over source text
answers a question about prose as easily as about code: a docstring that
explains "we never pass headless=True" trips the same grep as the line that
passes it. So the source checks below run over `_code_only()` -- the module
re-rendered from its AST with comments and docstrings removed -- which is the
executable half and nothing else. String literals SURVIVE that stripping on
purpose, because `args=["--headless"]` is executable and a comment about it is
not.

WHY NO TEST HERE OPENS A BROWSER. `browser_session` imports playwright lazily
(the convention both existing drivers use), so this suite exercises the pure
half: path refusal, result shape, transition arithmetic. The browser half is
proven by the live two-arm smoke against NodeSeek, which is a measurement, not
a unit test. The fable-discipline lint forbids a test touching a live data
path, and a headful probe of a real surface is exactly that.
"""
from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
SESSION_PY = SCRIPTS / "browser_session.py"
HEALTH_PY = SCRIPTS / "browser_session_health.py"
DEADMAN_PY = SCRIPTS / "browser_session_deadman.py"
PROFILES_JSON = SCRIPTS / "browser_profiles.json"
HEALTH_PLIST = SCRIPTS / "com.kipi.browser-session-health.plist"
DEADMAN_PLIST = SCRIPTS / "com.kipi.browser-session-deadman.plist"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def session():
    return _load(SESSION_PY, "browser_session")


@pytest.fixture(scope="module")
def health():
    return _load(HEALTH_PY, "browser_session_health")


@pytest.fixture(scope="module")
def deadman():
    return _load(DEADMAN_PY, "browser_session_deadman")


def _code_only(path: Path) -> str:
    """The module's executable text: AST round-trip, docstrings dropped.

    Comments vanish because ast.unparse never emits them. Docstrings are popped
    explicitly. Ordinary string literals stay, so a `"--headless"` argument is
    still visible to the checks below while a paragraph explaining why we do not
    pass one is not.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if isinstance(node, holders) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                node.body.pop(0)
                if not node.body:
                    node.body.append(ast.Pass())
    return ast.unparse(tree)


# ---------------------------------------------------------------------------
# CONSTRAINT 1 -- headful only
# ---------------------------------------------------------------------------

def test_c1_browser_module_never_asks_for_headless():
    """NodeSeek 403s headless Chrome and loads in a real one (measured
    2026-08-27, harvest_discussions.py). Headless is not a performance knob
    here; it is the thing that fails."""
    code = _code_only(SESSION_PY)
    assert "headless=True" not in code, "browser_session.py asks for headless"
    assert "--headless" not in code, "browser_session.py passes a --headless flag"


def test_c1_browser_module_positively_asks_for_headful():
    """The absence check above passes on a module that launches no browser at
    all. This is its other half: the launch exists and is explicitly headful."""
    code = _code_only(SESSION_PY)
    assert "headless=False" in code, "no explicit headful launch in browser_session.py"


# ---------------------------------------------------------------------------
# CONSTRAINT 2 -- never the founder's real Chrome profile
# ---------------------------------------------------------------------------

def test_c2_refuses_a_path_outside_the_research_root(session, tmp_path):
    with pytest.raises(session.ProfileRefused):
        session.resolve_profile_dir(tmp_path / "somewhere-else",
                                    research_root=tmp_path / "root")


def test_c2_accepts_a_path_inside_the_research_root(tmp_path, session):
    root = tmp_path / "root"
    target = root / "research-hn"
    target.mkdir(parents=True)
    assert session.resolve_profile_dir(target, research_root=root) == target.resolve()


def test_c2_refuses_real_chrome_even_when_the_root_would_allow_it(session):
    """The load-bearing arm. With the research root widened to $HOME, the
    root check cannot refuse the real Chrome profile -- only the explicit
    refusal can. Testing this under the narrow root would pass on a module
    with no Chrome branch at all, which is the mutant this catches."""
    with pytest.raises(session.ProfileRefused) as exc:
        session.resolve_profile_dir(
            Path.home() / "Library/Application Support/Google/Chrome",
            research_root=Path.home())
    assert "chrome" in str(exc.value).lower()


def test_c2_refuses_a_profile_inside_real_chrome(session):
    """`.../Chrome/Default` is the directory a real session actually lives in.
    An exact-match-only refusal would wave it through."""
    with pytest.raises(session.ProfileRefused):
        session.resolve_profile_dir(
            Path.home() / "Library/Application Support/Google/Chrome/Default",
            research_root=Path.home())


def test_c2_refuses_a_symlink_that_escapes_the_root(tmp_path, session):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "sneaky"
    link.symlink_to(outside)
    with pytest.raises(session.ProfileRefused):
        session.resolve_profile_dir(link, research_root=root)


# ---------------------------------------------------------------------------
# CONSTRAINT 3 -- read-only in v1
# ---------------------------------------------------------------------------

WRITE_VERBS = ("post", "comment", "message", "submit", "reply", "publish",
               "upvote", "downvote", "vote", "send", "dm", "follow", "subscribe")


def test_c3_no_public_write_verb_in_the_module_surface():
    tree = ast.parse(SESSION_PY.read_text(encoding="utf-8"))
    names = [n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and not n.name.startswith("_")]
    offenders = [n for n in names
                 for v in WRITE_VERBS if v in n.lower().replace("-", "_").split("_")]
    assert not offenders, f"write verbs in the public surface: {offenders}"


def test_c3_no_playwright_write_api_is_called():
    """The naming check above is defeated by a write method with an innocent
    name. This is the capability check: the module never calls a Playwright
    API that changes the page."""
    code = _code_only(SESSION_PY)
    forbidden = (".fill(", ".click(", ".dblclick(", ".tap(", ".type(",
                 ".press(", ".set_input_files(", ".select_option(",
                 ".check(", ".uncheck(", "insert_text", ".set_checked(")
    hits = [f for f in forbidden if f in code]
    assert not hits, f"page-mutating Playwright calls present: {hits}"


# ---------------------------------------------------------------------------
# CONSTRAINT 5 -- empty and broken stay distinguishable
# (checked before 4 because 4 reuses the shapes it pins)
# ---------------------------------------------------------------------------

def test_c5_a_load_failure_and_a_logged_out_page_are_different_results(session):
    """Both results come out of probe() itself. An earlier version of this test
    built the two ProbeResult values by hand and passed against a probe() that
    reported a navigation timeout as `logged_in=False` -- mutant M5b survived it
    on 2026-08-30. A fixture I invent tests my assumption, not the producer."""
    def broken_fetch(profile_dir, url, timeout_ms=None):
        return None, "TimeoutError: navigation timed out"

    def logged_out_fetch(profile_dir, url, timeout_ms=None):
        return "<html><body>" + "x" * 48000 + "<a href=/signin>sign in</a></body></html>", None

    # The injected fetcher never touches the path, so no profile dir is needed.
    broken = session.probe("p", "unused", "u", "logout", fetcher=broken_fetch)
    empty = session.probe("p", "unused", "u", "logout", fetcher=logged_out_fetch)

    assert broken.as_dict() != empty.as_dict()
    # The three axes that must not collapse into one another.
    assert broken.reachable is False and empty.reachable is True
    assert broken.logged_in is None and empty.logged_in is False
    assert broken.error and empty.error is None
    # And a legitimately-empty result still carries WHY it was empty.
    assert empty.reason


def test_c5_health_classifies_the_two_into_different_states(health):
    assert health.classify({"reachable": True, "logged_in": False}) == "dead"
    assert health.classify({"reachable": True, "logged_in": True}) == "alive"
    assert health.classify({"reachable": False, "logged_in": None}) == "unknown"


# ---------------------------------------------------------------------------
# CONSTRAINT 4 -- a dead session is REPORTED, never re-authenticated
# ---------------------------------------------------------------------------





def _recorder():
    sends = []

    def sender(message):
        sends.append(message)
        return {"delivered": True, "transport": "recorder"}

    sender.sends = sends
    return sender






def test_c4_health_never_calls_a_re_authentication_path():
    """Re-authenticating a profile the far side has already flagged is the
    documented 2026-07-20 failure. The manual-sign-in entry point exists for a
    human at a keyboard; nothing on the automated path may invoke it.

    This is a check on CALLS, not on text. A text grep for "login" is wrong
    twice over: it trips on the repair instruction inside the alert message,
    which is prose the founder needs, and it would still miss a re-auth helper
    named anything else.
    """
    tree = ast.parse(HEALTH_PY.read_text(encoding="utf-8"))
    called = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called.append(func.attr if isinstance(func, ast.Attribute)
                          else getattr(func, "id", ""))
    assert not [c for c in called if "login" in c.lower()], called
    assert "open_for_manual_login" not in _code_only(HEALTH_PY)


def test_c4_health_uses_exactly_one_thing_from_the_browser_module():
    """`probe` and nothing else. This is what keeps the read-only surface from
    being widened by a caller rather than by an edit to browser_session.py."""
    tree = ast.parse(HEALTH_PY.read_text(encoding="utf-8"))
    used = {n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == "session"}
    assert used == {"probe"}, f"health reaches into browser_session for {used}"


# ---------------------------------------------------------------------------
# CONSTRAINT 6 and the run_once behaviour tests live in
# test_browser_session_states.py, which owns the per-surface shape.
# ---------------------------------------------------------------------------















def test_health_can_actually_load_the_browser_module(health):
    """The LIVE path, which no injected prober ever touches.

    Measured 2026-08-30, after 34 green tests and 21 killed mutants: _module()
    built browser_session without registering it in sys.modules, and Python
    3.14's @dataclass then raised AttributeError on ProbeResult. The job died
    on import on every run and the suite could not see it, because every test
    injects its own prober. A green unit test never proves the helper is called.

    IT MUST RUN IN A CLEAN INTERPRETER. First attempt at this test called
    health._module() in-process and stayed GREEN with the fix removed, because
    the `session` fixture had already registered browser_session in sys.modules
    under the same name -- so the dataclass found what a sibling test put there,
    not what the loader did. A subprocess is the only place this loader is
    observed doing its own work, and it is also what launchd actually runs.
    """
    code = (
        "import importlib.util, sys;"
        f"spec = importlib.util.spec_from_file_location('h', r'{HEALTH_PY}');"
        "m = importlib.util.module_from_spec(spec); sys.modules['h'] = m;"
        "spec.loader.exec_module(m);"
        "bs = m._module('browser_session.py');"
        "r = bs.ProbeResult(profile='p', url='u', reachable=True, logged_in=True,"
        " error=None, reason=None, content_len=1, at='t');"
        "print(sorted(r.as_dict()))"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-1200:]
    assert "logged_in" in done.stdout


def test_health_can_actually_load_the_founder_sender(health):
    mod = health._module("slack_founder.py")
    assert callable(mod.deliver)


# ---------------------------------------------------------------------------
# The declared profile set
# ---------------------------------------------------------------------------





def test_shipped_profile_dirs_all_resolve_under_the_research_root(health, session):
    for p in health.load_profiles(PROFILES_JSON):
        d = Path(os.path.expanduser(p["dir"]))
        d.mkdir(parents=True, exist_ok=True)
        session.resolve_profile_dir(d)  # raises ProfileRefused if outside




# ---------------------------------------------------------------------------
# Deadman -- same transition rule, off the health job
# ---------------------------------------------------------------------------

def test_deadman_is_silent_on_a_fresh_receipt(tmp_path, deadman):
    now = dt.datetime(2026, 8, 30, 12, 0)
    receipt = tmp_path / "r.json"
    receipt.write_text(json.dumps({"at": (now - dt.timedelta(minutes=10)).isoformat()}))
    ok, reason = deadman.check(now, receipt_path=receipt)
    assert ok, reason


def test_deadman_alarms_on_a_missing_receipt(tmp_path, deadman):
    ok, reason = deadman.check(dt.datetime(2026, 8, 30, 12, 0),
                               receipt_path=tmp_path / "nope.json")
    assert not ok and "receipt" in reason


def test_deadman_alarms_once_on_a_stale_receipt_then_stays_quiet(tmp_path, deadman):
    now = dt.datetime(2026, 8, 30, 12, 0)
    receipt = tmp_path / "r.json"
    state = tmp_path / "state.json"
    receipt.write_text(json.dumps({"at": (now - dt.timedelta(hours=6)).isoformat()}))

    first = _recorder()
    rc = deadman.run(now, receipt_path=receipt, state_path=state, sender=first)
    assert rc == 1 and len(first.sends) == 1, first.sends

    second = _recorder()
    deadman.run(now + dt.timedelta(minutes=30), receipt_path=receipt,
                state_path=state, sender=second)
    assert second.sends == [], "the deadman alarmed twice for one outage"

    # Receipt restored -> recovery line, then silence.
    receipt.write_text(json.dumps({"at": (now + dt.timedelta(hours=1)).isoformat()}))
    back = _recorder()
    deadman.run(now + dt.timedelta(hours=1, minutes=1), receipt_path=receipt,
                state_path=state, sender=back)
    assert len(back.sends) == 1, back.sends


# ---------------------------------------------------------------------------
# Wiring: the plists, and the interpreter trap
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("plist,script", [
    (HEALTH_PLIST, "browser_session_health.py"),
    (DEADMAN_PLIST, "browser_session_deadman.py"),
])
def test_plist_template_carries_the_three_placeholders(plist, script):
    text = plist.read_text(encoding="utf-8")
    for token in ("__KIPI_REPO__", "__HOME__", "__USER__"):
        assert token in text, f"{plist.name} is missing {token}"
    assert script in text


def test_health_plist_uses_an_interpreter_that_actually_has_playwright():
    """The trap this pins, measured 2026-08-30 on this Mac:

        /usr/bin/python3            ModuleNotFoundError: No module named 'playwright'
        /opt/homebrew/bin/python3   3.14.6, playwright imports

    Every other com.kipi.* plist in this directory runs /usr/bin/python3, which
    is correct for a job that reads JSON. Copying that line into the ONE job
    here that drives a browser ships something launchd loads happily and that
    dies on import, forever, visible only in a log nobody reads.
    """
    data = plistlib.loads(HEALTH_PLIST.read_bytes())
    interp = data["ProgramArguments"][0]

    # MACHINE-INDEPENDENT, so it runs everywhere including CI: the plist must not
    # name the system python. This is a property of the committed file.
    assert interp != "/usr/bin/python3", "this job needs playwright; /usr/bin/python3 has none"

    # HOST-SPECIFIC, so it can only be answered where the job actually runs.
    # These plists are launchd files for the founder's Mac; a Linux CI runner has
    # no /opt/homebrew and cannot tell us anything about whether that interpreter
    # imports playwright. Asserting the path exists was a claim about the machine
    # running the TEST rather than about the plist, and it turned CI red on a
    # correct file (measured 2026-08-31, run 33415635699).
    #
    # It SKIPS rather than passing: "we could not check" must not render as "we
    # checked and it was fine", which is the same rule the health prober's
    # unknown state exists for.
    if not Path(interp).exists():
        pytest.skip(f"{interp} is not on this host, so whether it imports "
                    "playwright is unanswerable here. This is a macOS launchd "
                    "plist; the check is real on the Mac that runs the job.")
    rc = subprocess.run([interp, "-c", "import playwright"],
                        capture_output=True).returncode
    assert rc == 0, f"{interp} cannot import playwright"


def test_deadman_plist_interpreter_can_actually_run_the_deadman():
    """The deadman reads one JSON receipt and never opens a browser, so it runs
    on the system python on purpose. That is only correct while the module
    imports there -- this executes it rather than asserting the intention."""
    data = plistlib.loads(DEADMAN_PLIST.read_bytes())
    interp = data["ProgramArguments"][0]
    assert Path(interp).exists(), f"{interp} does not exist on this machine"
    done = subprocess.run([interp, str(DEADMAN_PY), "--dry-run"],
                          capture_output=True, text=True)
    assert "Traceback" not in done.stderr, done.stderr[-800:]


def test_health_plist_probes_every_thirty_minutes():
    """30 minutes is a constraint, not a default. The probe opens a real Chrome
    against the surface it is trying to stay logged into; a five-minute probe
    IS the bot-like pattern that gets a session flagged, so the check would
    break the thing it checks."""
    data = plistlib.loads(HEALTH_PLIST.read_bytes())
    assert data["StartInterval"] == 1800
    assert data["RunAtLoad"] is True


def test_capability_fragment_declares_this_test_file():
    frag = (HERE.parent / "capability" / "expected_tests"
            / "q-system__.q-system__tests__test_browser_session.py.json")
    assert frag.exists(), f"no capability fragment at {frag}"
    data = json.loads(frag.read_text())
    assert data["path"] == "q-system/.q-system/tests/test_browser_session.py"
    # pytest, not python3: these files have no __main__ block, so a python3
    # runner binds the test functions and exits 0 having run none of them.
    # The capability gate calls that a "zero-execution test" and it is right.
    assert data["runner"] == "pytest"
