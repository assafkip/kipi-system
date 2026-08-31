#!/usr/bin/env python3
"""The ONLY file in this repo that opens a browser for a research profile.

Same convention as the two drivers this is modelled on
(`cole-gtm/gtm/scripts/reddit_worker/reddit_driver.py` and
`substack_worker/substack_driver.py`): one file touches Chrome, everything
testable lives outside it, and it is exercised by a live smoke rather than by
unit tests. Per-action launch, close when done.

It knows nothing about any target. It takes a profile directory and a URL.

## Why headful, and why that is not a preference

Measured, not assumed:

  reddit_driver.py, canon 2026-07-17   a Playwright profile login for Reddit is
                                       WAF-blocked and FORBIDDEN. That lane goes
                                       through the Chrome extension and this
                                       module must never be pointed at it.
  Alice/harvest_discussions.py,        NodeSeek 403s a plain GET AND headless
  measured 2026-08-27                  Chrome, and loads fully in a real browser
                                       with no login at all.

So the browser being real is the capability. A headless launch here does not
run slightly worse, it returns 403 on the surfaces this exists for. The
constraint is pinned by two checks in tests/test_browser_session.py: one that
no headless request appears in this file's executable text, and one that the
headful launch positively exists (the absence check alone passes on a module
that launches nothing).

## Why the window is thrown off-screen

Headful means a real window, and this runs every 30 minutes on the founder's
primary Mac. Ninety-six windows a day stealing focus is how a job gets killed
in a week. `--window-position` puts it far off the visible desktop: still a
real rendering browser with a real fingerprint, just not in his face. The
NodeSeek two-arm smoke was run WITH these args, so the off-screen placement is
measured not to cost the thing headful buys.

## Why there is no write path

Read-only in v1, and enforced structurally rather than by intent: no public
method carries a write verb, and this file calls no page-mutating Playwright
API at all. Both are checked. `open_for_manual_login` opens a window and waits
for a HUMAN to type in it; this module never fills a field itself.

CLI:
    browser_session.py login <profile-name>    # one-time, human at the keyboard
    browser_session.py probe <profile-name>    # print one liveness result
    browser_session.py fetch <profile-name> <url>
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The declared research root. Every profile this module will open must resolve
# inside it. Kept separate from ~/.config/kipi itself so that the three existing
# worker profiles (reddit-, substack-, linkedin-profile) are OUTSIDE it: reddit
# in particular is a forbidden surface for Playwright and must not become
# reachable through this module by a widened root.
RESEARCH_ROOT = Path(
    os.environ.get("KIPI_BROWSER_RESEARCH_ROOT",
                   os.path.expanduser("~/.config/kipi/browser-profiles")))

# The founder's real Chrome profile. Refused by name, and so is anything under
# it, because the directory a live session actually occupies is `Chrome/Default`
# and an exact-match-only refusal waves that straight through.
REAL_CHROME = Path(os.path.expanduser("~/Library/Application Support/Google/Chrome"))

DEFAULT_TIMEOUT_MS = 45000

# A Chrome persistent context is SINGLE-HOLDER. When the founder has his own
# window open on a research profile, Playwright cannot launch against it at all.
# Measured live 2026-08-31 08:13, verbatim from the receipt:
#   "Opening in existing browser session. This usually means that the profile is
#    already in use by another instance of Chromium."
# That is benign, expected and transient: the window that blocks the probe is
# usually him repairing the very session being watched. It is NOT the same
# condition as a browser that will not start, and collapsing the two is how a
# run that learned nothing printed "0 dead" in production on day one.
#
# Keyed on the message rather than on SingletonLock: measured the same morning,
# that profile directory held no Singleton* file at all while a live Chrome
# process was holding it, so the lock file is not a reliable signal here.
PROFILE_HELD_MARKERS = (
    "already in use by another instance",
    "opening in existing browser session",
)


def _looks_held(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in PROFILE_HELD_MARKERS)

# Far enough off any plausible desktop that the window never appears, near
# enough that Chrome still lays out and renders normally.
OFFSCREEN_ARGS = ("--window-position=-32000,-32000", "--window-size=1280,900")


class ProfileRefused(Exception):
    """A profile directory this module will not open. Never caught internally."""


class BrowserEnvError(Exception):
    """Playwright missing, Chromium missing, launch failed. Environmental."""


@dataclass
class ProbeResult:
    """One liveness observation.

    THE THREE STATES ARE DELIBERATELY NOT TWO. `logged_in` is False only when a
    page actually loaded and the marker was absent; it is None when nothing
    loaded, because "we could not look" is not "he is logged out". Collapsing
    those two is how a network blip pages the founder about a dead session, and
    how a genuinely dead session hides inside a timeout.
    """
    profile: str
    url: str
    reachable: bool
    logged_in: bool | None
    error: str | None
    reason: str | None
    content_len: int
    at: str
    # Defaulted so the four positional-free constructions in the older tests
    # keep working; `held` is the fourth state the first live morning forced.
    surface: str = ""
    held: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def resolve_profile_dir(path, research_root=None) -> Path:
    """The single chokepoint. Returns the resolved directory or refuses.

    ORDER IS LOAD-BEARING. The Chrome refusal runs FIRST and independently of
    the root check. Today the root is narrow enough that the root check would
    catch Chrome anyway, which means a Chrome branch could be deleted without a
    single test going red -- so the test for it widens the root to $HOME, where
    only this branch can refuse. A guard that cannot be observed failing is not
    a guard.

    Symlinks are resolved before comparison: a link inside the root pointing
    out of it is exactly the shape a path check that trusts its input misses.
    """
    root = Path(research_root) if research_root is not None else RESEARCH_ROOT
    root = Path(os.path.expanduser(str(root))).resolve()
    target = Path(os.path.expanduser(str(path))).resolve()

    chrome = REAL_CHROME.resolve()
    if target == chrome or target.is_relative_to(chrome):
        raise ProfileRefused(
            f"refusing {target}: that is the founder's real Chrome profile. "
            "This capability is isolated from it by design; every session it "
            "holds belongs to a research identity, never to him.")

    if not target.is_relative_to(root):
        raise ProfileRefused(
            f"refusing {target}: outside the declared research root {root}. "
            "Profiles are declared in browser_profiles.json, never discovered.")
    return target


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserEnvError(
            "playwright not installed for this interpreter "
            f"({sys.executable}) -- pip install playwright && "
            "playwright install chromium") from exc
    return sync_playwright


def _context(p, profile_dir: Path):
    try:
        return p.chromium.launch_persistent_context(
            str(profile_dir), headless=False, args=list(OFFSCREEN_ARGS))
    except Exception as exc:  # noqa: BLE001
        raise BrowserEnvError(f"browser launch failed for {profile_dir}: {exc}") from exc


def fetch_html(profile_dir, url: str, timeout_ms: int = DEFAULT_TIMEOUT_MS):
    """(html, error). Never raises for a page-level failure.

    Returning a pair rather than raising is constraint 5 at the lowest level:
    an empty page and a failed navigation have to stay different values all the
    way up, and an exception erases the difference between "nothing was there"
    and "we never got to look".
    """
    directory = resolve_profile_dir(profile_dir)
    directory.mkdir(parents=True, exist_ok=True)
    sync_playwright = _playwright()
    with sync_playwright() as p:
        ctx = _context(p, directory)
        try:
            page = ctx.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)  # late client-side render
            return page.content(), None
        except Exception as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {str(exc)[:200]}"
        finally:
            ctx.close()


def probe(name: str, profile_dir, url: str, logged_in_marker: str,
          timeout_ms: int = DEFAULT_TIMEOUT_MS, fetcher=None,
          surface: str = "") -> ProbeResult:
    """One liveness observation for one profile. Read-only by construction.

    `fetcher` exists so the empty-versus-broken rule can be tested against THIS
    function rather than against ProbeResult values a test typed for itself. A
    test that builds both results by hand passes no matter what this function
    does with them, which is exactly the mutant that survived the first
    mutation round (M5b, 2026-08-30): flipping the load-failure branch to
    report `logged_in=False` changed nothing any test could see.
    """
    at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    fetcher = fetcher or fetch_html
    try:
        html, error = fetcher(profile_dir, url, timeout_ms=timeout_ms)
    except (ProfileRefused, BrowserEnvError) as exc:
        text = f"{type(exc).__name__}: {exc}"
        return ProbeResult(profile=name, url=url, reachable=False, logged_in=None,
                           error=text, reason=None, content_len=0, at=at,
                           surface=surface, held=_looks_held(text))
    if error is not None:
        return ProbeResult(profile=name, url=url, reachable=False, logged_in=None,
                           error=error, reason=None, content_len=0, at=at,
                           surface=surface, held=_looks_held(error))

    found = logged_in_marker.lower() in html.lower()
    return ProbeResult(
        profile=name, url=url, reachable=True, logged_in=found, error=None,
        reason=None if found else
        f"marker {logged_in_marker!r} absent in {len(html)} bytes of loaded page",
        content_len=len(html), at=at, surface=surface)


def screenshot(profile_dir, url: str, out_path,
               timeout_ms: int = DEFAULT_TIMEOUT_MS):
    """(path, error). Same pair contract as fetch_html."""
    directory = resolve_profile_dir(profile_dir)
    directory.mkdir(parents=True, exist_ok=True)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sync_playwright = _playwright()
    with sync_playwright() as p:
        ctx = _context(p, directory)
        try:
            page = ctx.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            page.screenshot(path=str(out), full_page=True)
            return str(out), None
        except Exception as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {str(exc)[:200]}"
        finally:
            ctx.close()


def open_for_manual_login(profile_dir, url: str) -> int:
    """Open a real window at `url` and wait for a HUMAN to close it.

    This module types nothing. Creating a research identity is a human step
    this capability consumes, never one it performs, and re-authenticating a
    profile the far side has already flagged is the documented 2026-07-20
    failure. Nothing on the automated path may call this.
    """
    directory = resolve_profile_dir(profile_dir)
    directory.mkdir(parents=True, exist_ok=True)
    sync_playwright = _playwright()
    with sync_playwright() as p:
        # Visible on purpose: the founder has to see it to use it. This is the
        # one entry point that does NOT throw the window off-screen.
        ctx = p.chromium.launch_persistent_context(str(directory), headless=False)
        page = ctx.new_page()
        page.goto(url)
        print(f"Sign in in the window that opened, then close it.\n  profile: {directory}")
        page.wait_for_event("close", timeout=0)
        ctx.close()
    print(f"session stored in {directory}")
    return 0


def _profiles():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "browser_session_health", HERE / "browser_session_health.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {p["name"]: p for p in mod.load_profiles()}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: browser_session.py {login|probe|fetch} <profile> [url]",
              file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd in ("login", "probe", "fetch") and not rest:
        print(f"{cmd} needs a profile name", file=sys.stderr)
        return 2
    declared = _profiles()
    if cmd in ("login", "probe", "fetch"):
        prof = declared.get(rest[0])
        if prof is None:
            print(f"no profile {rest[0]!r} in browser_profiles.json; "
                  f"declared: {sorted(declared)}", file=sys.stderr)
            return 2
    if cmd == "login":
        return open_for_manual_login(prof["dir"], prof["liveness_probes"][0]["url"])
    if cmd == "probe":
        results = [probe(prof["name"], prof["dir"], s["url"], s["logged_in_marker"],
                         surface=s["name"]).as_dict()
                   for s in prof["liveness_probes"]]
        print(json.dumps(results, indent=2))
        return 0
    if cmd == "fetch":
        if len(rest) < 2:
            print("fetch needs a url", file=sys.stderr)
            return 2
        html, error = fetch_html(prof["dir"], rest[1])
        if error:
            print(error, file=sys.stderr)
            return 1
        sys.stdout.write(html)
        return 0
    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
