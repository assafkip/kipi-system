"""Agent-facing adapter for the two read lanes. Stdlib only, on purpose.

## Why an adapter and not logic in server.py

`plugins/kipi-core/kipi-mcp` cannot be collected by pytest (ModuleNotFoundError:
No module named 'kipi_mcp'), which is why it is one of the deliberate exclusions
in `.verify-suites`. Anything living inside that package is untested by the
floor. So this module imports nothing from `kipi_mcp`, and its suite lives in
`q-system/.q-system/tests`, which IS a named suite. server.py stays a thin
registration layer over functions that are actually checked.

## Why the tools exist at all

`browser_session.py` and `reddit_read.py` both shipped with a CLI and no
agent-facing surface: no skill, no command, no MCP tool, no rule. The founder's
answer to "how do I tell Claude to use this" was to hand over a file path every
time, and a fresh session did not know either existed. That is the "text in a
file is NOT wired" bullet in wiring-check.md, missed on both.

## The load path, which this repo has already paid for twice

Plugins run from the marketplace clone (`~/.claude/plugins/marketplaces/kipi`),
never from a project's working tree, and an instance `plugins/` dir is a
`kipi update` destination that gets overwritten. The clone is a full checkout of
this repo, so `q-system/.q-system/scripts` sits beside `plugins/` inside it and
`KIPI_PLUGIN_ROOT` reaches it. `resolution_info()` reports WHICH candidate won,
so serving a stale or wrong copy is visible instead of silent.

## Read only

`fetch` and `probe` for the browser, `thread` and `listing` for Reddit. No write
path, and specifically no `login`: `open_for_manual_login` waits for a human to
close a window, so exposing it to an agent would hang the session forever.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

SCRIPT_NAMES = ("reddit_read.py", "browser_session.py")


class ScriptsNotFound(Exception):
    """No candidate directory held both lanes. A load-path failure, said loudly."""


class UnknownProfile(Exception):
    """A profile name that is not declared in browser_profiles.json."""


class CoverageMissing(Exception):
    """A thread artifact carrying comments without saying what fraction they are."""


def _candidates():
    env = os.environ.get("KIPI_SCRIPTS_DIR")
    if env:
        yield "env", Path(env)
    root = os.environ.get("KIPI_PLUGIN_ROOT")
    if root:
        # KIPI_PLUGIN_ROOT is <clone>/plugins/kipi-core
        yield "plugin_root", Path(root).resolve().parents[1] / "q-system/.q-system/scripts"
    # src/kipi_mcp -> src -> kipi-mcp -> kipi-core -> plugins -> repo root
    yield "module_relative", Path(__file__).resolve().parents[5] / "q-system/.q-system/scripts"


def resolution_info() -> dict:
    """Which directory the tools will run, and how it was found.

    Returned rather than logged because a wrong-copy bug is invisible by
    construction: the code you edited and the code that ran are both real files
    with the same name.
    """
    tried = []
    for source, directory in _candidates():
        tried.append(str(directory))
        if all((directory / name).exists() for name in SCRIPT_NAMES):
            return {"source": source, "scripts_dir": str(directory)}
    raise ScriptsNotFound(
        f"neither {SCRIPT_NAMES} found. Tried: {tried}. Plugins run from the "
        "marketplace clone, not a project working tree; if this fires, the clone "
        "is missing q-system or KIPI_PLUGIN_ROOT is not what it should be.")


def scripts_dir() -> Path:
    return Path(resolution_info()["scripts_dir"])


def load_script(filename: str):
    """Load one of the lane scripts by path.

    THE sys.modules REGISTRATION IS NOT OPTIONAL. browser_session defines a
    dataclass, and Python 3.14 resolves the owning module out of sys.modules to
    read its annotations; without the registration, constructing ProbeResult
    raises AttributeError. That exact defect shipped green on 2026-08-30 because
    every test injected its own prober and nothing exercised the loader.
    """
    name = filename[:-3]
    path = scripts_dir() / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def declared_profiles() -> dict:
    """name -> profile, straight out of browser_profiles.json."""
    health = load_script("browser_session_health.py")
    return {p["name"]: p for p in health.load_profiles()}


def _profile_or_refuse(name: str) -> dict:
    profiles = declared_profiles()
    if name not in profiles:
        raise UnknownProfile(
            f"no declared profile {name!r}. Declared: {sorted(profiles)}. "
            "This tool takes a profile NAME, never a directory: accepting a path "
            "would put the research-root refusal one argument away from being "
            "bypassed, and the founder's real Chrome profile is a path.")
    return profiles[name]


# ---------------------------------------------------------------------------
# Browser lane
# ---------------------------------------------------------------------------

def browser_fetch(profile: str, url: str, fetcher=None, timeout_ms: int = 45000) -> dict:
    """Load one URL in the headful research browser. Read only.

    `held` is an ANSWER, not an error. A Chrome persistent context allows one
    holder, so whenever the founder has a window open on this profile the fetch
    cannot happen. That is expected and transient and will occur constantly,
    because the human and the agent want the same profile. It returns a state.
    """
    profile_row = _profile_or_refuse(profile)
    session = load_script("browser_session.py")
    fetcher = fetcher or session.fetch_html
    html, error = fetcher(profile_row["dir"], url, timeout_ms=timeout_ms)

    if error:
        held = session.looks_held(error)
        return {
            "status": "held" if held else "error",
            "profile": profile, "url": url, "reason": error, "html": None,
            "next_step": ("Another Chrome is holding this profile, usually your own "
                          "sign-in window. Close it and retry; nothing here will "
                          "force the profile open.") if held else
                         "The browser could not start. This is environmental.",
        }
    return {"status": "ok", "profile": profile, "url": url,
            "bytes": len(html), "html": html}


def browser_probe(profile: str, prober=None) -> dict:
    """Liveness of every declared surface on one profile. Read only."""
    profile_row = _profile_or_refuse(profile)
    session = load_script("browser_session.py")

    def live(row, surface):
        return session.probe(row["name"], row["dir"], surface["url"],
                             surface["logged_in_marker"],
                             surface=surface["name"]).as_dict()

    prober = prober or live
    return {"profile": profile, "identity": profile_row["identity"],
            "surfaces": [prober(profile_row, s)
                         for s in profile_row["liveness_probes"]],
            "unmonitored_surfaces": profile_row.get("unmonitored_surfaces", [])}


# ---------------------------------------------------------------------------
# Reddit lane. Coverage is put where it cannot be skimmed past.
# ---------------------------------------------------------------------------

def summarize_thread(artifact: dict) -> dict:
    """The artifact with a one-line coverage banner as its FIRST key.

    A caller that receives 536 comments and no coverage number is back to silent
    truncation one layer up, which is the whole defect this lane was built
    around. `coverage_summary` leads the object so it is read before the
    comments, not after them.
    """
    if artifact.get("comments") is not None:
        missing = [k for k in ("declared", "fetched", "coverage_pct", "stubs",
                               "complete", "strategy") if k not in artifact]
        if missing:
            raise CoverageMissing(
                f"artifact carries comments but is missing {missing}; a comment "
                "list without its coverage reads as a whole thread.")

    if artifact.get("refused"):
        banner = (f"REFUSED: HTTP {artifact.get('http_status')}. Nothing was read. "
                  "This is a refusal, not an empty thread.")
    else:
        parts = [f"{artifact.get('fetched')} of {artifact.get('declared')} comments "
                 f"({artifact.get('coverage_pct')}%)",
                 f"{artifact.get('stubs')} unexpanded stubs",
                 f"strategy={artifact.get('strategy')}"]
        if artifact.get("truncated"):
            parts.append("TRUNCATED, this is not the whole thread")
        if artifact.get("anomaly"):
            parts.append(f"ANOMALY {artifact['anomaly']}")
        banner = ", ".join(parts)

    out = {"coverage_summary": banner}
    out.update(artifact)
    return out


def reddit_thread(permalink: str) -> dict:
    """One Reddit thread over plain HTTP, with its coverage banner."""
    reader = load_script("reddit_read.py")
    return summarize_thread(reader.read_thread(permalink, pacer=reader.Pacer()))


def reddit_listing(subreddit: str, period: str = "month") -> dict:
    """Candidate threads and the size Reddit declares for each."""
    reader = load_script("reddit_read.py")
    return reader.read_listing(subreddit, period=period, pacer=reader.Pacer())
