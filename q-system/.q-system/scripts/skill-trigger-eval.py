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

Paths-scoped rules (ASK-1242): a rule with a `paths:` frontmatter loads only
when a matching file is touched, and a bare `claude -p` touches none. A fixture
governed by such a rule (the rule file is `<skill>.md`, or its body names
`skill-evals/<skill>.json`) must declare `seed_path`, a repo-relative file that
matches one of the rule's globs. The harness then runs that fixture in a temp
copy of the tracked tree with the file created, and names it in every prompt.
Without it the fixture is REFUSED before any claude call. Project root override
(for testing): SKILL_EVAL_REPO_ROOT.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL_DIR = os.environ.get("SKILL_EVAL_DIR", os.path.join(HERE, "..", "skill-evals"))
REPO_ROOT = os.path.abspath(os.environ.get("SKILL_EVAL_REPO_ROOT") or os.path.join(HERE, "..", "..", ".."))
CLAUDE = os.environ.get("SKILL_EVAL_CLAUDE_CMD", "claude")
# A rule scoped to every path is always-on (concurrent-session-worktrees.md measured
# this when "**/*" tripped the instruction-budget ratchet), so it needs no seed.
ALWAYS_ON_GLOBS = {"**", "**/*"}


def load_fixture(skill):
    with open(os.path.join(EVAL_DIR, skill + ".json")) as f:
        fx = json.load(f)
    if not isinstance(fx, dict) or "skill" not in fx or not isinstance(fx.get("cases"), list) or not fx["cases"]:
        raise ValueError(skill + ".json: needs 'skill' and a non-empty 'cases' list")
    for c in fx["cases"]:
        if not isinstance(c, dict) or "prompt" not in c or "should_trigger" not in c:
            raise ValueError(skill + ".json: each case needs 'prompt' and 'should_trigger'")
    seed = fx.get("seed_path")
    if seed is not None and (not isinstance(seed, str) or os.path.isabs(seed) or ".." in seed.split("/")):
        raise ValueError(skill + ".json: seed_path must be a repo-relative path inside the repo")
    return fx


def rule_paths(text):
    """The `paths:` globs from a rule's frontmatter; [] when it has none.
    Handles the three shapes the rules dir uses: a `- "glob"` list, an inline
    scalar, and an inline [a, b] list."""
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return []
    lines = m.group(1).split("\n")
    for i, line in enumerate(lines):
        if line.startswith("paths:"):
            return _paths_value(line[len("paths:"):].strip(), lines[i + 1:])
    return []


def _paths_value(inline, rest):
    if inline:
        return [g.strip().strip("'\"") for g in inline.strip("[]").split(",") if g.strip()]
    globs = []
    for line in rest:
        item = re.match(r"\s+-\s+(.+)", line)
        if not item:
            break
        globs.append(item.group(1).strip().strip("'\""))
    return globs


def glob_regex(pattern):
    """Gitignore-style: `**/` is zero or more directories, `*` stays in one segment."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] in "*?":
            out, i = out + ("[^/]*" if pattern[i] == "*" else "[^/]"), i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def matches_any(path, globs):
    return any(glob_regex(g).match(path) for g in globs)


def scoped_rules(skill):
    """Every paths-scoped rule that governs this fixture, derived from the rule
    files themselves at run time, never restated in the fixture."""
    found = []
    for path in sorted(glob.glob(os.path.join(REPO_ROOT, ".claude", "rules", "*.md"))):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        governs = os.path.basename(path) == skill + ".md" or ("skill-evals/" + skill + ".json") in text
        globs = rule_paths(text)
        if governs and globs and not ALWAYS_ON_GLOBS.intersection(globs):
            found.append((os.path.relpath(path, REPO_ROOT), globs))
    return found


def prompt_names_match(prompt, globs):
    tokens = re.findall(r"[\w./-]+", prompt)
    return any(matches_any(t.strip("./"), globs) for t in tokens if "/" in t or "." in t)


def check_scoped(fx):
    """Refuse a fixture whose paths-scoped rule could not load in the eval.
    Raises ValueError, which main() turns into exit 2 before any claude call."""
    seed = fx.get("seed_path")
    for rel, globs in scoped_rules(fx["skill"]):
        where = rel + " is paths-scoped (paths: " + ", ".join(globs) + ")"
        if seed is not None and not matches_any(seed, globs):
            raise ValueError(fx["skill"] + ".json: seed_path " + seed + " matches none of the globs; " + where)
        if seed is not None:
            continue
        for n, c in enumerate(fx["cases"], 1):
            if not prompt_names_match(c["prompt"], globs):
                raise ValueError(fx["skill"] + ".json: " + where + " and case " + str(n)
                                 + " names no matching path, so the rule would not load and the rate would"
                                 + " measure the un-ruled model. Add a seed_path matching one of those globs.")


def copy_tracked_tree(dest):
    """The session runs in a copy, so the seed never lands in the live checkout."""
    ls = subprocess.run(["git", "-C", REPO_ROOT, "ls-files", "-z"], capture_output=True, text=True, check=True)
    for rel in filter(None, ls.stdout.split("\0")):
        src = os.path.join(REPO_ROOT, rel)
        if not os.path.lexists(src):
            continue
        os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
        shutil.copy2(src, os.path.join(dest, rel), follow_symlinks=False)


def seeded_workdir(tmp, seed):
    copy_tracked_tree(tmp)
    target = os.path.join(tmp, seed)
    os.makedirs(os.path.dirname(target) or tmp, exist_ok=True)
    if not os.path.exists(target):
        with open(target, "w", encoding="utf-8") as f:
            f.write("# seeded by skill-trigger-eval.py so a paths-scoped rule matching this path loads\n")
    return tmp


def run_case(prompt, cwd):
    # Run claude -p from the project root (or its seeded copy) so the .claude/rules auto-invoke path loads.
    try:
        r = subprocess.run([CLAUDE, "-p", prompt], cwd=cwd,
                           capture_output=True, text=True, timeout=180)
        return r.stdout or ""
    except Exception:
        return ""


def score(fx, cwd):
    marker = str(fx.get("fired_marker", fx["skill"])).lower()
    seed = fx.get("seed_path")
    correct = 0
    for c in fx["cases"]:
        prompt = c["prompt"] + ("\n\nThe file in question is " + seed + "." if seed else "")
        fired = marker in run_case(prompt, cwd).lower()
        if fired == bool(c["should_trigger"]):
            correct += 1
    return {"skill": fx["skill"], "cases": len(fx["cases"]), "trigger_rate": correct / len(fx["cases"])}


def eval_skill(fx):
    if not fx.get("seed_path"):
        return score(fx, REPO_ROOT)
    with tempfile.TemporaryDirectory(prefix="skill-eval-") as tmp:
        return score(fx, seeded_workdir(tmp, fx["seed_path"]))


def claude_runnable():
    # Distinguish "claude binary missing/broken" from "claude ran but the skill did not fire".
    if os.sep in CLAUDE or CLAUDE.startswith("."):
        return os.access(CLAUDE, os.X_OK)
    return shutil.which(CLAUDE) is not None


def load_all(skills):
    # Load and check all fixtures first, then call claude: a refusal after real spend
    # on the fixtures sorted ahead of it is wasted money. Case 6 of
    # test/test-skill-trigger-eval.sh counts the claude calls a refusal makes (zero).
    fixtures = [load_fixture(s) for s in skills]
    for fx in fixtures:
        check_scoped(fx)
    return fixtures


def main():
    skills = sys.argv[1:] or sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(EVAL_DIR, "*.json")))
    if not skills:
        sys.stderr.write("no fixtures in " + EVAL_DIR + "\n")
        sys.exit(1)
    if not claude_runnable():
        sys.stderr.write("error: claude command not runnable: " + CLAUDE + " (set SKILL_EVAL_CLAUDE_CMD). Refusing to report a misleading trigger_rate.\n")
        sys.exit(3)
    try:
        results = [eval_skill(fx) for fx in load_all(skills)]
    except (ValueError, FileNotFoundError) as e:
        sys.stderr.write("fixture error: " + str(e) + "\n")
        sys.exit(2)
    for r in results:
        print("{:32} trigger_rate={:.2f} ({} cases)".format(r["skill"], r["trigger_rate"], r["cases"]))
    avg = sum(r["trigger_rate"] for r in results) / len(results)
    print("\nADVISORY: mean trigger_rate {:.2f}. Noisy (auto-invoke is a model decision); not a pass/fail gate.".format(avg))


if __name__ == "__main__":
    main()
