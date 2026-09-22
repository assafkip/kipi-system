#!/usr/bin/env python3
"""settings-template-sync-check: catch enforcement hooks drifted between the two
settings files (both directions).

Scar (2026-06-30): `kipi update` rebuilds each instance's settings.json from
settings-template.json ONLY. A hook wired in the skeleton's runtime
.claude/settings.json but absent from settings-template.json ships its SCRIPT to
the fleet (q-system/ rsyncs from git HEAD) while the SWITCH never propagates --
it ran dead in 18/18 instances (lessons-validator, wiring-check, memory-confidence
+ 5 lints). The inverse also drifts: a hook in the template but not in the
skeleton's settings.json runs dead in the skeleton's own runtime (scar sp-aa7e4995:
memory-freshness-check + prompt-only-enforcement-guard). This check fails on either
direction for any hook invoking a PROPAGATED script.

Modes:
- CLI / preflight (`--check`, or stdin empty): compare the repo's two settings
  files; exit 2 on divergence. Used as a `kipi update` preflight and manually.
- PostToolUse hook (hook JSON on stdin): self-scope on edits to settings.json or
  settings-template.json; same comparison; exit 2 blocks the edit.

No-op (exit 0) when settings-template.json is absent (i.e. inside an instance --
instances do not propagate further, so there is nothing to strand). stdlib only.
"""
import json
import os
import re
import sys

# Scripts that legitimately live ONLY in the skeleton runtime settings.json.
# This check itself is meaningless inside an instance (no template there), so it
# is skeleton-only by design -- without this entry the check would flag itself.
SKELETON_ONLY = {
    "settings-template-sync-check.py",
    # NOTHING ELSE BELONGS HERE RIGHT NOW, and that is the point.
    #
    # Using this set to park a gate "temporarily" is a real pattern -- it happened
    # on 2026-07-28, when all three grounding gates were held here (ASK-229) while
    # their false positives were fixed, then released as each became shippable
    # (ASK-231/232/233 for two of them, ASK-235 for read-first-gate).
    #
    # It is also a fragile one, so if you are about to add an entry, read this
    # first. A held-back gate is dormant ONLY because of its line here. The line
    # looks like bookkeeping, it carries no expiry, and the natural way to silence
    # a sync-check complaint is to delete the line that is "causing" it -- which
    # silently ships a gate that was deliberately switched off. Nothing downstream
    # would notice.
    #
    # So a hold is a temporary state that owes an exit, not a place to leave things:
    #   1. Open a tracking issue FIRST and name it in the comment beside the entry,
    #      with the measured reason for the hold. "It seemed risky" is not a reason;
    #      ASK-235 held read-first-gate on a measured 100% block rate against a
    #      subagent transcript, and released it when that dropped to 0.
    #   2. The exit condition goes in the comment too, so the next person can tell
    #      whether the hold is still earned or is just old.
    #   3. Remove the entry the moment the gate ships. A stale entry does not fail
    #      loudly; it means a gate quietly never reached 21 instances.
    #
    # The strongest version of this rule is the one applied on 2026-07-28: prefer
    # fixing the gate so it can ship over parking it here. An empty held-back list
    # has no fragile line for anyone to delete.
}

# Scripts that legitimately live ONLY in settings-template.json (fleet) and not in
# the skeleton's own runtime settings.json. Empty by default: a hook in the
# template but not the skeleton runs dead in the skeleton itself (scar sp-aa7e4995:
# memory-freshness-check + prompt-only-enforcement-guard were live in the fleet but
# dead in the skeleton). Add here only when an asymmetry is deliberate.
# Hooks that intentionally run ONLY on instances (the skeleton self-detects and no-ops),
# so they belong in settings-template.json but NOT in the skeleton's own .claude/settings.json.
FLEET_ONLY = {
    "instance-automation-guard.py",
    "miyo-session-pull.py",
    "miyo-research-gate.py",
}

# A hook "propagates" when it invokes a script under a directory kipi update
# rsyncs into instances. Such a hook's switch MUST live in the template too.
SCRIPT_RE = re.compile(
    r"q-system/(?:\.q-system/scripts|hooks)/([A-Za-z0-9_\-]+\.(?:py|sh))"
)


def scripts_in_hooks(settings):
    """Set of propagated-script basenames referenced by any hook command."""
    found = set()
    for _event, groups in settings.get("hooks", {}).items():
        for grp in groups:
            for h in grp.get("hooks", []):
                for name in SCRIPT_RE.findall(h.get("command", "")):
                    found.add(name)
    return found


def find_divergence(repo_root):
    """Both drift directions. Returns (stranded, skeleton_gap) or None for no-op.

    stranded     -- in settings.json, not template: ships dead to the fleet.
    skeleton_gap -- in template, not settings.json: runs dead in the skeleton.
    """
    sj = os.path.join(repo_root, ".claude", "settings.json")
    st = os.path.join(repo_root, "settings-template.json")
    if not os.path.isfile(st) or not os.path.isfile(sj):
        return None
    try:
        runtime = scripts_in_hooks(json.load(open(sj)))
        template = scripts_in_hooks(json.load(open(st)))
    except (json.JSONDecodeError, OSError):
        return None
    stranded = sorted((runtime - template) - SKELETON_ONLY)
    skeleton_gap = sorted((template - runtime) - FLEET_ONLY)
    return (stranded, skeleton_gap)


# GUARD DRIFT (ASK-1166): the same (event, script) wired in both files, guarded
# with an existence test in the template and bare in .claude/settings.json. A bare
# `python3 missing.py` exits 2, which a hook reads as BLOCK, so a script absent
# from a checkout blocks every tool call on that event instead of no-opping.
GUARD_RE = re.compile(r"(?:\btest -f |\[ -f )")

# Recorded divergences, "Event:script". Measured 2026-09-15: 22 wirings, all the
# skeleton runtime's older bare shape. They are recorded, not fixed, because the
# only sanctioned writer of .claude/settings.json (apply-claude-changes.sh)
# refuses the fix: its census keys a hook on the exact command string, so adding
# a guard reads as a hook removal ("enforcement ratchet: 1 hooks entr(ies) would
# disappear", exit 2, ASK-1166). Exit: guard the line in settings.json, then
# delete its entry here. A recorded entry that is no longer drifting FAILS the
# check, so this list can only shrink and never goes stale silently.
_RECORDED_REASON = "ASK-1166: apply-claude-changes ratchet refuses a rewritten hook command"
GUARD_DRIFT_RECORDED = {key: _RECORDED_REASON for key in (
    "PostToolUse:audhd-lint.py",
    "PostToolUse:batch-uniformity-lint.py",
    "PostToolUse:decision-origin-tag-lint.py",
    "PostToolUse:enforced-claim-lint.py",
    "PostToolUse:format-lint.py",
    "PostToolUse:headline-lint.py",
    "PostToolUse:hook_envelope_audit.py",
    "PostToolUse:lessons-validator.py",
    "PostToolUse:linear-filer-label-lint.py",
    "PostToolUse:linkedin-format-lint.py",
    "PostToolUse:memory-confidence-validator.py",
    "PostToolUse:prompt-only-enforcement-guard.py",
    "PostToolUse:voice-lint.py",
    "PostToolUse:voice-substance-lint.py",
    "PostToolUse:voiceloop-band-lint.py",
    "PostToolUse:wiring-check.py",
    "SessionStart:memory-scores-surface.py",
    "SessionStart:sycophancy-monthly-check.py",
    "Stop:voice-stop-gate.py",
    "UserPromptSubmit:knowledge-inject.py",
    "UserPromptSubmit:lessons-inject.py",
    "UserPromptSubmit:voice-dna-loader.py",
)}


def guard_states(settings):
    """{"Event:script": is_guarded}; False when ANY command for it is bare."""
    states = {}
    for event, groups in settings.get("hooks", {}).items():
        for grp in groups:
            for h in grp.get("hooks", []):
                cmd = h.get("command", "")
                is_guarded = bool(GUARD_RE.search(cmd))
                for name in SCRIPT_RE.findall(cmd):
                    key = f"{event}:{name}"
                    states[key] = states.get(key, True) and is_guarded
    return states


def find_guard_drift(repo_root):
    """Returns (unrecorded_drift, stale_records) or None for no-op."""
    sj = os.path.join(repo_root, ".claude", "settings.json")
    st = os.path.join(repo_root, "settings-template.json")
    if not os.path.isfile(st) or not os.path.isfile(sj):
        return None
    try:
        runtime = guard_states(json.load(open(sj)))
        template = guard_states(json.load(open(st)))
    except (json.JSONDecodeError, OSError):
        return None
    shared = runtime.keys() & template.keys()
    drift = {k for k in shared if template[k] and not runtime[k]}
    unrecorded = sorted(drift - GUARD_DRIFT_RECORDED.keys())
    stale = sorted(k for k in GUARD_DRIFT_RECORDED if k in shared and k not in drift)
    return (unrecorded, stale)


def report_guard_drift(unrecorded, stale):
    for k in unrecorded:
        sys.stderr.write(
            f"settings-template-sync-check: {k} is guarded (test -f) in "
            "settings-template.json but bare in .claude/settings.json; a missing "
            "script then exits 2 and BLOCKS instead of no-opping. Fix: add the "
            "template's guard to the settings.json line.\n")
    for k in stale:
        sys.stderr.write(
            f"settings-template-sync-check: {k} is recorded in GUARD_DRIFT_RECORDED "
            "but is no longer drifting. Fix: delete its entry.\n")


def repo_root_from(path):
    d = os.path.dirname(os.path.abspath(path))
    while d != "/":
        if os.path.isfile(os.path.join(d, "settings-template.json")):
            return d
        d = os.path.dirname(d)
    return None


def main():
    hook_data = None
    if "--check" not in sys.argv:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        if raw.strip():
            try:
                hook_data = json.loads(raw)
            except json.JSONDecodeError:
                hook_data = None

    if hook_data is not None:
        fp = (hook_data.get("tool_input") or {}).get("file_path", "")
        norm = fp.replace("\\", "/")
        if not (norm.endswith("/.claude/settings.json") or norm.endswith("/settings-template.json")):
            sys.exit(0)
        root = os.environ.get("CLAUDE_PROJECT_DIR") or repo_root_from(fp) or os.getcwd()
    else:
        root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    result = find_divergence(root)
    if not result:
        sys.exit(0)
    stranded, skeleton_gap = result
    unrecorded, stale = find_guard_drift(root) or ([], [])
    report_guard_drift(unrecorded, stale)
    if not stranded and not skeleton_gap:
        sys.exit(2 if unrecorded or stale else 0)

    if stranded:
        sys.stderr.write(
            "settings-template-sync-check: hook(s) wired in .claude/settings.json "
            "but MISSING from settings-template.json -> they ship DEAD to the fleet "
            "(kipi update rebuilds instance settings from the template only):\n"
        )
        for s in stranded:
            sys.stderr.write(f"  - {s}\n")
        sys.stderr.write(
            "Fix: add to settings-template.json, or add to SKELETON_ONLY if "
            "intentionally skeleton-only.\n"
        )
    if skeleton_gap:
        sys.stderr.write(
            "settings-template-sync-check: hook(s) in settings-template.json but "
            "MISSING from .claude/settings.json -> they run DEAD in the skeleton's "
            "own runtime (the fleet has them, the skeleton does not):\n"
        )
        for s in skeleton_gap:
            sys.stderr.write(f"  - {s}\n")
        sys.stderr.write(
            "Fix: add to .claude/settings.json, or add to FLEET_ONLY if "
            "intentionally fleet-only.\n"
        )
    sys.exit(2)


if __name__ == "__main__":
    main()
