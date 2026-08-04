## Round 10 blocker: fixed, and the defect was the CLAIM, not `awk`

**Your finding, confirmed.** `awk` was in `READ_ONLY`, and `READ_ONLY` said *"programs that cannot write to a path they are given"*. Eight of its members could: `awk`, `sed`, `sort`, `uniq`, `tree`, `xxd`, `yq`, `find`. Measured live on the pre-fix guard, every one rc=0:

```text
sed -n 'w .claude/settings.json' /etc/hosts        rc=0
sort -o .claude/settings.json /dev/null            rc=0
uniq /dev/null .claude/settings.json               rc=0
tree -o .claude/settings.json .                    rc=0
xxd /dev/null .claude/settings.json                rc=0
yq -i '.a=1' .claude/settings.json                 rc=0
find /tmp -name x -fprint .claude/settings.json    rc=0
awk 'BEGIN{system("touch .claude/settings.json")}' rc=0
```

The file's answer for two of those was `READER_WRITE_FLAGS`, an inner enumeration of the write **forms** of `sed` and `find`. That inner list is exactly the fail-open surface this file's own header warns about, and it was wrong in all three directions: it knew `sed -i` and missed `sed 'w FILE'` / `s///w` / `W`; it knew `find -delete` and missed `-fprint` / `-fls` / `-fprintf`; and it never covered `awk` at all, despite the comment directly above it naming "awk-into-a-file" as one of the two cases it handled.

## The fix (two changes, neither one another spelling)

1. **`READ_ONLY` states the property the exemption actually needs, and holds only programs that have it:** no file-writing channel on ANY command line. The eight leave, and `READER_WRITE_FLAGS` is deleted with them. Enumerating a program's write forms is out-guessing its manual forever. Enumerating programs with no channel at all is a claim that can be checked once and stays checked, and a mistake in it is a false BLOCK (loud) instead of a false ALLOW (silent).

2. **`awk` and `sed` are interpreters, not readers.** Their write channel lives inside a program text, which component-wise path resolution structurally cannot see. That is the shape this file already handles for python/perl/node ("an interpreter carries its target INSIDE a code string"); `awk` and `sed` differ only in taking their script *positionally*, so no inline-code flag announces it. They were misfiled as readers because they default to printing. The verdict now depends on **zero awk/sed grammar**: a `.claude` mention anywhere in the STAGE is a block.

Scoped to the stage rather than the statement on purpose, because that is what keeps the escape hatch open: `cat .claude/settings.json | awk '{print $1}'` passes, since stage 2 names no path.

## A wider hole found while fixing it, which you did not report

`_stage()` skipped every `-`-leading token because "a flag is not a path". `--output=.claude/settings.json` is a flag AND a path, and this is not about readers at all -- it is **every writer in the system**:

```text
sort --output=.claude/settings.json /dev/null   rc=0
sort -o.claude/settings.json /dev/null          rc=0
tar --file=.claude/settings.json -c /dev/null   rc=0
cp --target-directory=.claude /etc/hosts        rc=0
```

It would have re-opened the hole pass 1 closed the moment anyone typed the long-flag form. A value attaches to a flag in exactly two ways (after `=`, or directly after a short flag), so `_flag_values()` yields those two mechanical candidates and each is resolved by the same rules as any other token. No table of which flags take a path. `--output=/tmp/unrelated-tree/.claude/x` stays allowed, so the round-5 pin holds.

## Named cost, not hidden

A plain **read** through one of the eight now blocks too: `awk '{print $1}' .claude/settings.json`, `sed -n 1p .claude/settings.json`, `sort .claude/settings.json`, `find .claude -name '*.md'`. Pinned as asserts so it stays a measurement. The escape hatch is free and pinned as an allow: pipe the file in.

## Reproducer first, RED then GREEN

`q-system/output/claude-changes/repro/probe_round10_findings.sh`. Before the patch:

```text
passed=11 failed=20
```

16 of those 20 were live bypasses; the other 4 are the named cost. After:

```text
== phase 1: awk, the program the finding names ==       4 ok
== phase 2: the CLASS, not the one program ==          12 ok
== phase 2b: the path GLUED TO A FLAG ==                5 ok
== phase 3: every pinned allow must survive ==         15 ok
== phase 4: the NAMED COST, pinned as a block ==        4 ok

passed=40 failed=0
```

Permanent suite, 24 cases added (`bash q-system/.q-system/scripts/test/test-claude-write-path.sh`):

```text
passed=136 failed=0
```

It was `passed=113 failed=0` before the additions, and every prior pin still passes.

**A `READ_ONLY` membership pin comes with it.** The set is sound only while every member has no write channel, which is checkable once but only stays checked if adding a name is a reviewed act. The test pins the exact membership and its failure message tells the next editor what claim they are making. It is proven able to fail rather than assumed to be: it went red twice on real mismatches while being wired (an unbound repo-root var, then a one-element sort-order difference) and printed the diff both times.

Regression sweep across the earlier rounds (`run_prior_round_probes.sh`):

```text
probe_round7_findings.sh   13 passed, 0 failed
probe_round8_findings.sh   18 passed, 0 failed
probe_round9_findings.sh   passed=17 failed=0
probe_round10_findings.sh  passed=40 failed=0
```

`AST parse: PASS`. Lefthook pre-commit green on both commits: blocked-paths, large-files, settings-template-sync, instruction-budget (RATCHET PASS, always-on total 512, baseline 512), plugin-version-bump, receipts-ledger, gitleaks (no leaks found).

## Captured, not fixed

`sp-06336c21`: the round-9 `layer2_blind` literal rule still skips `-`-leading tokens, so a flag-glued **unreadable** value beside a same-command re-baseline is not caught by *that* rule. Not a live bypass -- the write itself blocks through the new `_flag_values()` candidate resolution -- but the unreadable-literal rule should consume `_flag_values()` the same way the paths list now does. Ledger item, not a chat mention.

Commits `0c7811d` (guard) and `01dd2fb` (tests). The guard is self-watched, so the write is scripted and registered in a single tool call (`patch_round10_guard.py`, `patch_round10_guard_pass2.py`).

