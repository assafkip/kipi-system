#!/usr/bin/env python3
"""Pairs with fleet-health-daily.py's `plist-drift` detector (ASK-860).

THE SCAR THIS PINS. 2026-08-15 the dispatch daily cap read 12 in the committed
template `com.kipi.dispatch.plist` and **40** in the installed job at
`~/Library/LaunchAgents/com.kipi.dispatch.plist`. The committed copy is what a
reader inspects to answer "what is the cap?"; the installed copy is the cap that
actually runs. Nothing in the fleet compared them, so for an unknown period the
loop was authorised to start 40 issues a day against a stated ceiling of 12.

`install-plist.sh` makes rendering correct when it is USED. It cannot notice a
job installed some other way or edited in place. This detector is what notices.

Run: python3 test-plist-drift.py   (exit 0 = pass)
"""

import importlib.util
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
HEALTH = SCRIPTS / "fleet-health-daily.py"
INSTALLER = SCRIPTS / "install-plist.sh"

_spec = importlib.util.spec_from_file_location("fh", HEALTH)
fh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fh)

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
    else:
        print(f"  ok: {name}")


def body_of(findings, subject):
    for f in findings:
        if f["subject"] == subject:
            return f["body"]
    return ""


# ---------------------------------------------------------------------------
# The fixture comes from the PRODUCER, never from this file's imagination.
#
# A plist I hand-write tests my mental model of install-plist.sh, not
# install-plist.sh. So the "committed" side of every drift case below is the real
# `com.kipi.dispatch.plist` put through the real installer's `--render-only`, and
# the "live" side is that same rendered output with ONE value moved. That is
# exactly the shape of the 2026-08-15 incident.
# ---------------------------------------------------------------------------

WORK = Path(tempfile.mkdtemp(prefix="ask860-"))
RENDERED = WORK / "rendered-dispatch.plist"
_render = subprocess.run(
    ["bash", str(INSTALLER), "com.kipi.dispatch", "--render-only", str(RENDERED)],
    capture_output=True, text=True, timeout=60)
check("the producer rendered a real template (rc)", _render.returncode, 0)
if _render.returncode != 0:
    print(_render.stderr, file=sys.stderr)
    print("FAIL: cannot build a producer-derived fixture", file=sys.stderr)
    sys.exit(1)

# Through the module's OWN comment rule, not a second one invented here. The
# committed templates carry `--` inside their XML comments (long prose blocks
# citing PR rounds); CoreFoundation accepts that, so launchd loads them and the
# jobs run, while expat rejects the document outright. A fixture builder with its
# own parser would drift from the detector's.
BASE = plistlib.loads(fh._XML_COMMENT_RE.sub("", RENDERED.read_text()).encode())
check("the rendered fixture carries the cap key that drifted",
      "KIPI_DISPATCH_DAILY_MAX" in BASE["EnvironmentVariables"], True)


def _dirs(live_plist_by_label, fmt=plistlib.FMT_XML):
    """(template dir, LaunchAgents dir) holding the real render plus mutations.

    `fmt` is the format the LIVE copy is written in. Both are legitimate: a job
    edited with `defaults write` ends up as FMT_BINARY, and launchd loads it.
    """
    root = Path(tempfile.mkdtemp(prefix="ask860-case-", dir=WORK))
    templates, agents = root / "templates", root / "LaunchAgents"
    templates.mkdir()
    agents.mkdir()
    shutil.copy(RENDERED, templates / "com.kipi.dispatch.plist")
    for label, data in live_plist_by_label.items():
        (agents / f"{label}.plist").write_bytes(plistlib.dumps(data, fmt=fmt))
    return templates, agents


def _mutated(**env):
    """The rendered plist with EnvironmentVariables values replaced."""
    import copy

    data = copy.deepcopy(BASE)
    data["EnvironmentVariables"].update(env)
    return data


def _drift(live_by_label, fmt=plistlib.FMT_XML):
    """Run the detector over a fixture pair. Templates are ALREADY rendered here,
    so the renderer is the identity: the case under test is the COMPARE, not the
    substitution (which the producer above already exercised for real)."""
    templates, agents = _dirs(live_by_label, fmt=fmt)
    return fh.plist_drift_findings(
        template_dir=templates,
        launch_agents=agents,
        render=lambda path: path.read_text(),
    )


# === THE REPRODUCER: the 2026-08-15 incident, replayed =====================
# Committed says 10 (whatever the template holds), live says 40. RED at HEAD,
# where nothing looks at the installed copy at all.
_live_cap = BASE["EnvironmentVariables"]["KIPI_DISPATCH_DAILY_MAX"]
_incident = _drift({"com.kipi.dispatch": _mutated(KIPI_DISPATCH_DAILY_MAX="40")})
check("a drifted live value is DETECTED", len(_incident), 1)
check("the finding's subject is the job label, so it is ONE issue forever",
      _incident[0]["subject"] if _incident else None, "com.kipi.dispatch")

_body = body_of(_incident, "com.kipi.dispatch")
check("the body NAMES THE KEY", "KIPI_DISPATCH_DAILY_MAX" in _body, True)
check("the body carries the COMMITTED value", f"`{_live_cap}`" in _body, True)
check("the body carries the LIVE value", "`40`" in _body, True)

# === THE NEGATIVE SELF-TEST ================================================
# A check that cannot go green for the right reason is decoration. An installed
# job that MATCHES its rendered template must produce nothing at all -- otherwise
# the detector files a permanent Linear issue for every job, every morning.
check("an identical installed job produces NO finding",
      _drift({"com.kipi.dispatch": BASE}), [])

# === REPORT, DO NOT AUTO-REPAIR ============================================
# A live value may have been set deliberately during an incident. The detector
# must not carry a repair as a side effect, and must not tell the operator the
# machine was changed for them.
check("the detector never writes to the live plist",
      plistlib.loads((_dirs({"com.kipi.dispatch": _mutated(KIPI_DISPATCH_DAILY_MAX='40')})[1]
                      / "com.kipi.dispatch.plist").read_bytes())
      ["EnvironmentVariables"]["KIPI_DISPATCH_DAILY_MAX"], "40")
check("the body offers the render command rather than claiming a fix",
      "install-plist.sh" in _body and "auto" not in _body.lower(), True)

# === ASK-204: what a finding CARRIES =======================================
# A key the repo declares is the repo's own knob, and its live value is the
# answer the operator needs. A key that exists ONLY on the live copy is operator-
# authored -- the one place a hand-added credential could sit -- so it is named
# and never quoted. That is a STRUCTURAL split (who authored the key), not a
# denylist over value text, which is the architecture ASK-204 threw out.
_secret = _mutated(SOME_TOKEN="lin_api_realvalue")
_leak = _drift({"com.kipi.dispatch": _secret})
_leak_body = body_of(_leak, "com.kipi.dispatch")
check("a live-only key IS reported", "SOME_TOKEN" in _leak_body, True)
check("a live-only key's VALUE is never published",
      "lin_api_realvalue" in _leak_body, False)

# === A JOB WITH NO INSTALLED COPY IS NOT DRIFT =============================
# `detect_dark_jobs` already owns "a job that should be running is not". A
# template with nothing installed is a job that was never armed on this machine,
# and filing it here would fork a second permanent issue for one condition.
check("a template with no installed job produces no drift finding",
      _drift({}), [])

# === A DETECTOR THAT CANNOT LOOK SAYS SO ===================================
# The silent-disable shape this file has already been corrected for three times:
# quiet is indistinguishable from healthy. An unrenderable template is UNKNOWN.
def _boom(_path):
    raise RuntimeError("render failed")


# ONE fixture root, not two: taking templates from one _dirs() call and agents
# from a second builds a pair that never existed on any machine.
_blind_templates, _blind_agents = _dirs({"com.kipi.dispatch": BASE})
_blind = fh.plist_drift_findings(
    template_dir=_blind_templates,
    launch_agents=_blind_agents,
    render=_boom,
)
check("an unrenderable template yields a finding, not silence", len(_blind), 1)
check("the cannot-run finding has its own subject, so it cannot collide",
      _blind[0]["subject"] if _blind else None, "com.kipi.dispatch--unrenderable")

# === A BINARY INSTALLED JOB IS A REAL JOB, NOT GARBAGE =====================
# `defaults write <plist> KEY value` is THE canonical in-place launchd edit --
# the exact hand-edit this detector exists to catch -- and it rewrites the file
# as bplist00. Reading that with `read_text(errors="ignore")` drops every
# non-UTF-8 byte; plistlib then ACCEPTS the shortened binary rather than
# raising, so the detector both cried wolf on a healthy job and went blind to
# the drift it was built for. Neither failure announced itself.
_bin_identical = _drift({"com.kipi.dispatch": BASE}, fmt=plistlib.FMT_BINARY)
check("a BINARY installed job identical to its template files NOTHING",
      _bin_identical, [])

_bin_incident = _drift({"com.kipi.dispatch": _mutated(KIPI_DISPATCH_DAILY_MAX="40")},
                       fmt=plistlib.FMT_BINARY)
check("the 2026-08-15 drift is still caught when the live job is BINARY",
      len(_bin_incident), 1)
_bin_body = body_of(_bin_incident, "com.kipi.dispatch")
check("the BINARY finding names the key", "KIPI_DISPATCH_DAILY_MAX" in _bin_body, True)
check("the BINARY finding carries the live value", "`40`" in _bin_body, True)
check("the BINARY finding carries the committed value", f"`{_live_cap}`" in _bin_body, True)

# A live copy that is neither valid XML nor a real binary plist stays UNKNOWN.
# Strict decoding is what keeps this from parsing into a confident wrong answer.
_junk_templates, _junk_agents = _dirs({})
(_junk_agents / "com.kipi.dispatch.plist").write_bytes(b"\xff\xfe not a plist \x00\x01")
_junk = fh.plist_drift_findings(
    template_dir=_junk_templates, launch_agents=_junk_agents,
    render=lambda path: path.read_text())
check("an undecodable live job is UNKNOWN, not silently clean",
      [f["subject"] for f in _junk], ["com.kipi.dispatch--unrenderable"])

# === A DIFFERENCE PAST THE DISPLAY CAP MUST STILL BE VISIBLE ===============
# Head-truncating both sides renders a late divergence as two identical cells:
# the issue asserts a difference while showing none. No committed template holds
# a value this long today, which is exactly why nothing would have caught it.
_cap = fh._VALUE_CAP
_long_a, _long_b = "x" * (_cap + 50) + "AAA", "x" * (_cap + 50) + "BBB"
_long_row = fh._drift_finding("com.kipi.demo", [("Env.LONG", _long_a, _long_b)], [], [])
check("the two truncated cells are NOT identical",
      fh._shown(_long_a, _long_b) == fh._shown(_long_b, _long_a), False)
check("the committed side of the divergence is shown", "AAA" in _long_row["body"], True)
check("the live side of the divergence is shown", "BBB" in _long_row["body"], True)
check("a value under the cap is still shown whole", fh._shown("short", "other"), "short")

# === THE TWO INJECTION KNOBS ARE PAIRED, AND SAY SO ========================
# The default renderer shells install-plist.sh, which resolves templates from
# ITS OWN directory. Moving template_dir without a matching render would compare
# one tree's files against another tree's renders and read that as drift.
_moved, _moved_agents = _dirs({"com.kipi.dispatch": BASE})
try:
    fh.plist_drift_findings(template_dir=_moved, launch_agents=_moved_agents)
    _refused = False
except ValueError:
    _refused = True
check("a moved template_dir with the default renderer is REFUSED", _refused, True)

# === REGISTRY WIRING =======================================================
# A detector not in DETECTORS is a function nobody calls.
_ids = [d["id"] for d in fh.DETECTORS]
check("plist-drift is registered", "plist-drift" in _ids, True)
check("the registry still satisfies its own contract", fh.validate_detectors(), [])

shutil.rmtree(WORK, ignore_errors=True)

if failures:
    print("\nFAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nall plist-drift checks passed")
