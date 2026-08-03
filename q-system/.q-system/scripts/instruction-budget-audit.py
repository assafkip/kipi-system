#!/usr/bin/env python3
"""Audit always-on instruction token budget.

Single budget: CLAUDE.md (with imports) + effectively-always-on rules < 300 lines.

IMPORTANT: Rules with paths: ["**/*"] are functionally always-on because **/*
matches every file Claude will ever read. The script must count these as always-on,
not conditional. A naive has_paths_frontmatter() check would misclassify them.

Exits non-zero if budget exceeded.

--ratchet (the commit-time mode, wired in lefthook.yml pre-commit): the 300-line
target was already 214 lines underwater when the hook was resurrected from a dead
pre-commit.old backup (2026-07-02, spillover sp-b417481b), so an absolute block
would freeze all commits. Ratchet mode blocks only REGRESSION against the
committed cap. CLAUDE.md's own 200-line cap stays absolute (it passes today).

WHY THE CAP AND THE LAST TOTAL ARE TWO NUMBERS (ASK-285; do not collapse them
back into one):

The ratchet used to auto-tighten its baseline to the total on every shrink. That
made it mutually exclusive with the only sanctioned write path into .claude/.
apply_claude_changes.py is additive-only and refuses ANY frontmatter change on
any op, so through that route the always-on total can grow or stay flat and can
never drop. A cap that tightens on every drop and refuses every rise therefore
refused every rule-file append that route could express: the only way through was
to find unrelated dead weight somewhere else and delete it. PR #48 got through
exactly that way, by the luck of a duplicated paragraph existing in root
CLAUDE.md, and neither the duplicate nor the direct writability generalises.

The fix is in the ACCOUNTING, not in the write path's vocabulary. Additive-only
is why that route is safe to run unattended (ASK-282), so it stays untouched.
A drop in the always-on total is now classified:

  scoping  : a rule that was always-on at the last audit and now carries
             paths:/globs: frontmatter, with its body intact. Its lines stop
             loading every turn. The cap does NOT follow the total down, so the
             freed lines stay as headroom that a later append may spend.
  deletion : anything else -- lines removed from a rule, a rule deleted, root
             CLAUDE.md trimmed. The cap follows the total down, permanently,
             exactly as it did before.

The cap therefore changes only by `-deletion_delta`, which is never negative, so
it is monotone NON-INCREASING by construction: "the floor may tighten, never
loosen" holds. Scoping buys back budget it genuinely freed; it never raises the
ceiling above a value the repo has already lived under.

WHO CAN BANK HEADROOM (say it plainly): scoping means editing a rule's
frontmatter, and apply_claude_changes.py refuses that on every op because a
narrowed paths: switches a rule off while body, tokens and line count all stay
identical (PR #70 rounds 3 and 4, both MAJOR). So an agent cannot bank headroom;
the founder can, with an ordinary edit. An agent SPENDS headroom. That split is
deliberate: deciding a rule may stop loading is a judgement call, and keeping
judgement calls out of the unattended engine is the property that makes it safe.

HONEST BOUNDARY: this baseline JSON lives outside .claude/, so an agent's
ordinary tools can write it and nothing here stops a fabricated cap. The
protection is that the file is tracked and any change to it lands in the commit
diff. That was equally true before this change; it is not a regression, and it is
not a claim this script makes good on.

SECOND HONEST BOUNDARY: every count here reads the WORKING TREE, not the index.
That is required -- apply_claude_changes.py runs this as a gate right after writing
its edits into the tree and BEFORE anything is staged, so an index-reading gate
would be blind to exactly the change it is gating. The consequence is that under a
partial `git add` the tree this run measured is not the tree the commit carries, so
the run RECORDS NOTHING when any audited path differs from the index (see
index_divergence). Judging is unchanged -- the cap check still runs against the tree
and still fails closed on growth; only the accounting transition waits for a commit
that carries the rules it was computed from (PR #88 round 2, major).

THIRD HONEST BOUNDARY: deletion is accounted PER FILE, at the granularity the
baseline snapshot stores. Three lines deleted from one rule and three added to
another tighten the cap by three. Three deleted and three added inside the SAME
rule net to zero and tighten nothing -- separating them needs a line-level diff of
rule bodies, which this baseline does not carry. The direction of that residual is
a cap that stays up to N lines looser than ideal; it never raises the ceiling and
never banks headroom (sp-cdd3f338).

FOURTH HONEST BOUNDARY: a rename is recognised only where git recorded one -- an
`R` record for a staged rename under .claude/rules. Outside a git work tree (a
--root'ed fixture, apply_claude_changes.py's gate suite) there are no records, and
git's own similarity detection can miss a rename that also rewrote most of the
file. Both fall back to the pre-fix reading: the old path is charged as a deletion
and the new one as a fresh file. That direction only ever TIGHTENS the cap (and is
clamped at the total that just passed), so it costs banked headroom and never
mints any. Recovering it is a founder edit of the baseline, same as before.
"""
import json
import os
import re
import subprocess
import sys

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
PROJECT_ROOT = os.path.normpath(os.path.join(QROOT, ".."))

# Anthropic docs say <200 for CLAUDE.md (stated 3x).
# Docs also say: "Rules without paths frontmatter are loaded at launch
# with the same priority as .claude/CLAUDE.md."
# Rules with paths: ["**/*"] match everything = same as no paths.
# Single budget: CLAUDE.md + effectively-always-on rules combined.
BUDGET_CLAUDE_MD = 200
BUDGET_TOTAL_ALWAYS_ON = 300

# Glob patterns that match everything (functionally always-on)
CATCH_ALL_PATTERNS = {"**/*", "**/**", "**"}

# Baseline keys. `cap` is the gate; `total_always_on` is the last observed total
# and is what the next run diffs against. They were one field before ASK-285 and
# are equal in a repo that has only ever deleted, which is why the old name keeps
# its old meaning for any reader that only knows about one number.
KEY_CAP = "cap"
KEY_TOTAL = "total_always_on"
KEY_SNAPSHOT = "always_on_files"


def count_lines(path):
    if not os.path.exists(path):
        return 0
    with open(path) as f:
        return sum(1 for line in f if line.strip())


def parse_paths_from_frontmatter(path):
    """Extract paths/globs list from YAML frontmatter. Returns None if no scoping key."""
    with open(path) as f:
        content = f.read()

    if not content.startswith("---"):
        return None

    end = content.find("---", 3)
    if end == -1:
        return None

    frontmatter = content[3:end]
    # Check for either paths: or globs: (both are scoping keys in Claude Code)
    has_scoping = re.search(r"^(paths|globs):", frontmatter, re.MULTILINE)
    if not has_scoping:
        return None

    # Extract list values from whichever key is present
    paths = []
    in_list = False
    for line in frontmatter.splitlines():
        if re.match(r"^(paths|globs):\s*$", line):
            in_list = True
            continue
        if in_list:
            m = re.match(r'^\s+-\s+"?([^"]+)"?\s*$', line)
            if m:
                paths.append(m.group(1).strip())
            else:
                break
    return paths


def is_effectively_always_on(path):
    """Return True if the rule has no paths: or paths: contains a catch-all glob."""
    paths = parse_paths_from_frontmatter(path)

    # No paths key = always-on
    if paths is None:
        return True

    # Empty paths list = always-on (no restriction)
    if len(paths) == 0:
        return True

    # If ANY pattern is a catch-all, the rule is effectively always-on
    for p in paths:
        if p.strip().strip('"').strip("'") in CATCH_ALL_PATTERNS:
            return True

    return False


def claude_md_sources(path):
    """CLAUDE.md plus every @import target it pulls in. One list, so the counter
    and the index-divergence check cannot disagree about which files are audited."""
    files = [path]
    if not os.path.exists(path):
        return files
    with open(path) as f:
        for line in f:
            match = re.match(r"^@(.+)$", line.strip())
            if match:
                files.append(os.path.join(os.path.dirname(path), match.group(1)))
    return files


def resolve_imports(path):
    """Count lines including @import targets."""
    return sum(count_lines(p) for p in claude_md_sources(path))


def baseline_path(project_root):
    return os.path.join(project_root, "q-system", ".q-system",
                        "instruction-budget-baseline.json")


def read_baseline(project_root):
    path = baseline_path(project_root)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def write_baseline(project_root, cap, total, always_on):
    path = baseline_path(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({KEY_CAP: cap, KEY_TOTAL: total,
                   KEY_SNAPSHOT: dict(sorted(always_on.items()))}, f, indent=2)
        f.write("\n")


def scan_rules(rules_dir):
    """Return (always_on, conditional) as {path-under-rules: substantive lines}.

    os.walk, not os.listdir. A rule at .claude/rules/team/nested.md loads always-on
    exactly like a top-level one, and apply_claude_changes.py is depth-permissive
    for rule text (is_rule_text) with a content census that already walks the whole
    tree, so the sanctioned write path can create one. A one-level listing left
    those lines uncounted: the engine reported "gates held" and the ratchet reported
    headroom on instructions neither could see (PR #88, major).

    The key is the path relative to rules/, which is identical to the old bare
    filename for every top-level rule -- so a pre-existing baseline snapshot keeps
    matching and no rule that was already counted stops being. Same keying as
    _rule_marks in apply_claude_changes.py, deliberately: two spellings of "name a
    rule" is the drift class that opened this hole in the first place.
    """
    always_on = {}
    conditional = {}
    if not os.path.isdir(rules_dir):
        return always_on, conditional
    for dirpath, dirnames, filenames in os.walk(rules_dir):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for filename in sorted(filenames):
            if filename.startswith(".") or not filename.endswith(".md"):
                continue
            full = os.path.join(dirpath, filename)
            name = os.path.relpath(full, rules_dir)
            lines = count_lines(full)
            if is_effectively_always_on(full):
                always_on[name] = lines
            else:
                conditional[name] = lines
    return always_on, conditional


def stage_baseline(project_root):
    """git add the baseline the ratchet just rewrote. Returns the staged
    repo-relative path, or None when there is no index to stage into.

    The ratchet runs from lefthook pre-commit and rewrites the baseline in the
    WORKING TREE. Left unstaged, the commit that CAUSED the accounting transition
    does not carry it: a tightened cap is one `git checkout` from gone, and the
    committed baseline disagrees with the tree every later run reads (PR #88,
    major). The old behaviour was to print "stage this file with the commit",
    which addresses a reader who is not there -- the hook runs unattended, and an
    instruction nobody executes is not a mechanism.

    Never raises and never fails the run. The fixtures and apply_claude_changes.py's
    gate suite both run this against a --root'ed tree that is not a git work tree;
    where the audit was run from must not be what fails it.
    """
    path = baseline_path(project_root)
    try:
        proc = subprocess.run(["git", "-C", project_root, "add", "--", path],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return os.path.relpath(path, project_root)


def git_status(project_root, audited):
    """Parsed `git status --porcelain -z` records for the audited paths.

    Returns [(index_state, tree_state, path, source_path), ...] with source_path
    set only on a rename/copy, or None when there is no index to read (a --root'ed
    fixture, a non-git tree). Callers treat None as "not applicable", never as
    "clean", so a missing git is not silently a pass for a check that never ran.

    ONE call with TWO readers on purpose: index_divergence wants the
    worktree-vs-index column and rule_renames wants the rename records, and they
    have to be describing the same tree at the same instant. Two subprocess calls
    could disagree across an edit landing between them.

    In -z format the rename fields are reversed and un-arrowed: the record carries
    the DESTINATION path and the source follows as its own NUL-terminated field
    with no XY prefix.
    """
    rel = []
    for path in audited:
        r = os.path.relpath(path, project_root)
        if r.startswith(".."):
            continue  # outside the audited root; not in this index either
        rel.append(r)
    if not rel:
        return None
    try:
        proc = subprocess.run(["git", "-C", project_root, "status", "--porcelain",
                               "-z", "--"] + rel,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    if proc.returncode != 0:
        return None

    fields = [f for f in proc.stdout.decode("utf-8", "replace").split("\0") if f]
    records = []
    i = 0
    while i < len(fields):
        field = fields[i]
        i += 1
        if len(field) < 4:
            continue
        index_state, tree_state, name = field[0], field[1], field[3:]
        source = None
        if index_state in ("R", "C") and i < len(fields):
            source = fields[i]
            i += 1
        records.append((index_state, tree_state, name, source))
    return records


def index_divergence(records):
    """Audited paths whose WORKING TREE content differs from the index.

    Returns [] when the tree and the index agree, and None when `records` is None
    (no index to compare against).

    WHY THIS EXISTS (PR #88 round 2, major). The ratchet reads the tree and stages
    the baseline it wrote. Under a partial `git add`, a deletion that lives only in
    the tree tightened the cap, and that tightened cap got committed while the
    rules it was computed from did not -- so the very next fresh clone audited RED
    against a cap no committed rule text could satisfy, and only a hand edit of the
    baseline got it back. Recording a transition therefore waits for a tree that
    matches the index. Judging does not wait: the cap check upstream still runs
    against the tree, so growth still fails closed.
    """
    if records is None:
        return None
    # Second column is the worktree-vs-index state. ' ' means they agree; a
    # staged-only change (e.g. "M ") is exactly what we want to let through.
    return sorted({name for _, tree_state, name, _ in records if tree_state != " "})


def rule_renames(records, project_root, rules_dir):
    """{old snapshot key: new snapshot key} for rules git recorded as renamed.

    Only `R` records, never `C`: a copy leaves its source in place, so rekeying
    the snapshot onto the destination would lose the source's own accounting and
    diff a brand-new file against an entry it never owned.

    Returns {} when there is no index to read, which is the pre-fix behaviour:
    a rename nobody recorded is still charged as a deletion (see the FOURTH
    HONEST BOUNDARY).
    """
    if not records:
        return {}
    prefix = os.path.relpath(rules_dir, project_root) + os.sep
    renames = {}
    for index_state, _, name, source in records:
        if index_state != "R" or not source:
            continue
        if not name.startswith(prefix) or not source.startswith(prefix):
            continue
        renames[source[len(prefix):]] = name[len(prefix):]
    return renames


def apply_renames(snapshot, renames, always_on, conditional):
    """Rekey the snapshot onto the paths the rules live at NOW.

    A rename moves no instruction line: the lines are still loaded every turn and
    still counted in `total`. Diffing the old key against a file that no longer
    answers to that name read the whole rule as deleted, so `git mv` on an
    untouched rule charged the cap for every one of its lines and permanently
    spent headroom the founder had banked by scoping (PR #88 round 3, major).

    Rekeying happens ONCE, here, before either deleted_lines or scoping_freed sees
    the snapshot -- two spellings of "resolve a snapshot key" is the drift class
    that opened the nested-rules hole in round 1.

    The source is followed only when it is genuinely gone from the current scan,
    so a mis-detected rename can never make a still-present rule stop being
    accounted. Colliding keys sum, which keeps sum(snapshot.values()) exact for
    the CLAUDE.md subtraction downstream.
    """
    if not renames:
        return snapshot
    out = {}
    for name, lines in snapshot.items():
        key = name
        if name not in always_on and name not in conditional:
            key = renames.get(name, name)
        out[key] = out.get(key, 0) + lines
    return out


def deleted_lines(snapshot, always_on, conditional, prev_claude_md, claude_md_lines):
    """Always-on lines the snapshot had that no longer exist anywhere, per file.

    Netting the whole repo's drop against the scoping credit was wrong: a step that
    scoped 20 lines, deleted 3 from one rule and added 3 to another netted out to
    "scoping only", so the 3 deleted lines never tightened the cap and turned into
    permanent extra headroom (PR #88 round 2, minor). An addition in one file must
    not pay for a deletion in another, so each file is diffed against its own
    snapshot entry:

      still always-on : deleted = max(0, before - after)
      now conditional : the credited survivors are min(before, after), so the
                        uncredited remainder is a deletion -- same split section 9
                        already pinned for scoped-and-gutted
      gone entirely   : the whole entry is a deletion

    CLAUDE.md has no snapshot entry of its own; its previous line count is the
    recorded total minus the recorded rules, which is exact.
    """
    deleted = max(0, prev_claude_md - claude_md_lines)
    for name, before in snapshot.items():
        if name in always_on:
            after = always_on[name]
        elif name in conditional:
            after = min(before, conditional[name])
        else:
            after = 0
        if after < before:
            deleted += before - after
    return deleted


def scoping_freed(snapshot, always_on, conditional):
    """Lines the last audit counted as always-on that are now paths-scoped.

    Returns (freed_lines, [(name, lines), ...]).

    Only a rule that WAS always-on can free anything: a brand-new paths-scoped
    rule was never costing always-on lines, so crediting it would mint headroom
    out of nothing. A rule that vanished entirely is a deletion and earns no
    credit either -- deleting a rule already tightens the cap, which is the
    behaviour that has held since the ratchet was resurrected.

    A rule that was scoped AND shortened in the same step is credited only
    min(before, after): the shortening half is a deletion and tightens the cap
    like any other.
    """
    freed = 0
    moved = []
    for name, before in sorted(snapshot.items()):
        if name in always_on:
            continue
        if name not in conditional:
            continue
        credited = min(before, conditional[name])
        if credited <= 0:
            continue
        freed += credited
        moved.append((name, credited))
    return freed, moved


def ratchet_fail_text(cap, total, always_on):
    """The message an agent reads when it is over the cap.

    It names the moves that are actually REACHABLE from where the reader stands,
    because the old text ("Trim what you added, or move a rule to paths-scoped")
    named two moves the sanctioned write path cannot make and cost a full agent
    pass to discover (ASK-285).
    """
    candidates = sorted(always_on.items(), key=lambda kv: -kv[1])[:3]
    named = ", ".join("%s (%d)" % (n, c) for n, c in candidates) or "none"
    return (
        "RATCHET FAIL: always-on total {cap} -> {total} (+{over}); headroom 0.\n"
        "  Reachable with no deletion anywhere: put the new lines in a rule that "
        "declares paths:/globs: frontmatter. A paths-scoped rule costs 0 always-on "
        "lines, create_file through apply-claude-changes.sh can make one, and "
        "appending to an already-scoped rule is free.\n"
        "  Growing an ALWAYS-ON rule needs headroom, and only scoping an existing "
        "always-on rule creates it. Largest candidates: {named}.\n"
        "  Scoping is a founder edit: apply_claude_changes.py refuses frontmatter "
        "changes on every op, because a narrowed paths: switches a rule off.\n"
        "  Target remains {target}."
    ).format(cap=cap, total=total, over=total - cap, named=named,
             target=BUDGET_TOTAL_ALWAYS_ON)


def report_baseline_written(project_root, stage):
    """One line saying where the rewritten baseline went, staged or not."""
    staged = stage_baseline(project_root) if stage else None
    if staged:
        print(f"RATCHET: staged {staged} with this commit.")
    else:
        print(f"RATCHET: stage {baseline_path(project_root)} with this commit.")


def run_ratchet(project_root, claude_md_lines, total, always_on, conditional,
                rules_dir, audited=(), write=True, stage=True):
    """Regression gate: block growth past the cap; tighten the cap on deletion."""
    if claude_md_lines > BUDGET_CLAUDE_MD:
        print(
            f"RATCHET FAIL: CLAUDE.md {claude_md_lines} > {BUDGET_CLAUDE_MD} (absolute cap)"
        )
        return 1

    baseline = read_baseline(project_root)
    if baseline is None:
        print(f"RATCHET: baseline created at {total} (target {BUDGET_TOTAL_ALWAYS_ON})")
        if write:
            write_baseline(project_root, total, total, always_on)
            report_baseline_written(project_root, stage)
        return 0

    # A pre-ASK-285 baseline carries one number that meant both cap and total.
    # Reading it as both is exactly the old behaviour, so the upgrade run cannot
    # move the gate: it only records the snapshot the next run needs.
    cap = baseline.get(KEY_CAP, baseline.get(KEY_TOTAL))
    prev_total = baseline.get(KEY_TOTAL, cap)
    snapshot = baseline.get(KEY_SNAPSHOT)

    if total > cap:
        print(ratchet_fail_text(cap, total, always_on))
        return 1

    records = git_status(project_root, audited)
    diverged = index_divergence(records)
    if diverged:
        print(f"RATCHET PASS: total {total}, cap {cap}, headroom {cap - total}. "
              f"Target {BUDGET_TOTAL_ALWAYS_ON}.")
        print("RATCHET: not recording. {n} audited path(s) differ from the index "
              "({names}), so this run measured a tree the commit does not carry and "
              "a cap recorded from it could be one the committed rules already "
              "violate. Stage them, or let the commit that carries them record "
              "it.".format(n=len(diverged), names=", ".join(diverged)))
        return 0

    if snapshot is None:
        # No snapshot to diff against, so no drop can be attributed to scoping and
        # none can be attributed per file either. Fall back to the old netted
        # auto-tighten, which is the conservative answer.
        moved = []
        deletion_delta = max(0, prev_total - total)
    else:
        # `snapshot` stays as recorded; `prev_files` is the same entries rekeyed
        # onto today's paths. Keeping them apart is what lets the changed-compare
        # below still see the rename that the rekey deliberately smooths over.
        prev_files = apply_renames(snapshot,
                                   rule_renames(records, project_root, rules_dir),
                                   always_on, conditional)
        _, moved = scoping_freed(prev_files, always_on, conditional)
        prev_claude_md = prev_total - sum(prev_files.values())
        deletion_delta = deleted_lines(prev_files, always_on, conditional,
                                       prev_claude_md, claude_md_lines)

    # Never below the current total: moving lines between two always-on rules is a
    # per-file deletion plus a per-file addition, and letting the deletion half
    # alone push the cap under the tree that just passed would fail the NEXT commit
    # with no reachable move. Still monotone non-increasing -- both arms are <= cap.
    new_cap = max(total, cap - deletion_delta)

    # The snapshot compare is load-bearing, not belt-and-braces. A pure rename
    # moves neither the cap nor the total, and git reports the rename ONLY in the
    # commit that makes it -- so a run that declined to record would leave the old
    # key in the baseline and the NEXT run would see a rule vanish with nothing
    # left to explain it, charging the deletion one commit late. `snapshot is
    # None` is subsumed: None never equals a scan.
    changed = (new_cap != cap or total != prev_total or snapshot != always_on)
    if changed and write:
        write_baseline(project_root, new_cap, total, always_on)

    scoped_note = ""
    if moved:
        scoped_note = " scoped: %s;" % ", ".join("%s (%d)" % (n, c) for n, c in moved)
    if new_cap < cap:
        print(f"RATCHET: tightened cap {cap} -> {new_cap} on {cap - new_cap} deleted "
              f"line(s).{scoped_note} total {total}, headroom {new_cap - total} "
              f"(target {BUDGET_TOTAL_ALWAYS_ON}).")
    else:
        print(f"RATCHET PASS: total {total}, cap {new_cap}, headroom "
              f"{new_cap - total}.{scoped_note} Target {BUDGET_TOTAL_ALWAYS_ON}.")
    if changed and write:
        report_baseline_written(project_root, stage)
    return 0


def parse_root(argv):
    """--root DIR overrides the tree under audit.

    One resolver, so the baseline path, CLAUDE.md and the rules dir cannot end up
    pointing at different trees. Without it the script derives everything from
    __file__, which means a test fixture is audited only if the test copies the
    script into the fixture AND nothing else in the tree disagrees -- and it
    means apply_claude_changes.py could not run this as a gate against a
    --root'ed tree at all.
    """
    if "--root" not in argv:
        return PROJECT_ROOT
    idx = argv.index("--root")
    if idx + 1 >= len(argv):
        print("--root needs a value")
        sys.exit(2)
    return os.path.abspath(argv[idx + 1])


def main():
    argv = sys.argv[1:]
    project_root = parse_root(argv)
    write = "--no-write" not in argv
    stage = "--no-stage" not in argv

    claude_md = os.path.join(project_root, "CLAUDE.md")
    rules_dir = os.path.join(project_root, ".claude", "rules")

    audited = claude_md_sources(claude_md) + [rules_dir]
    claude_md_lines = resolve_imports(claude_md)
    always_on, conditional = scan_rules(rules_dir)
    total = claude_md_lines + sum(always_on.values())

    if "--ratchet" in argv:
        sys.exit(run_ratchet(project_root, claude_md_lines, total,
                             always_on, conditional, rules_dir, audited=audited,
                             write=write, stage=stage))

    print(f"CLAUDE.md (with imports): {claude_md_lines} / {BUDGET_CLAUDE_MD}")
    print(f"Always-on rules ({len(always_on)} files):")
    for name, lines in sorted(always_on.items()):
        print(f"  {name}: {lines}")
    print(f"Conditional rules ({len(conditional)} files):")
    for name, lines in sorted(conditional.items()):
        print(f"  {name}: {lines}")
    print(f"Total always-on (CLAUDE.md + rules): {total} / {BUDGET_TOTAL_ALWAYS_ON}")

    baseline = read_baseline(project_root)
    if baseline is not None:
        cap = baseline.get(KEY_CAP, baseline.get(KEY_TOTAL))
        print(f"Ratchet cap: {cap} (headroom {cap - total})")

    failed = False
    if claude_md_lines > BUDGET_CLAUDE_MD:
        print(
            f"\nFAIL: CLAUDE.md exceeds {BUDGET_CLAUDE_MD}-line budget "
            f"by {claude_md_lines - BUDGET_CLAUDE_MD} lines"
        )
        failed = True
    if total > BUDGET_TOTAL_ALWAYS_ON:
        print(
            f"\nFAIL: Total always-on exceeds {BUDGET_TOTAL_ALWAYS_ON}-line budget "
            f"by {total - BUDGET_TOTAL_ALWAYS_ON} lines"
        )
        failed = True

    if not failed:
        print("\nPASS: All budgets within limits")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
