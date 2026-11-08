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

# === THE DRIFT HEALS ITSELF (ASK-4022) =====================================
# A drift finding used to wait for a hand reinstall. heal_plist_drift reinstalls
# the job through install-plist.sh and files only what it could not heal. Every
# effect is a fake here: nothing reloads a real job.
_drift = {"subject": "com.kipi.dispatch",
          "title": "installed job drifted from its committed template: com.kipi.dispatch (1 key)",
          "body": "## Values that differ"}
_other = {"subject": "com.kipi.x", "title": "a template could not be rendered: com.kipi.x", "body": "b"}


def _heal(**kw):
    calls = []
    def install(label):
        calls.append(label)
        return kw.get("rc", 0), "tail"
    args = dict(install=install, running=lambda _l: kw.get("running", False),
                paused=kw.get("paused", set()), current=lambda: kw.get("current", True),
                recheck=lambda: kw.get("still", []))
    left, healed = fh.heal_plist_drift([_drift, _other], **args)
    return left, healed, calls


_l, _h, _c = _heal()
check("a drifted job is reinstalled and its finding drops", (_h, _c, _l), (["com.kipi.dispatch"], ["com.kipi.dispatch"], [_other]))
_l, _h, _c = _heal(running=True)
check("a job that is running is not reloaded; the finding stays and says why",
      (_h, _c, "was running" in _l[0]["body"]), ([], [], True))
_l, _h, _c = _heal(paused={"com.kipi.dispatch"})
check("a paused job is never re-armed", (_h, _c, len(_l)), ([], [], 2))
_l, _h, _c = _heal(current=False)
check("a checkout behind origin/main installs nothing and says so",
      (_h, _c, "not at origin/main" in _l[0]["body"]), ([], [], True))
_l, _h, _c = _heal(rc=1)
check("a failed install keeps the finding with the installer's exit code",
      (_h, "exited 1" in _l[0]["body"]), ([], True))
_l, _h, _c = _heal(still=[_drift])
check("an install that leaves drift keeps the finding", (_h, len(_l)), ([], 2))
check("a finding that is not drift is never touched", _heal()[0], [_other])
# Negative self-test: a heal that ignores the running guard reloads a live job.
_src = Path(fh.__file__).read_text()
_anchor = "        if running(label):\n"
check("mutant anchor present exactly once", _src.count(_anchor), 1)
_mut_ns = {"__file__": fh.__file__, "__name__": "fh_heal_mutant"}
exec(compile(_src.replace(_anchor, "        if False:\n"), "fh-mutant", "exec"), _mut_ns)
_calls = []
_mut_ns["heal_plist_drift"]([_drift], install=lambda l: (_calls.append(l), (0, ""))[1],
                            running=lambda _l: True, paused=set(), current=lambda: True,
                            recheck=lambda: [])
check("mutant killed: without the running guard a live job is reloaded, so the guard case can fail",
      _calls, ["com.kipi.dispatch"])

# PR #667 round 1, major: "disabled" is declared intent plus the ledgers, through
# launchd-intent-verify load_intent, not the watchdog ledger reader alone.
import os as _os
_home_saved = _os.environ.get("HOME")
_ih = WORK / "intent-home"; (_ih / ".config" / "kipi").mkdir(parents=True, exist_ok=True)
(_ih / ".config" / "kipi" / "launchd-intent.json").write_text(
    '{"jobs": [{"label": "com.kipi.dispatch", "intent": "disabled"}]}')
_os.environ["HOME"] = str(_ih)
try:
    _dis = fh._disabled_labels()
    (_ih / ".config" / "kipi" / "launchd-intent.json").write_text("{not json")
    _dis_bad = fh._disabled_labels()
finally:
    _os.environ["HOME"] = _home_saved
check("a job declared intent disabled in launchd-intent.json is in the disabled set",
      "com.kipi.dispatch" in _dis, True)
check("an unreadable intent manifest disables every reload for the run", _dis_bad, {"*"})
_l, _h, _c = _heal(paused={"*"})
check("...and then nothing is re-armed, and the finding says why",
      (_h, _c, "intent is disabled" in _l[0]["body"]), ([], [], True))
# PR #667 round 1, minor: an install that leaves drift says a reload ran.
_l, _h, _c = _heal(still=[_drift])
check("an install that leaves drift keeps the finding and says a bootout and bootstrap ran",
      ("bootout and a bootstrap ran" in _l[0]["body"], _c), (True, ["com.kipi.dispatch"]))
# PR #667 round 1, minor: the job running this check heals itself after it exits.
_os.environ["XPC_SERVICE_NAME"] = "com.kipi.dispatch"
try:
    _self = []
    _calls2 = []
    _left, _healed = fh.heal_plist_drift(
        [_drift], install=lambda l: (_calls2.append(l), (0, ""))[1], running=lambda _l: True,
        paused=set(), current=lambda: True, recheck=lambda: [],
        self_heal=lambda l: (_self.append(l), True)[1])
finally:
    _os.environ.pop("XPC_SERVICE_NAME", None)
check("the job running this check gets a deferred self-reinstall, not a live reload",
      (_self, _calls2, "detached reinstall" in _left[0]["body"]), (["com.kipi.dispatch"], [], True))
# PR #667 round 1, minor: a failed fetch is not a current checkout.
_nogit = WORK / "no-remote"; _nogit.mkdir(exist_ok=True)
subprocess.run(["git", "init", "-q", str(_nogit)], check=True)
_rr = fh.REPO_ROOT
fh.REPO_ROOT = _nogit
try:
    _cur = fh._checkout_at_origin_main()
finally:
    fh.REPO_ROOT = _rr
check("a checkout whose fetch fails is never treated as current", _cur, False)

# ASK-4055 (PR #667 round 2, major): the deferred reinstall writes its result and
# pages on failure. A fake installer exits 3; the wait is on a pid that exits now.
_sh_dir = WORK / "selfheal"; _pages = WORK / "selfheal-pages.log"
_fake_inst = WORK / "fake-install.sh"
_fake_inst.write_text("#!/bin/bash\necho bootstrap failed for $1 >&2\nexit 3\n")
_fake_notify = WORK / "fake-notify.sh"
_fake_notify.write_text(f'#!/bin/bash\nprintf "%s\\n" "$*" >> "{_pages}"\n')
_saved = (fh.SELF_HEAL_DIR, fh.PLIST_INSTALLER, fh.NOTIFY)
fh.SELF_HEAL_DIR, fh.PLIST_INSTALLER, fh.NOTIFY = _sh_dir, _fake_inst, _fake_notify
try:
    _short = subprocess.Popen(["sleep", "0.2"])
    _started = fh._self_heal_after_exit("com.kipi.fleet-health", wait_pid=_short.pid)
    _short.wait()
    import time as _time
    _res = _sh_dir / "com.kipi.fleet-health.result"
    for _ in range(100):
        if _res.exists() and _pages.exists():
            break
        _time.sleep(0.1)
    _text = _res.read_text() if _res.exists() else ""
    check("the deferred reinstall writes its exit code and output",
          (_started, _text.startswith("rc=3 "), "bootstrap failed" in _text), (True, True, True))
    check("a failed deferred reinstall pages once, naming the job and the fix",
          (_pages.read_text().count("\n") if _pages.exists() else 0,
           "com.kipi.fleet-health" in (_pages.read_text() if _pages.exists() else "")), (1, True))
    _os.environ["XPC_SERVICE_NAME"] = "com.kipi.fleet-health"
    _drift_self = dict(_drift, subject="com.kipi.fleet-health")
    try:
        _left, _healed = fh.heal_plist_drift(
            [_drift_self], install=lambda l: (0, ""), running=lambda _l: True,
            paused=set(), current=lambda: True, recheck=lambda: [],
            self_heal=lambda l: True)
    finally:
        _os.environ.pop("XPC_SERVICE_NAME", None)
    check("the next run's finding carries the previous deferred reinstall's failure",
          "The previous one: rc=3 " in _left[0]["body"], True)
finally:
    fh.SELF_HEAL_DIR, fh.PLIST_INSTALLER, fh.NOTIFY = _saved

# ASK-4055 (PR #667 delta, minor): the report-only detectors read the same declared
# intent as the heal. A job disabled ONLY in launchd-intent.json files no dark-job
# and no never-installed finding; with intent unreadable they fall back to the ledgers.
_ih2 = WORK / "intent-home-2"; (_ih2 / ".config" / "kipi").mkdir(parents=True, exist_ok=True)
(_ih2 / ".config" / "kipi" / "launchd-intent.json").write_text(
    '{"jobs": [{"label": "com.kipi.never-installed", "intent": "disabled"}]}')
_tpl = WORK / "tpl-4055"; _agt = WORK / "agents-4055"; _tpl.mkdir(); _agt.mkdir()
(_tpl / "com.kipi.never-installed.plist").write_text("<plist/>")
# PR #676 round 1, major: the CONFLICT case. A job paused in a ledger that the
# manifest calls enabled stays stopped for the reporters (the union), and the dark
# detector, run for real, files neither it nor the manifest-disabled job.
(_ih2 / ".config" / "kipi" / "launchd-intent.json").write_text(
    '{"jobs": [{"label": "com.kipi.never-installed", "intent": "disabled"},'
    ' {"label": "com.kipi.ledger-paused", "intent": "enabled"}]}')
(_ih2 / ".config" / "kipi" / "launchd-paused.txt").write_text("com.kipi.ledger-paused\n")
_saved_dark = (fh._launchd_labels, fh._is_loaded)
fh._launchd_labels = lambda: ["com.kipi.never-installed", "com.kipi.ledger-paused", "com.kipi.truly-dark"]
fh._is_loaded = lambda _l: False
_os.environ["HOME"] = str(_ih2)
try:
    _stopped = fh._stopped_labels()
    _ni = fh.never_installed_findings(template_dir=_tpl, launch_agents=_agt)
    _dark = sorted(f["subject"] for f in fh.detect_dark_jobs({}))
    (_ih2 / ".config" / "kipi" / "launchd-intent.json").write_text("{not json")
    _stopped_bad = fh._stopped_labels()
finally:
    _os.environ["HOME"] = _home_saved
    fh._launchd_labels, fh._is_loaded = _saved_dark
check("a job declared disabled only in launchd-intent.json is stopped for the detectors",
      "com.kipi.never-installed" in _stopped, True)
check("a ledger-paused job the manifest calls enabled is still stopped for the reporters",
      "com.kipi.ledger-paused" in _stopped, True)
check("...so never-installed files nothing for the manifest-disabled one", _ni, [])
check("detect_dark_jobs, run for real, files only the job no source stopped",
      [s for s in _dark if "never-installed" in s or "ledger-paused" in s or "truly-dark" in s],
      [s for s in _dark if "truly-dark" in s])
check("...and it does file that one", any("truly-dark" in s for s in _dark), True)
check("an unreadable intent leaves the ledgers, never 'everything stopped'",
      ("*" in _stopped_bad, "com.kipi.ledger-paused" in _stopped_bad), (False, True))
# Negative control for the conflict case: with the heal's reader (round 1's choice)
# the ledger-paused job IS filed as dark, so the check above can go red.
(_ih2 / ".config" / "kipi" / "launchd-intent.json").write_text(
    '{"jobs": [{"label": "com.kipi.ledger-paused", "intent": "enabled"}]}')
_real_stopped2 = fh._stopped_labels
fh._stopped_labels = fh._disabled_labels
fh._launchd_labels = lambda: ["com.kipi.ledger-paused"]
fh._is_loaded = lambda _l: False
_os.environ["HOME"] = str(_ih2)
try:
    _dark_r1 = [f["subject"] for f in fh.detect_dark_jobs({})]
finally:
    _os.environ["HOME"] = _home_saved
    fh._stopped_labels = _real_stopped2
    fh._launchd_labels, fh._is_loaded = _saved_dark
check("negative control: the manifest-resolved reader files the ledger-paused job as dark",
      any("ledger-paused" in s for s in _dark_r1), True)
# Negative control: with the ledger-only reader (the old one) the same job IS filed,
# so the check above can go red.
_os.environ["HOME"] = str(_ih2)
(_ih2 / ".config" / "kipi" / "launchd-intent.json").write_text(
    '{"jobs": [{"label": "com.kipi.never-installed", "intent": "disabled"}]}')
_real_stopped = fh._stopped_labels
fh._stopped_labels = fh._paused_labels
try:
    _ni_old = fh.never_installed_findings(template_dir=_tpl, launch_agents=_agt)
finally:
    fh._stopped_labels = _real_stopped
    _os.environ["HOME"] = _home_saved
check("negative control: the ledger-only reader files the manifest-disabled job",
      [f["subject"] for f in _ni_old], ["com.kipi.never-installed"])

# Only the daily job own --apply run heals. A test or a dry read that calls the
# detector must reload nothing: test-fleet-health-daily.py calls every detector.
_saved = (fh.REPO_ROOT, fh.plist_drift_findings, fh.heal_plist_drift, fh.HEAL_APPLY)
_fake_root = WORK / "primary"; (_fake_root / ".git").mkdir(parents=True, exist_ok=True)
_heal_calls = []
fh.REPO_ROOT = _fake_root
fh.plist_drift_findings = lambda: [_drift]
fh.heal_plist_drift = lambda fs: (_heal_calls.append(1), ([], ["com.kipi.dispatch"]))[1]
fh.HEAL_APPLY = False
_dry = fh.detect_plist_drift(None)
fh.HEAL_APPLY = True
_live = fh.detect_plist_drift(None)
fh.REPO_ROOT, fh.plist_drift_findings, fh.heal_plist_drift, fh.HEAL_APPLY = _saved
check("without --apply the detector reports drift and reloads nothing; with it, it heals",
      (_dry, len(_heal_calls), _live), ([_drift], 1, []))

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
