#!/usr/bin/env python3
"""Self-test for memory-lint.py.

Test isolation (fable-discipline): every fixture is built inside a
TemporaryDirectory. Nothing here reads or writes the real auto-memory dir, and
`--today` is passed on every run so the stale case is pinned to a fixed date and
cannot rot into a false green next February.

The shape that matters: a CLEAN fixture must report zero, and each defect class
gets its own fixture that injects exactly ONE defect into that same clean base.
Asserting only against a fixture carrying all seven defects at once would let a
check that never fires hide behind the six that do.

Run: python3 q-system/.q-system/scripts/test_memory_lint.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINT = HERE / "memory-lint.py"

TODAY = "2026-08-19"          # fixed clock for every run
FRESH = "2026-08-01"          # inside the 6-month window
ANCIENT = "2026-01-05"        # outside it

SECTIONS = (
    "DANGLING WIKI LINKS",
    "DANGLING SUPERSESSION LINKS",
    "INDEX MISMATCH",
    "DUPLICATE NAME SLUGS",
    "STALE",
    "MISSING as_of / status",
)

FAILURES: list[str] = []
CHECKS = 0


def memory(name, *, status="current", as_of=FRESH, body="body text\n", **extra):
    lines = ["---", f"name: {name}", "description: a fixture memory",
             "metadata:", "  type: project"]
    if status is not None:
        lines.append(f"status: {status}")
    if as_of is not None:
        lines.append(f"as_of: {as_of}")
    for key, value in extra.items():
        lines.append(f"{key}: {value}")
    lines += ["---", "", body]
    return "\n".join(lines)


def build_clean(root: Path):
    """Three memories, fully linked and indexed. Zero findings expected.

    gamma-old is deliberately superseded AND ancient: it proves the stale check
    skips a memory that has already been corrected, rather than nagging forever
    about a claim someone already replaced.
    """
    files = {
        "alpha.md": memory("alpha", body="see [[beta]] for the successor\n"),
        "beta.md": memory("beta", supersedes="gamma-old"),
        "gamma-old.md": memory("gamma-old", status="superseded",
                               as_of=ANCIENT, superseded_by="beta"),
    }
    index = ["# Memory Index", ""]
    index += [f"- [{n[:-3]}]({n}) - hook" for n in files]
    files["MEMORY.md"] = "\n".join(index) + "\n"
    for name, text in files.items():
        (root / name).write_text(text)


def run_lint(root: Path, *extra):
    proc = subprocess.run(
        [sys.executable, str(LINT), str(root), "--today", TODAY, *extra],
        capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def sections_present(output: str):
    return {s for s in SECTIONS if f"\n{s}" in output}


def check(label, condition, detail=""):
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"[PASS] {label}")
    else:
        print(f"[FAIL] {label}")
        FAILURES.append(f"{label}\n{detail}")


def case(label, mutate, want_section, want_fragment):
    """Clean base + exactly one injected defect -> exactly one section fires."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_clean(root)
        mutate(root)
        rc, out = run_lint(root)
        got = sections_present(out)
        check(f"{label}: reports {want_section} and nothing else",
              got == {want_section}, f"    got sections: {sorted(got)}\n{out}")
        check(f"{label}: names the offender",
              want_fragment in out, f"    wanted fragment: {want_fragment}\n{out}")
        check(f"{label}: advisory mode still exits 0", rc == 0, out)


# --- the injectors ----------------------------------------------------------

def inject_dangling_link(root):
    (root / "alpha.md").write_text(
        memory("alpha", body="see [[no-such-memory]] instead\n"))


def inject_dangling_supersede(root):
    (root / "gamma-old.md").write_text(
        memory("gamma-old", status="superseded", as_of=ANCIENT,
               superseded_by="ghost-memory"))


def inject_orphan_index_line(root):
    path = root / "MEMORY.md"
    path.write_text(path.read_text() + "- [Ghost](deleted-memory.md) - hook\n")


def inject_unindexed_file(root):
    (root / "delta.md").write_text(memory("delta"))


def inject_dup_slug(root):
    (root / "alpha-copy.md").write_text(memory("alpha"))
    path = root / "MEMORY.md"
    path.write_text(path.read_text() + "- [Alpha copy](alpha-copy.md) - hook\n")


def inject_stale_current(root):
    (root / "stale.md").write_text(memory("stale", as_of=ANCIENT))
    path = root / "MEMORY.md"
    path.write_text(path.read_text() + "- [Stale](stale.md) - hook\n")


def inject_grandfathered(root):
    (root / "bare.md").write_text(memory("bare", status=None, as_of=None))
    path = root / "MEMORY.md"
    path.write_text(path.read_text() + "- [Bare](bare.md) - hook\n")


# --- where the corpus lives -------------------------------------------------

# AN OBSERVED PAIR, not a restatement of the derivation under test: a project
# path this machine ran a session in, beside the transcript directory Claude
# Code itself reported for that session. Deriving the expectation from
# `claude_project_slug` would assert the function equals itself, and the point
# of ASK-1903 is that the old derivation was internally consistent and still
# named a directory the producer never creates.
#
# Read live from this worktree's own SessionStart hook output, which wrote to
# .../projects/-Users-assafkipnis--config-kipi-worktrees-ask-1903/ while
# CLAUDE_PROJECT_DIR was /Users/assafkipnis/.config/kipi/worktrees/ask-1903.
# The double hyphen is the whole finding: the dot in `.config` is a separator.
#
# The second pair is the underscore half of the same character class, in a
# GENERIC path. The producer observation behind it is a client instance whose
# corpus the PR #458 reviewer swept at the hyphenated slug; this repo is public,
# so the engagement is not named here. The real pair above is what anchors the
# class to the producer; this one pins that `_` is in it.
OBSERVED_SLUGS = (
    ("/Users/assafkipnis/.config/kipi/worktrees/ask-1903",
     "-Users-assafkipnis--config-kipi-worktrees-ask-1903"),
    ("/Users/assafkipnis/projects/consulting/projects/An_Example_Co",
     "-Users-assafkipnis-projects-consulting-projects-An-Example-Co"),
)


def check_slug_derivation():
    """ASK-1903: the corpus path memory-lint picks must be the one that exists.

    Gate 1.2b reports "no auto-memory directory at <path>" as a PASS. A
    derivation that disagrees with the producer makes that PASS a false
    statement about the filesystem, and hides every finding in the corpus that
    does exist -- three live structural findings when this was measured.
    """
    sys.path.insert(0, str(HERE))
    import memory_conventions

    for project_dir, expected in OBSERVED_SLUGS:
        got = memory_conventions.claude_project_slug(project_dir)
        check("slug for %s" % project_dir, got == expected,
              "expected %s\n     got %s" % (expected, got))

    # The mutant killer for the decision point above. A derivation that mapped
    # every character to '-' (or that lower-cased, or collapsed runs) would pass
    # the two pairs above and still miss the corpus for an ordinary path.
    plain = "/Users/x/projects/demo"
    check("an alphanumeric path is untouched apart from the separators",
          memory_conventions.claude_project_slug(plain) == "-Users-x-projects-demo",
          memory_conventions.claude_project_slug(plain))

    plain_dir = memory_conventions.claude_project_memory_dir(plain)
    check("the memory dir is the slug plus /memory",
          plain_dir.name == "memory" and plain_dir.parent.name == "-Users-x-projects-demo",
          str(plain_dir))


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True)


def check_worktree_corpus():
    """ASK-1903 round 3: a linked worktree reads the MAIN worktree's corpus.

    Claude Code keys the TRANSCRIPT directory on the session's cwd and the
    auto-memory corpus on the repository's MAIN worktree. OBSERVED_SLUGS[0]
    above is a transcript observation, and round 2 used it as the oracle for the
    corpus -- so every git worktree in the fleet derived a directory the producer
    never creates, and Gate 1.2b turned that into a green
    `PASS no auto-memory directory`.

    The producer observation behind this check, read live in the session that
    wrote it: cwd was /Users/assafkipnis/.config/kipi/worktrees/ask-1903, the
    transcript directory was .../-Users-assafkipnis--config-kipi-worktrees-ask-1903
    and held no memory/, and the corpus the session actually used was
    .../-Users-assafkipnis-projects-kipi-system/memory -- the slug of
    /Users/assafkipnis/projects/kipi-system, which is that worktree's MAIN
    worktree, not its cwd.

    Built as a real git worktree in a TemporaryDirectory so the check can go RED
    on any machine rather than asserting against this one.
    """
    sys.path.insert(0, str(HERE))
    import memory_conventions

    if shutil.which("git") is None:
        check("worktree corpus: git on PATH", False, "git not found; case unverified")
        return

    with tempfile.TemporaryDirectory() as tmp:
        main = Path(tmp) / "main_repo"
        main.mkdir()
        git(main, "init", "-q")
        git(main, "config", "user.email", "t@example.com")
        git(main, "config", "user.name", "t")
        git(main, "commit", "-q", "--allow-empty", "-m", "base")
        linked = Path(tmp) / "wt-side-branch"
        made = git(main, "worktree", "add", "-q", str(linked), "-b", "side")
        if made.returncode != 0 or not linked.is_dir():
            check("worktree corpus: fixture worktree was created", False,
                  made.stdout + made.stderr)
            return

        # `main.resolve()`: on macOS a TemporaryDirectory lives under a symlinked
        # /var, and git answers with the resolved path. Real fleet paths carry no
        # symlink, so this is fixture hygiene, not a claim about the derivation.
        want = memory_conventions.claude_project_memory_dir(str(main.resolve()))
        got = memory_conventions.claude_project_memory_dir(str(linked))
        check("a linked worktree resolves to the main worktree's corpus",
              got == want, "expected %s\n     got %s" % (want, got))
        # The literal half: an implementation that returned the same WRONG answer
        # for both sides would satisfy the equality above.
        check("the corpus slug names the main worktree, not the linked one",
              "main-repo" in got.parent.name and "wt-side-branch" not in got.parent.name,
              str(got))

        # A path outside any repository keeps answering for itself, so the
        # resolution is additive rather than a rewrite of every derivation.
        outside = Path(tmp) / "not-a-repo"
        outside.mkdir()
        got_outside = memory_conventions.claude_project_memory_dir(str(outside))
        check("a non-repo path still derives from itself",
              got_outside.parent.name.endswith("not-a-repo"), str(got_outside))


def main():
    # --- GREEN: the clean fixture ------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_clean(root)
        rc, out = run_lint(root)
        check("clean fixture: no sections at all", sections_present(out) == set(), out)
        check("clean fixture: summary reads 0/0",
              "structural: 0   advisory: 0" in out, out)
        check("clean fixture: exits 0", rc == 0, out)
        rc_strict, out_strict = run_lint(root, "--strict")
        check("clean fixture: --strict exits 0", rc_strict == 0, out_strict)

    # --- RED: one defect class per fixture ---------------------------------
    case("dangling wiki link", inject_dangling_link,
         "DANGLING WIKI LINKS", "[[no-such-memory]] resolves to no memory")
    case("dangling superseded_by", inject_dangling_supersede,
         "DANGLING SUPERSESSION LINKS", "superseded_by: ghost-memory resolves to no memory")
    case("index line with no backing file", inject_orphan_index_line,
         "INDEX MISMATCH", "points at deleted-memory.md, which does not exist")
    case("memory file with no index line", inject_unindexed_file,
         "INDEX MISMATCH", "delta.md has no line in MEMORY.md")
    case("duplicate name slug", inject_dup_slug,
         "DUPLICATE NAME SLUGS", "duplicate name slug 'alpha'")
    case("stale status:current", inject_stale_current,
         "STALE", "status current but as_of 2026-01-05 is older than 6 months")
    case("grandfathered file", inject_grandfathered,
         "MISSING as_of / status", "bare.md: no status and no as_of")

    # --- the strict-mode contract ------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_clean(root)
        inject_dangling_link(root)
        rc, out = run_lint(root, "--strict")
        check("--strict exits 1 on a structural finding", rc == 1, out)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_clean(root)
        inject_grandfathered(root)
        inject_stale_current(root)
        rc, out = run_lint(root, "--strict")
        check("--strict still exits 0 on advisory-only findings", rc == 0, out)
        check("advisory-only run counts 0 structural",
              "structural: 0   advisory: 2" in out, out)

    # --- the age flag actually moves the cutoff ----------------------------
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_clean(root)
        _, out_default = run_lint(root)
        check("FRESH memory is not stale at the 6-month default",
              "STALE" not in out_default, out_default)
        _, out_tight = run_lint(root, "--max-age-months", "0")
        check("same corpus goes stale at --max-age-months 0",
              "alpha.md: status current but as_of" in out_tight, out_tight)

    # --- degenerate inputs --------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        rc, out = run_lint(Path(tmp) / "not-there")
        check("missing directory: says so and exits 0",
              rc == 0 and "nothing to sweep" in out, out)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rc, out = run_lint(root)
        check("empty directory: reports the missing index, exits 0",
              rc == 0 and "MEMORY.md is missing" in out, out)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_clean(root)
        (root / "no-frontmatter.md").write_text("just a body, no frontmatter\n")
        path = root / "MEMORY.md"
        path.write_text(path.read_text() + "- [Nofm](no-frontmatter.md) - hook\n")
        rc, out = run_lint(root)
        check("file with no frontmatter is advisory, never a crash",
              rc == 0 and "no-frontmatter.md: no status and no as_of" in out, out)

    check_slug_derivation()
    check_worktree_corpus()

    if FAILURES:
        print(f"\nFAILED {len(FAILURES)}/{CHECKS}\n")
        for f in FAILURES:
            print("  " + f + "\n")
        return 1
    print(f"\nok  {CHECKS}/{CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
