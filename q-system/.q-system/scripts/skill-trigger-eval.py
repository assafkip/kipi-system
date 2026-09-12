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


class InfraError(RuntimeError):
    """The measurement could not be taken. Distinct from "the skill did not fire"."""


def run_case(prompt):
    """Model output for one prompt. Raises InfraError when the call did not happen.

    WHY the rc check (ASK-135, Codex PR #238 round 3): this used to be
    `r.stdout or ""` inside a bare `except Exception: return ""`, so a claude
    that exited nonzero on every call was indistinguishable from a claude that
    ran fine and declined to invoke the skill. Point the harness at a binary
    that always fails and it credited every should_trigger=false case and
    published trigger_rate=0.38 -- a total infrastructure failure wearing the
    shape of a model-quality measurement. `claude_runnable()` cannot catch this:
    an expired credential, a rate limit or /usr/bin/false all pass an X_OK test.
    An empty stdout with rc 0 stays a real result ("did not fire"); only a
    failed invocation is refused.
    """
    # Run claude -p from the REPO ROOT so the .claude/rules auto-invoke path loads.
    # stream-json is what exposes the tool calls; the prompt stays at argv[2].
    try:
        r = subprocess.run([CLAUDE, "-p", prompt, "--output-format", "stream-json",
                            "--verbose"], cwd=REPO_ROOT,
                           capture_output=True, text=True, timeout=180)
    except Exception as e:
        raise InfraError("`" + CLAUDE + " -p` could not be run: " + repr(e))
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        raise InfraError("`" + CLAUDE + " -p` exited " + str(r.returncode)
                         + (": " + tail[-1] if tail else " with no output"))
    return r.stdout or ""


def stream_events(out):
    """The JSON events of one stream-json run. Raises InfraError on zero events:
    a successful run always emits at least its result event, so an empty or
    non-JSON stdout means the invocations were not observable, not that no
    skill fired."""
    events = []
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type"):
            events.append(ev)
    if not events:
        raise InfraError("`" + CLAUDE + " -p` exited 0 but emitted no stream-json "
                         "events, so no tool call could be observed")
    return events


def invoked_skills(events):
    """Skill names the run actually loaded, lowercased.

    WHY tool calls and not text (ASK-135, Codex PR #238 round 4): the old test
    was `marker in stdout`, so "I did not invoke skill-creator." scored as an
    invocation and the eval could report 1.00 for work that never happened.
    Two tool calls count: a Skill call (its `skill` input, plugin namespace
    stripped) and a Read of `<skill>/SKILL.md`, the load path the
    fable-discipline fixture relies on.
    """
    names = set()
    for ev in events:
        content = (ev.get("message") or {}).get("content") if ev.get("type") == "assistant" else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            args = block.get("input") or {}
            if block.get("name") == "Skill" and isinstance(args.get("skill"), str):
                names.add(args["skill"].strip().lower().split(":")[-1])
            path = str(args.get("file_path", "")).replace("\\", "/")
            if block.get("name") == "Read" and path.lower().endswith("/skill.md"):
                names.add(path.rsplit("/", 2)[-2].lower())
    return names


def eval_skill(skill):
    fx = load_fixture(skill)
    correct = 0
    for i, c in enumerate(fx["cases"]):
        try:
            invoked = invoked_skills(stream_events(run_case(c["prompt"])))
        except InfraError as e:
            raise InfraError(skill + " case " + str(i) + ": " + str(e))
        fired = any(m in invoked for m in c["_markers"])
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
    except InfraError as e:
        # Same posture as the claude_runnable() refusal above and for the same
        # reason: a rate computed from calls that never happened is worse than
        # no rate, because it looks like a measurement of the model.
        sys.stderr.write("error: " + str(e) + ". Refusing to report a "
                         "trigger_rate from calls that did not complete.\n")
        sys.exit(3)
    for r in results:
        print("{:32} trigger_rate={:.2f} ({} cases)".format(r["skill"], r["trigger_rate"], r["cases"]))
    avg = sum(r["trigger_rate"] for r in results) / len(results)
    print("\nADVISORY: mean trigger_rate {:.2f}. Noisy (auto-invoke is a model decision); not a pass/fail gate.".format(avg))


if __name__ == "__main__":
    main()
