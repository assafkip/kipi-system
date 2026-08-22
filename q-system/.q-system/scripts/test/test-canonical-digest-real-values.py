#!/usr/bin/env python3
"""Prove canonical_digest actually READ a live canonical tree, by named value.

Pairs with: prd-canonical-read-path-repair-2026-08-22, issue
crpr-digest-asserts-real-canonical (closes Codex finding-14 / finding-9).

WHY THIS SHAPE (scar, measured 2026-08-22):

  Every other check in this PRD is fixture-level and therefore structurally
  cannot prove a live tree was read. Codex finding-14 named the exact hole: a
  digest of {"talk_tracks":{"metaphor":"placeholder"}, ...} satisfies any
  "some field is nonempty" assertion while having read nothing.

  So this file asserts NAMED values, and it obeys three hard rules:

  1. NEVER assert digest["valid"]. Measured against the real live tree, valid is
     FALSE (3 of 7 _validate_digest checks pass) because the live files were
     retired to pointer docs whose headings no longer match the 2026-07-01
     template the parsers were written for. valid:true is not the success
     signal and valid:false is not the failure signal. Asserting it in either
     direction encodes a wrong belief. (Tracked separately as sp-8804dee7 --
     read-path repair cannot fix a parser/shape mismatch.)

  2. NEVER assert mere non-emptiness. That is finding-14 verbatim.

  3. DERIVE the expected value with an INDEPENDENT reader; never hardcode it.
     This repo is PUBLIC, so a client's decision text must not be baked in.
     A raw regex over decisions.md and the digest's own parser are two
     independent implementations; when they agree on an id that exists only in
     THAT tree, the tree was read. That also keeps the checker instance-agnostic.

THE NEGATIVE CONTROL IS THE POINT. Measured across consulting's two trees:
  live   q-consult/canonical/decisions.md : 1 dated RULE-YYYY-MM-DD id
  fossil q-system/canonical/decisions.md  : 0 (only RULE-XXX / RULE-001/002/003)
A checker that passes against the fossil is the false green this PRD exists to
remove, so --self-test asserts the fossil case FAILS and exits nonzero if it
passes. A check that cannot fail is not a check.

READ-ONLY. This opens canonical files for reading and never writes to any
instance tree; the only path it writes is a private tmp dir for the hermetic
synthetic control.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# test/ -> scripts/ -> .q-system/ -> q-system/ -> repo root. Five levels, not four:
# the first draft used parents[3] and silently resolved to q-system/, which made the
# import REFUSE. It refused rather than passing, which is the contract working.
REPO = Path(__file__).resolve().parents[4]
MCP_SRC = REPO / "plugins" / "kipi-core" / "kipi-mcp" / "src"

# A DATED rule id. The template scaffolding that ships in every fresh instance
# uses RULE-XXX and RULE-001..003, which this deliberately does NOT match --
# that gap is exactly what separates a live tree from a fossil one.
DATED_RULE_RE = re.compile(r"\bRULE-\d{4}-\d{2}-\d{2}[A-Za-z0-9-]*")


class Refusal(Exception):
    """The checker cannot answer. Never a pass, never a skip."""


def _load_digest_fn():
    """Import the digest from the repo copy that ships, and say which file it is."""
    if str(MCP_SRC) not in sys.path:
        sys.path.insert(0, str(MCP_SRC))
    try:
        from kipi_mcp import morning_init  # noqa: WPS433
    except Exception as exc:  # pragma: no cover - environment failure
        raise Refusal(f"cannot import kipi_mcp.morning_init from {MCP_SRC}: {exc}")
    return morning_init.canonical_digest, Path(morning_init.__file__)


class _PathsShim:
    """canonical_digest only ever reads .canonical_dir and .my_project_dir."""

    def __init__(self, canonical_dir: Path, my_project_dir: Path):
        self.canonical_dir = canonical_dir
        self.my_project_dir = my_project_dir


def independent_dated_rule_ids(canonical_dir: Path) -> set[str]:
    """Reader #1: a raw regex over the file. Shares no code with the digest parser."""
    decisions = canonical_dir / "decisions.md"
    if not decisions.is_file():
        return set()
    text = decisions.read_text(encoding="utf-8", errors="ignore")
    return {m.group(0) for m in DATED_RULE_RE.finditer(text)}


def digest_dated_rule_ids(canonical_dir: Path, my_project_dir: Path) -> tuple[set[str], dict]:
    """Reader #2: the shipping parser, reached through the real public entrypoint."""
    canonical_digest, _ = _load_digest_fn()
    digest = canonical_digest(_PathsShim(canonical_dir, my_project_dir))
    found: set[str] = set()
    for entry in digest.get("decisions", []):
        rule = str(entry.get("rule", ""))
        found.update(m.group(0) for m in DATED_RULE_RE.finditer(rule))
    return found, digest


def check_tree(canonical_dir: Path, my_project_dir: Path) -> tuple[bool, str]:
    """True only if both independent readers agree on a dated rule id in THIS tree."""
    if not canonical_dir.is_dir():
        return False, f"no canonical dir at {canonical_dir}"

    expected = independent_dated_rule_ids(canonical_dir)
    if not expected:
        # This is the fossil / fresh-template outcome, and it is a FAILURE, not a skip.
        return False, (
            f"independent reader found no dated RULE-YYYY-MM-DD id in "
            f"{canonical_dir/'decisions.md'} -- this tree is template scaffolding "
            f"or a fossil, not a live canonical tree"
        )

    got, digest = digest_dated_rule_ids(canonical_dir, my_project_dir)
    agreed = expected & got
    if not agreed:
        return False, (
            f"readers DISAGREE: raw file has {sorted(expected)} but "
            f"canonical_digest parsed {sorted(got)} from decisions[] "
            f"({len(digest.get('decisions', []))} entries) -- the digest did not "
            f"read {canonical_dir}"
        )
    # Deliberately NOT asserting digest["valid"]; see module docstring rule 1.
    return True, f"both readers agree on {sorted(agreed)} (valid={digest.get('valid')!r}, not asserted)"


# --------------------------------------------------------------- instance discovery

def fleet_root() -> Path:
    """Same convention as verify-alert-wiring.sh:16."""
    return Path(os.environ.get("KIPI_FLEET_ROOT") or (Path.home() / "projects"))


def registry_instances() -> list[dict]:
    reg = REPO / "instance-registry.json"
    if not reg.is_file():
        raise Refusal(f"no instance registry at {reg}")
    data = json.loads(reg.read_text(encoding="utf-8"))
    return list(data.get("instances", []))


def _named_live_dir(root: Path) -> Path | None:
    """A named q-* domain dir holding canonical/ -- never q-system (that is the fossil)."""
    for child in sorted(root.glob("q-*")):
        if child.is_dir() and child.name != "q-system" and (child / "canonical").is_dir():
            return child
    return None


def find_live_and_fossil() -> tuple[str, Path, Path, Path]:
    """First registered instance carrying BOTH a live dated-rule tree and a fossil tree.

    Refuses rather than skipping. Instance names are printed locally only; this
    function hardcodes none, which is what keeps the public repo clean.
    """
    reasons = []
    for entry in registry_instances():
        path = Path(entry.get("path", ""))
        if not path.is_dir():
            reasons.append(f"{entry.get('name')}: path absent")
            continue
        live = _named_live_dir(path)
        if live is None:
            reasons.append(f"{entry.get('name')}: no named q-* dir with canonical/")
            continue
        if not independent_dated_rule_ids(live / "canonical"):
            reasons.append(f"{entry.get('name')}: live tree has no dated rule id")
            continue
        fossil = path / "q-system" / "canonical"
        if not (fossil / "decisions.md").is_file():
            reasons.append(f"{entry.get('name')}: no fossil decisions.md to control against")
            continue
        return str(entry.get("name")), live / "canonical", live / "my-project", fossil
    raise Refusal(
        "no registered instance has BOTH a live dated-rule canonical tree and a "
        "fossil q-system/canonical/decisions.md to control against. Refusing "
        "rather than skipping: a skip here is a false green.\n  " + "\n  ".join(reasons)
    )


def synthetic_fossil() -> Path:
    """Hermetic negative control: template scaffolding, exactly as a fresh instance ships.

    Always available, so the negative half of this checker never silently stops
    running just because a particular machine lacks the real fossil.
    """
    tmp = Path(tempfile.mkdtemp(prefix="canon-fossil-control-"))
    canon = tmp / "canonical"
    canon.mkdir()
    (canon / "decisions.md").write_text(
        "# Decision Log\n\n"
        "## Format <!-- pin -->\n\n"
        "### RULE-XXX: [Name]\n\n"
        "## Starter Rules <!-- pin -->\n\n"
        "### RULE-001: Warm Intro Beats Cold\n\n"
        "### RULE-002: Auto-Close Dead Loops\n\n"
        "### RULE-003: Max 1 Value Drop Per Person Per Week\n",
        encoding="utf-8",
    )
    (tmp / "my-project").mkdir()
    return tmp


# ------------------------------------------------------------------------- self-test

def synthetic_live(rule_id: str = "RULE-2026-01-02-Z") -> Path:
    """Hermetic POSITIVE control: a tree a correct checker MUST pass.

    WHY THIS EXISTS (scar, measured 2026-08-22): the first version of this file
    made only the NEGATIVE control runnable off-fleet, so on a machine with no
    kipi instances -- every CI runner -- the single assertion was "the fossil
    fails". A checker hardcoded to `return False` passes that. A one-directional
    control is the false green this PRD exists to remove, so the hermetic pair
    runs everywhere: fossil must FAIL and live must PASS in the same run.

    The heading is `### RULE-YYYY-MM-DD...`, which is what _parse_decisions keys
    on ("rule" in heading.lower()), so both readers can see the same id.
    """
    tmp = Path(tempfile.mkdtemp(prefix="canon-live-control-"))
    canon = tmp / "canonical"
    canon.mkdir()
    (canon / "decisions.md").write_text(
        "# Decision Log\n\n"
        f"### {rule_id}: Hermetic positive control\n\n"
        "Body text so the section carries a summary.\n",
        encoding="utf-8",
    )
    (tmp / "my-project").mkdir()
    return tmp


def run_checks(require_fleet: bool) -> int:
    """The whole check. `require_fleet` changes REPORTING, never an assertion.

    bare run -- `python3 <this file>`, which is exactly what capability-gate.py
        builds at line 617 and it can pass NO arguments at all. require_fleet is
        False: the hermetic pair still both run and both assert; an unreachable
        fleet prints what it could not reach and claims nothing about it.
    --self-test -- operator, on a machine with the fleet checked out.
        require_fleet is True: an unreachable fleet is a REFUSAL, not a skip.

    Scar: this file originally printed argparse help and returned 2 on a bare
    invocation. That made it undeclarable in expected_tests (the gate's only
    bucket that clears present-but-undeclared), so it sat undeclared and turned
    the capability gate red instead.
    """
    _, module_file = _load_digest_fn()
    print(f"[load-path] canonical_digest imported from {module_file}")

    failures = []

    # --- hermetic pair: ALWAYS runs, on every machine, both directions -------
    tmp = synthetic_fossil()
    syn_canon, syn_proj = tmp / "canonical", tmp / "my-project"
    # Validate the control is really what we think before trusting its verdict.
    raw = (syn_canon / "decisions.md").read_text(encoding="utf-8")
    assert "RULE-001" in raw and not DATED_RULE_RE.search(raw), "synthetic fossil control malformed"
    ok, why = check_tree(syn_canon, syn_proj)
    print(f"[control:synthetic-fossil] {syn_canon}\n    -> {'PASS' if ok else 'FAIL'}: {why}")
    if ok:
        failures.append("synthetic fossil PASSED; the checker cannot distinguish a template tree")

    live_tmp = synthetic_live()
    lv_canon, lv_proj = live_tmp / "canonical", live_tmp / "my-project"
    raw_live = (lv_canon / "decisions.md").read_text(encoding="utf-8")
    assert DATED_RULE_RE.search(raw_live), "synthetic live control malformed"
    ok, why = check_tree(lv_canon, lv_proj)
    print(f"[control:synthetic-live] {lv_canon}\n    -> {'PASS' if ok else 'FAIL'}: {why}")
    if not ok:
        failures.append(f"synthetic LIVE tree FAILED; checker cannot recognise a live tree: {why}")

    # --- real fleet: the only half that can prove a SHIPPED tree is read -----
    fleet_ran = False
    try:
        name, live_canon, live_proj, fossil_canon = find_live_and_fossil()
    except Refusal as exc:
        if require_fleet:
            raise
        print(f"[fleet] SKIPPED: {exc}")
        print("[fleet] this run proves NOTHING about any real instance tree; the "
              "hermetic pair above is everything it checked.")
    else:
        fleet_ran = True
        print(f"[instance] {name}")
        ok, why = check_tree(fossil_canon, fossil_canon.parent / "my-project")
        print(f"[control:real-fossil] {fossil_canon}\n    -> {'PASS' if ok else 'FAIL'}: {why}")
        if ok:
            failures.append(f"real fossil {fossil_canon} PASSED; checker does not separate fossil from live")
        ok, why = check_tree(live_canon, live_proj)
        print(f"[subject:live] {live_canon}\n    -> {'PASS' if ok else 'FAIL'}: {why}")
        if not ok:
            failures.append(f"live tree {live_canon} FAILED: {why}")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    tail = "; real instance tree proved read by name." if fleet_ran else " (fleet half not reached)."
    print(f"PASS: hermetic pair separated fossil from live{tail}")
    return 0


def self_test() -> int:
    """Back-compat alias. The fleet is REQUIRED here."""
    return run_checks(require_fleet=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true",
                    help="require the real fleet: an unreachable instance refuses, never skips")
    ap.add_argument("--canonical-dir", type=Path, help="check one tree directly")
    ap.add_argument("--my-project-dir", type=Path)
    args = ap.parse_args()

    try:
        if args.canonical_dir:
            proj = args.my_project_dir or args.canonical_dir.parent / "my-project"
            ok, why = check_tree(args.canonical_dir, proj)
            print(f"{'PASS' if ok else 'FAIL'} {args.canonical_dir}: {why}")
            return 0 if ok else 1
        # No flag is the RUNNER's invocation and it must be the real check, not help.
        return run_checks(require_fleet=args.self_test)
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
