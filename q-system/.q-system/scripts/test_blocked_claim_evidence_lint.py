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
import os
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
def run_hook_in_root(answer: str, mode: str = "advisory") -> tuple[int, str, Path]:
    """Same as `run_hook`, but also hands back the throwaway project root.

    The root is what the hook writes its log under, so a test that asserts the log
    needs it. `run_hook` keeps its two-value shape so the existing cases are
    untouched.
    """
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
             **({} if mode is None else {"KIPI_BLOCKED_CLAIM_LINT_MODE": mode})},
        check=False)
    return proc.returncode, proc.stderr, tmp


def run_hook(answer: str, mode: str = "advisory") -> tuple[int, str]:
    """Feed `answer` as the final assistant text through the Stop hook. -> (rc, stderr)"""
    rc, err, _ = run_hook_in_root(answer, mode)
    return rc, err


def log_rows(root: Path) -> list[dict]:
    """Every row the hook appended to its own log. [] when the file is absent."""
    log = root / "q-system" / "output" / "blocked-claim-lint.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


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

    # === PR #79 review round 2: the SAME-LINE residue of the minor-1 fix ===
    # Binding a fence to the nearest claim LINE still let one line hold two claims.
    # Codex's reproducer, verbatim: both claims on one line, one fence answering only
    # the Alice half. The merge claim rode out on the Alice claim's evidence.
    same_line = ("- Merge is blocked pending founder approval. "
                 "The 10 Alice scripts are LIVE.\n\n```\n"
                 "bash alice/run.sh --list\n"
                 "alice/collect.sh: never invoked, no run-log entry\n```\n")
    found = mod.evaluate(same_line)
    cases.append(("one fence settles one claim on a two-claim LINE",
                  len(found) == 1 and found[0].pattern == "rollup-as-config"))
    # The report must point at the sentence that is unsettled, not the whole line:
    # the operator has to see WHICH half still needs a command.
    cases.append(("the finding quotes the unsettled sentence, not the whole line",
                  bool(found) and "LIVE" not in found[0].text
                  and "blocked" in found[0].text))
    # Collection half: two claims on one line with NO evidence are two findings.
    both = mod.evaluate("- Merge is blocked pending approval. The scripts are LIVE.")
    cases.append(("two claims on one line are two findings, not one",
                  [f.pattern for f in both]
                  == ["rollup-as-config", "lookup-as-runtime-fact"]))

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

    # === ASK-1958: a blocking stop leaves a firing record ====================
    # RCA rca-fleet-sync-two-day-spin-2026-09-20, row T6. Advisory mode logged every
    # finding; the blocking branch returned 2 and wrote NOTHING. So the mode that
    # actually stops a turn was the one mode with no artifact -- exactly backwards,
    # because a block is the event worth counting. Nobody could answer "has this ever
    # blocked, and on what" from the repo.
    rc_blk, _, root_blk = run_hook_in_root(CLAIMS[0][1], mode="blocking")
    rows_blk = [r for r in log_rows(root_blk) if r.get("event") == "blocked"]
    cases.append(("blocking mode appends a firing row",
                  rc_blk == 2 and len(rows_blk) == 1))
    row = rows_blk[-1] if rows_blk else {}
    cases.append(("the firing row names the hook",
                  row.get("hook") == "blocked-claim-evidence-lint.py"))
    cases.append(("the firing row names the reason (the sub-shapes that fired)",
                  row.get("reason") == "rollup-as-config"))
    cases.append(("the firing row carries a timestamp", bool(row.get("ts"))))

    # Advisory mode still logs, and is distinguishable from a block. Losing that
    # separation would make the calibration corpus and the firing record the same
    # undifferentiated pile.
    rc_adv2, _, root_adv = run_hook_in_root(CLAIMS[0][1], mode="advisory")
    rows_adv = log_rows(root_adv)
    cases.append(("advisory mode still logs its finding",
                  rc_adv2 == 0 and len(rows_adv) == 1))
    cases.append(("an advisory row is not marked as a block",
                  bool(rows_adv) and rows_adv[0].get("event") == "advisory"))

    # NEGATIVE CONTROL. This hook runs on every turn. A row on the pass path would
    # grow an unbounded log in every instance and bury the firings it exists to show.
    _, _, root_clean = run_hook_in_root("- Picked the branch-protection read.",
                                        mode="blocking")
    cases.append(("a clean answer writes no row at all", log_rows(root_clean) == []))

    cases.extend(measured_mode_cases(mod))

    failures = 0
    for name, ok in cases:
        print(f"{'PASS' if ok else 'FAIL'}: {name}")
        failures += 0 if ok else 1
    print(f"\n{len(cases) - failures}/{len(cases)} passed")
    return 1 if failures else 0


TALLY = HERE / "test" / "fixtures" / "blocked-claim-lint-tally-2026-09-23.json"
# The labelled sentences stay OFF this public repo (PR #428 review blocker: a
# denylist scrub let a person's name and a prospect through). Point this at the
# calibrating machine's copy to run the drift and replay checks.
PRIVATE_REPLAY = os.environ.get(
    "KIPI_BLOCKED_CLAIM_REPLAY",
    str(Path.home() / ".local/state/kipi/calibration/"
        "blocked-claim-lint-replay-2026-09-23.json"))

# Real sentences from the fleet's advisory log, chosen because they name nobody.
REAL_DOES_NOT_EXIST = "That command doesn't exist."
REAL_NOTHING_WRITTEN = "Nothing was written to the tree."
REAL_BARE_BLOCKED = "PR #306 is BLOCKED."


def _strings(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)
    elif isinstance(node, str):
        yield node


def measured_mode_cases(mod) -> list[tuple[str, bool]]:
    """ASK-459: which triggers block is a MEASUREMENT, recomputed here from counts.

    This test does not trust BLOCKING_TRIGGERS: it recomputes the set from the
    labelled tally and fails when the table and the measurement disagree, so the
    blocking set only moves by re-labelling evidence.
    """
    cases: list[tuple[str, bool]] = []
    data = json.loads(TALLY.read_text(encoding="utf-8"))
    tally = data.get("tally", {})
    total = sum(v.get("labelled", 0) for v in tally.values())
    cases.append(("tally carries provenance and at least 200 labelled rows",
                  bool(data.get("provenance", {}).get("source")) and total >= 200))
    # The public file holds counts, never prose. A "text" key or a long string
    # outside the provenance block means sentences are leaking back in.
    leaked = [s for s in _strings(tally) if len(s) > 40] + \
             [k for k in _strings(data) if k in ("text", "rows_text", "sentence")]
    cases.append((f"the public tally carries no sentence text ({len(leaked)} found)",
                  not leaked))

    for p in mod.PATTERNS:
        cases.append((f"every trigger of {p.pattern_id} has an id",
                      len(mod.TRIGGER_IDS.get(p.pattern_id, ())) == len(p.triggers)))
    measured = {t for t, v in tally.items()
                if v["labelled"] >= mod.MIN_LABELLED
                and v["genuine"] / v["labelled"] >= mod.PRECISION_BAR}
    cases.append((f"BLOCKING_TRIGGERS equals the measured set (measured "
                  f"{sorted(measured)}, table {sorted(mod.BLOCKING_TRIGGERS)})",
                  measured == set(mod.BLOCKING_TRIGGERS) and bool(measured)))

    # Shadowing (PR #428 review): a precise claim next to a bare "blocked" blocks.
    both = mod.evaluate(
        "The commit is blocked because the config it reads does not exist.")
    cases.append(("a 'does not exist' claim is not shadowed by 'blocked' beside it",
                  [f.trigger for f in both] == ["does-not-exist"]
                  and bool(mod.blocking_findings(both, "measured"))))

    cases.extend(_private_replay_cases(mod))

    # The real hook path.
    rc, err, root = run_hook_in_root(REAL_DOES_NOT_EXIST, mode="measured")
    fired = [f for row in log_rows(root) for f in row.get("findings", [])]
    cases.append(("measured hook exits 2 on a real unsettled 'does not exist' claim",
                  rc == 2 and "lookup-as-runtime-fact" in err))
    cases.append(("the firing row records the trigger and that it blocked",
                  any(f.get("trigger") == "does-not-exist" and f.get("blocking")
                      for f in fired)))
    rc, _, _ = run_hook_in_root(REAL_NOTHING_WRITTEN, mode="measured")
    cases.append(("measured hook exits 2 on a real 'nothing was written' claim",
                  rc == 2))
    rc, _, root = run_hook_in_root(REAL_BARE_BLOCKED, mode="measured")
    rows_adv = log_rows(root)
    cases.append(("measured hook exits 0 on a bare-'blocked' claim and logs it advisory",
                  rc == 0 and [r.get("event") for r in rows_adv] == ["advisory"]))

    # The switch ships WITH THE SCRIPT: with no mode in the environment the hook runs
    # measured. The RCA's promotion lived in one settings file and never reached the
    # fleet; a default in code cannot be stranded that way.
    rc, _, _ = run_hook_in_root(REAL_DOES_NOT_EXIST, mode=None)
    cases.append(("with no mode in the environment the hook runs measured (exit 2)",
                  rc == 2))
    # A caller's exported mode wins, which is how the one-shot reviewer opts out.
    rc, _, _ = run_hook_in_root(REAL_DOES_NOT_EXIST, mode="advisory")
    cases.append(("an exported advisory mode still wins (exit 0)", rc == 0))
    agent = (HERE / "pr-review-agent.sh").read_text()
    cases.append(("pr-review-agent.sh runs its claude reviewer with the lint advisory",
                  "claude) KIPI_BLOCKED_CLAIM_LINT_MODE=advisory run_bounded" in agent))
    return cases


def _private_replay_cases(mod) -> list[tuple[str, bool]]:
    """Drift + replay against the labelled rows, where they exist (never in CI)."""
    path = Path(PRIVATE_REPLAY)
    if not path.exists():
        print(f"NOTE: labelled replay rows absent ({path}); drift and replay "
              "checks not run on this machine. The tally checks above still ran.")
        return []
    rows = json.loads(path.read_text(encoding="utf-8")).get("rows", [])
    cases = [("private replay has at least 200 rows", len(rows) >= 200)]
    drifted = [r["text"][:60] for r in rows
               if [f.trigger for f in mod.evaluate(r["text"])][:1] != [r["trigger"]]]
    cases.append((f"every labelled row still fires its labelled trigger "
                  f"({len(drifted)} drifted)", not drifted))
    counts: dict[str, list[int]] = {}
    for r in rows:
        g_n = counts.setdefault(r["trigger"], [0, 0])
        g_n[0] += bool(r["genuine"])
        g_n[1] += 1
    tally = json.loads(TALLY.read_text(encoding="utf-8"))["tally"]
    cases.append(("the public tally matches the labelled rows",
                  {t: [v["genuine"], v["labelled"]] for t, v in tally.items()} == counts))
    wrong_pass = [r for r in rows if r["genuine"] and r["trigger"] in mod.BLOCKING_TRIGGERS
                  and not mod.blocking_findings(mod.evaluate(r["text"]), "measured")]
    cases.append((f"replay: every genuine row on a blocking trigger blocks "
                  f"({len(wrong_pass)} passed)", not wrong_pass))
    wrong_block = [r for r in rows if r["trigger"] not in mod.BLOCKING_TRIGGERS
                   and mod.blocking_findings(mod.evaluate(r["text"]), "measured")]
    cases.append((f"replay: no row on an advisory trigger blocks "
                  f"({len(wrong_block)} blocked)", not wrong_block))
    return cases


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
