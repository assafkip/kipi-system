#!/usr/bin/env python3
"""The agent-facing surface for the two read lanes.

WHY THIS EXISTS. `browser_session.py` and `reddit_read.py` both shipped with a
CLI and nothing else: no skill, no command, no MCP tool, no rule. The only
references to either were their own health job and their capability fragments.
So the founder's answer to "how do I tell Claude to use this" was to hand over a
file path every time, and a fresh session did not know they existed. That is
precisely the "text in a file is NOT wired" bullet in wiring-check.md.

The adapter under test is deliberately dependency-free (stdlib only, no
`kipi_mcp` imports) for one reason: `plugins/kipi-core/kipi-mcp` cannot be
collected by pytest (ModuleNotFoundError: No module named 'kipi_mcp'), which is
why it is one of the excluded suites in .verify-suites. A tool whose logic lived
inside that package would be untestable by the floor. This file lives in
q-system/.q-system/tests, which IS a named suite, and loads the adapter by path.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
ADAPTER = REPO / "plugins/kipi-core/kipi-mcp/src/kipi_mcp/web_read.py"
SERVER = REPO / "plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py"
SCRIPTS = REPO / "q-system/.q-system/scripts"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def wr():
    return _load(ADAPTER, "web_read")


# ---------------------------------------------------------------------------
# Load path. The scar this repo already paid for twice.
# ---------------------------------------------------------------------------

def test_scripts_dir_resolves_to_a_directory_holding_both_lanes(wr):
    d = wr.scripts_dir()
    assert (d / "reddit_read.py").exists(), d
    assert (d / "browser_session.py").exists(), d


def test_scripts_dir_reports_which_resolution_won(wr):
    """Plugins run from the marketplace clone, not the repo working tree. When
    a path resolves, the adapter says HOW, so a wrong copy is visible rather
    than silently serving stale code."""
    info = wr.resolution_info()
    assert info["source"] in ("env", "plugin_root", "module_relative")
    assert Path(info["scripts_dir"]).is_dir()


def test_an_explicit_env_override_wins(wr, tmp_path, monkeypatch):
    (tmp_path / "reddit_read.py").write_text("")
    (tmp_path / "browser_session.py").write_text("")
    monkeypatch.setenv("KIPI_SCRIPTS_DIR", str(tmp_path))
    assert wr.scripts_dir() == tmp_path
    assert wr.resolution_info()["source"] == "env"


def test_load_script_works_in_a_clean_interpreter(wr):
    """browser_session defines a dataclass, and Python 3.14 resolves the owning
    module out of sys.modules to read its annotations. A loader that skips the
    registration raises AttributeError on ProbeResult. That exact defect shipped
    green on 2026-08-30 because every test injected its own prober.

    It must run in a SUBPROCESS: in-process, a sibling fixture has already put
    browser_session in sys.modules and the bug hides.
    """
    code = (
        "import importlib.util, sys;"
        f"spec = importlib.util.spec_from_file_location('w', r'{ADAPTER}');"
        "m = importlib.util.module_from_spec(spec); sys.modules['w'] = m;"
        "spec.loader.exec_module(m);"
        "s = m.load_script('browser_session.py');"
        "print(s.ProbeResult(profile='p', url='u', reachable=True, logged_in=True,"
        " error=None, reason=None, content_len=1, at='t').as_dict()['logged_in'])"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-1200:]
    assert "True" in done.stdout


# ---------------------------------------------------------------------------
# `held` is a first-class ANSWER, not an exception
# ---------------------------------------------------------------------------

HELD_ERROR = ("BrowserEnvError: browser launch failed for /x: "
              "BrowserType.launch_persistent_context: Opening in existing browser "
              "session. This usually means that the profile is already in use by "
              "another instance of Chromium.")


def test_a_held_profile_returns_a_held_status_not_an_exception(wr):
    """Chrome allows one holder per profile. If the founder has a window open,
    the agent cannot fetch, and that will happen constantly because the human
    and the agent want the same profile. It is an answer, not a crash."""
    out = wr.browser_fetch("research-hn", "https://example.invalid/",
                           fetcher=lambda d, u, timeout_ms=None: (None, HELD_ERROR))
    assert out["status"] == "held"
    assert "already in use" in out["reason"].lower()
    assert out.get("html") is None


def test_an_ordinary_launch_failure_is_an_error_not_held(wr):
    """If every failure read as `held`, a genuinely broken Chrome would look
    like the founder having a tab open, forever."""
    out = wr.browser_fetch("research-hn", "https://example.invalid/",
                           fetcher=lambda d, u, timeout_ms=None:
                           (None, "BrowserEnvError: Executable doesn't exist at /nope"))
    assert out["status"] == "error"


def test_a_successful_fetch_reports_ok_with_the_byte_count(wr):
    out = wr.browser_fetch("research-hn", "https://example.invalid/",
                           fetcher=lambda d, u, timeout_ms=None: ("<html>hi</html>", None))
    assert out["status"] == "ok" and out["bytes"] == 15


# ---------------------------------------------------------------------------
# Isolation survives the new surface
# ---------------------------------------------------------------------------

def test_the_tool_takes_a_DECLARED_PROFILE_NAME_never_a_path(wr):
    """Constraint 2 of the approved plan. If the agent surface accepted a
    directory, the whole research-root refusal would be one argument away from
    being bypassed, and the founder's real Chrome profile is a path."""
    with pytest.raises(wr.UnknownProfile):
        wr.browser_fetch("~/Library/Application Support/Google/Chrome",
                         "https://example.invalid/",
                         fetcher=lambda d, u, timeout_ms=None: ("x", None))


def test_an_undeclared_profile_name_is_refused(wr):
    with pytest.raises(wr.UnknownProfile):
        wr.browser_fetch("not-a-declared-profile", "https://example.invalid/",
                         fetcher=lambda d, u, timeout_ms=None: ("x", None))


def test_the_error_names_the_profiles_that_do_exist(wr):
    with pytest.raises(wr.UnknownProfile) as exc:
        wr.browser_fetch("nope", "https://x/", fetcher=lambda d, u, timeout_ms=None: ("x", None))
    assert "research-hn" in str(exc.value)


# ---------------------------------------------------------------------------
# Read-only, everywhere, including the new surface
# ---------------------------------------------------------------------------

WRITE_PREFIXES = ("post", "submit", "send", "reply", "vote", "upvote", "downvote",
                  "message", "dm", "delete", "edit", "subscribe", "follow",
                  "create", "publish", "update", "remove", "save", "write")


def test_no_write_verb_leads_a_public_adapter_function():
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    names = [n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and not n.name.startswith("_")]
    bad = [n for n in names if n.lower().split("_")[0] in WRITE_PREFIXES]
    assert not bad, f"write verbs lead these adapter names: {bad}"


def _code_only(path: Path) -> str:
    """The module's executable text: AST round-trip with docstrings dropped.

    A raw grep here fails on the adapter's own docstring, which NAMES
    open_for_manual_login in order to explain why it is not exposed. Prose about
    a refusal is not the refusal being violated, and a check that cannot tell
    those apart is one that gets deleted.
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


def test_the_adapter_never_exposes_login():
    """`open_for_manual_login` waits for a HUMAN to close a window. Exposed to
    an agent it would hang the session forever, and it is a write path onto a
    session besides."""
    assert "open_for_manual_login" not in _code_only(ADAPTER)
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    called = [n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert not [c for c in called if "login" in c.lower()], called


def test_the_server_registers_no_login_or_write_tool():
    """The registration itself, not just the adapter. A tool is only read-only
    if the thing wired into the session is."""
    src = SERVER.read_text(encoding="utf-8")
    for banned in ("kipi_browser_login", "kipi_reddit_post", "kipi_reddit_submit",
                   "kipi_browser_click", "kipi_browser_fill"):
        assert banned not in src, f"server registers a write tool: {banned}"


# ---------------------------------------------------------------------------
# Coverage must be impossible to ignore, one layer up
# ---------------------------------------------------------------------------

def test_reddit_thread_puts_coverage_in_a_human_readable_banner(wr):
    art = {"declared": 1190, "fetched": 536, "coverage_pct": 45.0, "stubs": 74,
           "complete": False, "truncated": True, "strategy": "large_partial",
           "anomaly": None, "refused": False, "comments": [{"id": "t1_a"}]}
    out = wr.summarize_thread(art)
    assert "45.0%" in out["coverage_summary"]
    assert "536" in out["coverage_summary"] and "1190" in out["coverage_summary"]
    assert "TRUNCATED" in out["coverage_summary"].upper()


def test_a_complete_thread_says_so_in_the_banner(wr):
    art = {"declared": 8, "fetched": 8, "coverage_pct": 100.0, "stubs": 0,
           "complete": True, "truncated": False, "strategy": "single",
           "anomaly": None, "refused": False, "comments": []}
    out = wr.summarize_thread(art)
    assert "TRUNCATED" not in out["coverage_summary"].upper()


def test_the_banner_is_the_FIRST_key_so_it_cannot_be_skimmed_past(wr):
    art = {"declared": 10, "fetched": 5, "coverage_pct": 50.0, "stubs": 1,
           "complete": False, "truncated": True, "strategy": "single",
           "anomaly": None, "refused": False, "comments": []}
    out = wr.summarize_thread(art)
    assert list(out.keys())[0] == "coverage_summary"


def test_a_refusal_banner_does_not_claim_zero_comments(wr):
    art = {"refused": True, "http_status": 429, "declared": None, "fetched": None,
           "coverage_pct": None, "stubs": None, "complete": False,
           "truncated": None, "strategy": None, "anomaly": None, "comments": None}
    out = wr.summarize_thread(art)
    assert "REFUSED" in out["coverage_summary"].upper()
    assert "429" in out["coverage_summary"]
    assert "0 of" not in out["coverage_summary"]


def test_an_anomaly_reaches_the_banner(wr):
    art = {"declared": 2, "fetched": 0, "coverage_pct": 0.0, "stubs": 0,
           "complete": False, "truncated": True, "strategy": "single",
           "anomaly": "declared_nonzero_but_none_parsed", "refused": False,
           "comments": []}
    out = wr.summarize_thread(art)
    assert "declared_nonzero_but_none_parsed" in out["coverage_summary"]


def test_summarize_refuses_an_artifact_with_comments_but_no_coverage(wr):
    with pytest.raises(wr.CoverageMissing):
        wr.summarize_thread({"comments": [{"id": "t1_a"}], "refused": False})


# ---------------------------------------------------------------------------
# The tool DESCRIPTION is load-bearing: it steers away from an expensive default
# ---------------------------------------------------------------------------

def _tool_docstrings():
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith(
                ("kipi_browser_", "kipi_reddit_")):
            out[node.name] = ast.get_docstring(node) or ""
    return out


def test_the_four_read_tools_are_registered():
    names = set(_tool_docstrings())
    assert names == {"kipi_browser_fetch", "kipi_browser_probe",
                     "kipi_reddit_thread", "kipi_reddit_listing"}, names


def test_the_browser_tool_steers_away_from_reddit_and_names_the_cheap_path():
    """Measured 2026-08-31: Reddit needs only an HTTP client with an honest UA.
    A browser description that does not say so makes Chrome the default and
    burns a launch on work curl does, every time."""
    doc = _tool_docstrings()["kipi_browser_fetch"]
    low = " ".join(doc.lower().split())
    # The IMPERATIVE, not a mention. Mutation 2026-08-31 (DESC-loses-reddit-steer)
    # deleted the "do not use" line and this test stayed green, because the word
    # "reddit" survived in the surrounding prose. A description that mentions
    # Reddit approvingly would have passed the old assertion.
    assert "do not use this for reddit" in low, \
        "the browser tool must carry an explicit do-not, not just mention Reddit"
    assert "kipi_reddit_thread" in doc, "it must name the cheaper tool by name"


def test_the_browser_tool_states_the_narrow_category_it_is_for():
    doc = _tool_docstrings()["kipi_browser_fetch"].lower()
    assert "nodeseek" in doc, "the one proven member of the category"
    assert "403" in doc or "defeat" in doc


def test_the_browser_tool_documents_the_held_answer():
    doc = _tool_docstrings()["kipi_browser_fetch"].lower()
    assert "held" in doc


def test_the_reddit_tool_tells_the_caller_to_report_coverage():
    doc = " ".join(_tool_docstrings()["kipi_reddit_thread"].lower().split())
    # Same lesson: "coverage" and "truncat" both survive incidentally in
    # `coverage_summary` and `truncated`, so the old assertion passed against a
    # docstring with the instruction removed (DESC-loses-coverage-instruction).
    assert "always report the coverage" in doc
    assert "silent truncation" in doc


def test_the_capability_fragment_declares_this_suite():
    frag = (HERE.parent / "capability" / "expected_tests"
            / "q-system__.q-system__tests__test_web_read_tools.py.json")
    assert frag.exists(), f"no capability fragment at {frag}"
    assert json.loads(frag.read_text())["path"].endswith("tests/test_web_read_tools.py")


# ---------------------------------------------------------------------------
# Codex review of PR #293 (MINOR): the tool promised a state and returned none.
# ---------------------------------------------------------------------------

def test_browser_probe_reports_a_state_per_surface(wr, monkeypatch):
    """The tool description tells the caller it reports `unverified` for a
    marker never seen true. The response carried no `state` key at all, so the
    promise was prose. It now classifies through the health module rather than
    re-implementing, so it cannot drift from the scheduled job."""
    row = {"name": "p", "identity": "i", "unmonitored_surfaces": [],
           "liveness_probes": [{"name": "s", "url": "https://x", "logged_in_marker": "m"}]}
    monkeypatch.setattr(wr, "_profile_or_refuse", lambda name: row)
    out = wr.browser_probe("p", prober=lambda p, s: {"reachable": True,
                                                     "logged_in": False, "held": False})
    surface = out["surfaces"][0]
    assert surface["state"] is not None, "the promised state is missing"
    assert surface["state"] == "unverified", \
        "a marker never seen true must not read as a dead session"
    assert surface["marker_ever_seen"] is False


def test_browser_probe_reports_held_rather_than_a_dead_session(wr, monkeypatch):
    row = {"name": "p", "identity": "i", "unmonitored_surfaces": [],
           "liveness_probes": [{"name": "s", "url": "https://x", "logged_in_marker": "m"}]}
    monkeypatch.setattr(wr, "_profile_or_refuse", lambda name: row)
    out = wr.browser_probe("p", prober=lambda p, s: {"reachable": False,
                                                     "logged_in": None, "held": True})
    assert out["surfaces"][0]["state"] == "held"


# ---------------------------------------------------------------------------
# Codex round 2, MINOR: held was documented and raised instead.
# ---------------------------------------------------------------------------

def test_a_launch_failure_that_RAISES_still_returns_held(wr):
    """fetch_html lets a LAUNCH failure propagate as BrowserEnvError; only
    page-level failures come back as an error string. So the documented `held`
    status never happened on the real path, and the earlier test missed it by
    injecting a fetcher that returned (None, error) instead of raising, which is
    not what the producer does."""
    class BrowserEnvError(Exception):
        pass

    def raising(profile_dir, url, timeout_ms=None):
        raise BrowserEnvError(
            "browser launch failed for /x: Opening in existing browser session. "
            "This usually means that the profile is already in use by another "
            "instance of Chromium.")

    out = wr.browser_fetch("research-hn", "https://example.invalid/", fetcher=raising)
    assert out["status"] == "held", out
    assert "already in use" in out["reason"].lower()


def test_a_raising_launch_failure_that_is_not_held_is_an_error(wr):
    def raising(profile_dir, url, timeout_ms=None):
        raise RuntimeError("Executable doesn't exist at /nope")
    out = wr.browser_fetch("research-hn", "https://example.invalid/", fetcher=raising)
    assert out["status"] == "error"
