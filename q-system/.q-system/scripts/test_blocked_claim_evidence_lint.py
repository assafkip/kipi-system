#!/usr/bin/env python3
"""Reproducer + negative self-test for blocked-claim-evidence-lint.py (ASK-317).

THE REPRODUCER is `CLAIMS` below: the six real false "this is blocked" reports from
one session (RCA rca-inherited-claim-treated-as-verified-2026-08-02, restated in
ASK-317). Each was fluent, specific, wrong, and wrong in the direction that
transferred work to the founder or stopped work entirely. All six must be flagged.

THE NEGATIVE SELF-TEST is the same six claims WITH the command and output that
settles each one attached. All six must pass. A lint that fails this half is a wall,
not a gate -- it would just teach the operator to route around it.

Run: python3 test_blocked_claim_evidence_lint.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINT = HERE / "blocked-claim-evidence-lint.py"


def _load():
    spec = importlib.util.spec_from_file_location("blocked_claim_lint", LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- the six claims, and the pattern each one is an instance of --------------
# (label, claim text as it was actually written, expected pattern id)
CLAIMS = [
    ("merge blocked pending approval",
     "- merge is blocked pending founder approval.",
     "rollup-as-config"),
    ("codex credits block the PR",
     "- codex is out of credits, that blocks the PR.",
     "rollup-as-config"),
    ("degraded.state absent",
     "- no `degraded.state` was written for the codex engine.",
     "lookup-as-runtime-fact"),
    ("relay of the absence claim",
     "- Sharpest finding this round: no degraded.state file was written anywhere.",
     "lookup-as-runtime-fact"),
    ("gh pr merge denied",
     "- `gh pr merge` is denied to the tool layer, so I cannot merge.",
     "my-denial-as-object-property"),
    ("Alice scripts live",
     "- the 10 Alice scripts are LIVE.",
     "lookup-as-runtime-fact"),
]

# --- the settling command + its output, per claim ----------------------------
# Attached as a fenced block directly under the claim, which is exactly the shape
# the remediation text asks for.
SETTLED = [
    CLAIMS[0][1] + "\n\n```\n"
    "gh api repos/assafkip/kipi-system/branches/main/protection --jq .required_pull_request_reviews\n"
    "null\n```\n",
    CLAIMS[1][1] + "\n\n```\n"
    "sed -n '45,55p' plugins/prd-os/scripts/pr-review-agent.sh\n"
    "# codex down -> claude fills PRIMARY and the run posts DEGRADED\n```\n",
    CLAIMS[2][1] + "\n\n```\n"
    "cat .prd-os/engines/codex/degraded.state\n"
    "1\n```\n",
    CLAIMS[3][1] + "\n\n```\n"
    "find .prd-os -name 'degraded.state' -print -exec cat {} +\n"
    ".prd-os/engines/codex/degraded.state\n1\n```\n",
    CLAIMS[4][1] + "\n\n```\n"
    "gh pr merge 74 --squash\n"
    "GraphQL: Pull request is not mergeable (try --admin)\n```\n",
    CLAIMS[5][1] + "\n\n```\n"
    "bash alice/run.sh --list\n"
    "alice/collect.sh: never invoked, no run-log entry\n```\n",
]


# --- subprocess harness (the real hook path) ---------------------------------
def run_hook(answer: str, mode: str = "advisory") -> tuple[int, str]:
    """Feed `answer` as the final assistant text through the Stop hook. -> (rc, stderr)"""
    tmp = Path(tempfile.mkdtemp())
    transcript = tmp / "transcript.jsonl"
    rows = [
        {"message": {"role": "user", "content": [{"type": "text", "text": "status?"}]}},
        {"message": {"role": "assistant",
                     "content": [{"type": "text", "text": answer}]}},
    ]
    transcript.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    payload = json.dumps(
        {"transcript_path": str(transcript), "stop_hook_active": False})
    proc = subprocess.run(
        [sys.executable, str(LINT)], input=payload, capture_output=True, text=True,
        env={"CLAUDE_PROJECT_DIR": str(tmp), "PATH": "/usr/bin:/bin",
             "KIPI_BLOCKED_CLAIM_LINT_MODE": mode},
        check=False)
    return proc.returncode, proc.stderr


def main() -> int:
    if not LINT.exists():
        print(f"FAIL: {LINT.name} does not exist yet (this is the RED state)")
        return 1
    mod = _load()
    cases: list[tuple[str, bool]] = []

    # === THE REPRODUCER: all six must be flagged, each as the right sub-shape ===
    for label, text, want_pattern in CLAIMS:
        found = mod.evaluate(text)
        ok = len(found) == 1 and found[0].pattern == want_pattern
        got = f"{[(f.pattern) for f in found]}"
        cases.append((f"reproducer: {label} -> {want_pattern} (got {got})", ok))

    # === THE NEGATIVE SELF-TEST: the same six, settled, must all pass ===
    for (label, _, _), settled in zip(CLAIMS, SETTLED):
        found = mod.evaluate(settled)
        cases.append((f"settled: {label} passes (got {len(found)} finding(s))",
                      found == []))

    # === escape hatches ===
    cases.append((
        "labelled inference passes ({{UNVERIFIED}})",
        mod.evaluate("- merge is blocked pending founder approval {{UNVERIFIED}}") == []))
    cases.append((
        "labelled inference passes (provenance: inferred)",
        mod.evaluate("- the 10 Alice scripts are LIVE. provenance: inferred") == []))
    cases.append((
        "an ev- claim id passes",
        mod.evaluate("- `degraded.state` does not exist (ev-a1b2c3d4e5)") == []))
    cases.append((
        "skip marker bypasses the whole answer",
        mod.evaluate(
            "- merge is blocked pending founder approval.\n"
            f"- the scripts are LIVE.\n{mod.SKIP_MARKER}") == []))

    # === it must not fire on ordinary prose ===
    cases.append((
        "prose with no state claim passes",
        mod.evaluate("- Picked the branch-protection read as the next step.") == []))
    cases.append((
        "a question is not a claim",
        mod.evaluate("- Is the merge blocked, or is that a roll-up? Checking now.") == []))

    # === fence interiors are output, not claims ===
    cases.append((
        "command output inside a fence is not itself flagged",
        mod.evaluate(
            "- codex degraded state, checked:\n\n```\n"
            "ls .prd-os/engines/codex/degraded.state\n"
            "ls: no such file or directory\n```\n") == []))

    # === a fence with a command but no output does not settle ===
    cases.append((
        "a command with no output does not settle the claim",
        len(mod.evaluate(
            "- merge is blocked pending founder approval.\n\n```\n"
            "gh api repos/o/r/branches/main/protection\n```\n")) == 1))

    # === a distant fence does not settle a claim it is not adjacent to ===
    far = ("- merge is blocked pending founder approval.\n" + ("\nfiller\n" * 12) +
           "```\ngh api repos/o/r/branches/main/protection\nnull\n```\n")
    cases.append(("a fence far from the claim does not settle it",
                  len(mod.evaluate(far)) == 1))

    # === one settled claim does not launder an unsettled one ===
    mixed = SETTLED[0] + "\n" + CLAIMS[4][1] + "\n"
    found = mod.evaluate(mixed)
    cases.append(("a settled claim does not launder an unsettled one",
                  len(found) == 1 and found[0].pattern == "my-denial-as-object-property"))

    # === PR #79 review, minor 1: a fence binds to ONE claim, not to the window ===
    # Codex reproduced this: two claims inside one lookahead window, one fence that
    # answers only the SECOND. The window rule cleared both, so evidence for the
    # Alice claim silently laundered the false merge claim next to it.
    launder = (CLAIMS[0][1] + "\n" + CLAIMS[5][1] + "\n\n```\n"
               "bash alice/run.sh --list\n"
               "alice/collect.sh: never invoked, no run-log entry\n```\n")
    found = mod.evaluate(launder)
    cases.append(("one fence settles its own claim, not the claim above it",
                  len(found) == 1 and found[0].pattern == "rollup-as-config"))

    # Two claims, two fences: each still gets settled by its own evidence.
    paired = SETTLED[0] + "\n" + SETTLED[5]
    cases.append(("two claims each carrying their own fence both pass",
                  mod.evaluate(paired) == []))

    # === PR #79 review, minor 2: the repo's own "unreachable" status wording ===
    # Not a fabricated phrase: the autonomous-board prompt tells agents to report
    # when "Linear is unreachable". That is a stop claim, and it was invisible.
    cases.append((
        "a repo-produced 'X is unreachable' claim is flagged",
        [f.pattern for f in mod.evaluate(
            "- Linear is unreachable, so the board could not be refreshed.")]
        == ["my-denial-as-object-property"]))
    cases.append((
        "'X is unreachable' settled by the probe that establishes it passes",
        mod.evaluate(
            "- Linear is unreachable, so the board could not be refreshed.\n\n```\n"
            "python3 q-system/.q-system/scripts/linear-sync.py progress ASK-317\n"
            "urllib.error.HTTPError: HTTP Error 401: Unauthorized\n```\n") == []))

    # === remediation text is per-pattern, not generic ===
    texts = {p.pattern_id: p.settles for p in mod.PATTERNS}
    cases.append(("three distinct sub-shapes are named",
                  len(mod.PATTERNS) == 3 and len(set(texts.values())) == 3))
    cases.append(("each remediation prints a runnable command",
                  all(any(line.strip().startswith(v) for line in t.splitlines()
                          for v in mod.COMMAND_VERBS)
                      for t in texts.values())))

    # === exit-code contract: advisory ships first, blocking is opt-in ===
    rc_adv, err_adv = run_hook(CLAIMS[0][1], mode="advisory")
    cases.append(("advisory mode exits 0 on a finding", rc_adv == 0))
    rc_blk, err_blk = run_hook(CLAIMS[0][1], mode="blocking")
    cases.append(("blocking mode exits 2 on a finding", rc_blk == 2))
    cases.append(("blocking stderr names the sub-shape",
                  "rollup-as-config" in err_blk))
    cases.append(("blocking stderr prints the settling command",
                  "gh api" in err_blk))
    rc_clean, _ = run_hook("- Picked the branch-protection read.", mode="blocking")
    cases.append(("clean answer exits 0 in blocking mode", rc_clean == 0))
    rc_loop, _ = run_hook_loop_guard()
    cases.append(("stop_hook_active short-circuits (no block loop)", rc_loop == 0))

    failures = 0
    for name, ok in cases:
        print(f"{'PASS' if ok else 'FAIL'}: {name}")
        failures += 0 if ok else 1
    print(f"\n{len(cases) - failures}/{len(cases)} passed")
    return 1 if failures else 0


def run_hook_loop_guard() -> tuple[int, str]:
    tmp = Path(tempfile.mkdtemp())
    transcript = tmp / "transcript.jsonl"
    transcript.write_text(json.dumps(
        {"message": {"role": "assistant",
                     "content": [{"type": "text", "text": CLAIMS[0][1]}]}}) + "\n",
        encoding="utf-8")
    payload = json.dumps(
        {"transcript_path": str(transcript), "stop_hook_active": True})
    proc = subprocess.run(
        [sys.executable, str(LINT)], input=payload, capture_output=True, text=True,
        env={"CLAUDE_PROJECT_DIR": str(tmp), "PATH": "/usr/bin:/bin",
             "KIPI_BLOCKED_CLAIM_LINT_MODE": "blocking"},
        check=False)
    return proc.returncode, proc.stderr


if __name__ == "__main__":
    sys.exit(main())
