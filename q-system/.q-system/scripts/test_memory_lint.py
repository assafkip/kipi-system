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

    if FAILURES:
        print(f"\nFAILED {len(FAILURES)}/{CHECKS}\n")
        for f in FAILURES:
            print("  " + f + "\n")
        return 1
    print(f"\nok  {CHECKS}/{CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
