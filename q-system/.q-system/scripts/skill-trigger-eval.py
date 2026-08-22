#!/usr/bin/env python3
"""Skill-trigger eval harness (H1). Measures whether kipi's auto-invoked skills
actually FIRE for prompts that should trigger them -- the gap deterministic
lint hooks cannot see (they check OUTPUT after the model already chose to act).

On-demand ONLY: shells `claude -p` (real Opus cost). NOT a hook. ADVISORY: the
live trigger_rate is noisy because skill auto-invocation is a model decision; it
is a signal, never a pass/fail gate. Run it periodically, not in CI.

Usage:  skill-trigger-eval.py [<skill> ...]   (no args = every fixture)
Fixtures: q-system/.q-system/skill-evals/<skill>.json  (override dir: SKILL_EVAL_DIR)
Claude command override (for testing): SKILL_EVAL_CLAUDE_CMD. stdlib only.
"""
import glob
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL_DIR = os.environ.get("SKILL_EVAL_DIR", os.path.join(HERE, "..", "skill-evals"))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
CLAUDE = os.environ.get("SKILL_EVAL_CLAUDE_CMD", "claude")


def markers(value, where):
    """Normalize a `fired_marker` into a list of lowercased literals (any-of).

    WHY the '|' refusal (ASK-135, Codex PR #238): a rule that names several
    skills wants alternation, and the obvious way to write it -- "a|b|c" -- is
    NOT alternation here. `fired` is a literal substring test, so that string
    matches no output ever and every correct invocation scores as a miss. The
    eval then reports a confident 0.00 forever, which is worse than no eval.
    A list is the supported way to say any-of; the pipe form is refused at load
    rather than silently mismeasured for months.
    """
    values = value if isinstance(value, list) else [value]
    if not values:
        raise ValueError(where + ": 'fired_marker' list is empty. any([]) is "
                         "False, so every case would score as 'did not fire'.")
    out = []
    for v in values:
        if not isinstance(v, str) or not v.strip():
            raise ValueError(where + ": each 'fired_marker' must be a non-empty string")
        if "|" in v:
            raise ValueError(
                where + ": 'fired_marker' " + repr(v) + " contains '|'. Matching "
                "is a literal substring test, not a regex, so this matches "
                'nothing. Use a list instead: ["a", "b"].')
        out.append(v.strip().lower())
    return out


def load_fixture(skill):
    with open(os.path.join(EVAL_DIR, skill + ".json")) as f:
        fx = json.load(f)
    if not isinstance(fx, dict) or "skill" not in fx or not isinstance(fx.get("cases"), list) or not fx["cases"]:
        raise ValueError(skill + ".json: needs 'skill' and a non-empty 'cases' list")
    fx["_markers"] = markers(fx.get("fired_marker", fx["skill"]), skill + ".json")
    for i, c in enumerate(fx["cases"]):
        if not isinstance(c, dict) or "prompt" not in c or "should_trigger" not in c:
            raise ValueError(skill + ".json: each case needs 'prompt' and 'should_trigger'")
        # A per-case marker NARROWS the fixture-level any-of set: for a rule
        # naming six skills, "something fired" is not the measurement we want --
        # firing the wrong one of the six is a miss, not a hit.
        c["_markers"] = (markers(c["fired_marker"], skill + ".json case " + str(i))
                         if "fired_marker" in c else fx["_markers"])
    return fx


def run_case(prompt):
    # Run claude -p from the REPO ROOT so the .claude/rules auto-invoke path loads.
    try:
        r = subprocess.run([CLAUDE, "-p", prompt], cwd=REPO_ROOT,
                           capture_output=True, text=True, timeout=180)
        return r.stdout or ""
    except Exception:
        return ""


def eval_skill(skill):
    fx = load_fixture(skill)
    correct = 0
    for c in fx["cases"]:
        out = run_case(c["prompt"]).lower()
        fired = any(m in out for m in c["_markers"])
        if fired == bool(c["should_trigger"]):
            correct += 1
    return {"skill": skill, "cases": len(fx["cases"]), "trigger_rate": correct / len(fx["cases"])}


def claude_runnable():
    # Distinguish "claude binary missing/broken" from "claude ran but the skill did not fire".
    if os.sep in CLAUDE or CLAUDE.startswith("."):
        return os.access(CLAUDE, os.X_OK)
    return shutil.which(CLAUDE) is not None


def main():
    skills = sys.argv[1:] or sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(EVAL_DIR, "*.json")))
    if not skills:
        sys.stderr.write("no fixtures in " + EVAL_DIR + "\n")
        sys.exit(1)
    if not claude_runnable():
        sys.stderr.write("error: claude command not runnable: " + CLAUDE + " (set SKILL_EVAL_CLAUDE_CMD). Refusing to report a misleading trigger_rate.\n")
        sys.exit(3)
    try:
        results = [eval_skill(s) for s in skills]
    except (ValueError, FileNotFoundError) as e:
        sys.stderr.write("fixture error: " + str(e) + "\n")
        sys.exit(2)
    for r in results:
        print("{:32} trigger_rate={:.2f} ({} cases)".format(r["skill"], r["trigger_rate"], r["cases"]))
    avg = sum(r["trigger_rate"] for r in results) / len(results)
    print("\nADVISORY: mean trigger_rate {:.2f}. Noisy (auto-invoke is a model decision); not a pass/fail gate.".format(avg))


if __name__ == "__main__":
    main()
