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
sys.path.insert(0, HERE)
import fleet_door  # noqa: E402  (ASK-4311: who pays for each case)


def load_fixture(skill):
    with open(os.path.join(EVAL_DIR, skill + ".json")) as f:
        fx = json.load(f)
    if not isinstance(fx, dict) or "skill" not in fx or not isinstance(fx.get("cases"), list) or not fx["cases"]:
        raise ValueError(skill + ".json: needs 'skill' and a non-empty 'cases' list")
    for c in fx["cases"]:
        if not isinstance(c, dict) or "prompt" not in c or "should_trigger" not in c:
            raise ValueError(skill + ".json: each case needs 'prompt' and 'should_trigger'")
    return fx


def _routed_model(job="on-demand"):
    """The routing table's model for an on-demand run (ASK-4013): no fleet call
    rides the CLI default."""
    import importlib.util as _u
    spec = _u.spec_from_file_location("model_route", os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_route.py"))
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.pick(job)


#: An on-demand eval with no launchd job: it runs inside whichever session
#: started it. So each call FOLLOWS ITS CALLER (ASK-4311): a fleet run bills a
#: fleet API key through the metered door, the founder's own session stays on his
#: plan with any inherited key stripped, exactly as before.
DOOR_ACTOR = "skill-trigger-eval"


def run_case(prompt):
    # Run claude -p from the REPO ROOT so the .claude/rules auto-invoke path loads.
    try:
        r = fleet_door.run_for_caller([CLAUDE, "-p", prompt, "--model", _routed_model()], actor=DOOR_ACTOR,
                                      cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
        return r.stdout or ""
    except Exception:
        return ""


def eval_skill(skill):
    fx = load_fixture(skill)
    marker = str(fx.get("fired_marker", fx["skill"])).lower()
    correct = 0
    for c in fx["cases"]:
        fired = marker in run_case(c["prompt"]).lower()
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
