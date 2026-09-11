#!/usr/bin/env bash
# Reproducer for PR #85 round 10 (BLOCKER).
#
# THE FINDING, in the reviewer's words: "awk is treated as read-only, allowing it
# to overwrite .claude/settings.json and sanction the disabled hooks with a
# same-command baseline rewrite" (claude-path-write-guard.py:994).
#
# CONFIRMED, and the diagnosis is one level up from the spelling. `READ_ONLY`
# declares "programs that cannot write to a path they are given". That claim is
# FALSE for eight of its members, and the file already knew about two of them:
# `READER_WRITE_FLAGS` is an inner enumeration of the write FORMS of `sed` and
# `find`. That inner list is the fail-open surface the file's own header warns
# about -- "enumerating writers and getting it wrong yields a false ALLOW
# (silent, and the gate was never real)". It got `sed` wrong (`-i` only; `w` and
# `s///w` write with no `-i` in sight), it got `find` wrong (`-fprint`/`-fls`/
# `-fprintf` write and match none of its four patterns), and it never covered
# `awk` at all despite the comment above it naming "awk-into-a-file".
#
# Measured live against the pre-fix guard, all rc=0:
#     sed -n 'w .claude/settings.json' /etc/hosts
#     sort -o .claude/settings.json /dev/null
#     uniq /dev/null .claude/settings.json
#     tree -o .claude/settings.json .
#     xxd /dev/null .claude/settings.json
#     yq -i '.a=1' .claude/settings.json
#
# WHY awk in particular is worse than the others: its write channel lives INSIDE
# a program text (`system()`, `print | "cmd"`, `print > "f"`), which
# component-wise path resolution structurally cannot see. That is the same shape
# the file already handles for python/perl/node -- "an interpreter carries its
# target INSIDE a code string" (guard:1035) -- so awk and sed were simply
# misfiled as readers. `awk` and `sed` are interpreters that happen to default to
# printing.
#
# WHAT DONE LOOKS LIKE (stated before the fix, per verification-loops):
#   phase 1  the awk write channels that carry no shell `>` block
#   phase 2  the CLASS blocks: sed's non-`-i` write forms, and every READ_ONLY
#            member that takes an output-file argument
#   phase 3  every pinned allow survives, including the read-only escape hatch
#   phase 4  the NAMED COST is pinned as a block, so it is visible not hidden:
#            plain awk/sed/sort/find READS of a .claude path now block too
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GUARD="$ROOT/q-system/.q-system/scripts/claude-path-write-guard.py"
TRIP="q-system/.q-system/scripts/claude-integrity-tripwire.py"
PASS=0; FAIL=0

run() { # command -> rc
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]},"cwd":sys.argv[2]}))' "$1" "$ROOT" \
    | CLAUDE_PROJECT_DIR="$ROOT" python3 "$GUARD" >/dev/null 2>&1
  echo $?
}

expect() { # want_rc, desc, command
  local want="$1" desc="$2" cmd="$3" got
  got="$(run "$cmd")"
  if [ "$got" = "$want" ]; then
    PASS=$((PASS+1)); printf 'ok    %s (rc=%s)\n' "$desc" "$got"
  else
    FAIL=$((FAIL+1)); printf 'FAIL  %s (want rc=%s, got rc=%s)\n  cmd: %s\n' "$desc" "$want" "$got" "$cmd"
  fi
}

echo "== phase 1: awk, the program the finding names =="
# The `>` spellings are caught today only by accident: the redirect scanner sees
# awk's `>` and reads it as a SHELL redirect. These three carry no `>` at all.
expect 2 "awk system() into .claude" \
  "awk 'BEGIN{system(\"touch .claude/settings.json\")}'"
expect 2 "awk system() + same-command --baseline" \
  "awk 'BEGIN{system(\"touch .claude/settings.json\")}'; python3 $TRIP --baseline"
expect 2 "awk pipes into a writing command" \
  "awk 'BEGIN{print \"x\" | \"tee .claude/settings.json\"}'"
expect 2 "awk -v carries the path, program text does the write" \
  "awk -v f=.claude/settings.json 'BEGIN{print \"x\" > f}'"

echo
echo "== phase 2: the CLASS, not the one program =="
# sed writes without -i. READER_WRITE_FLAGS['sed'] only knows -i.
expect 2 "sed w-command" \
  "sed -n 'w .claude/settings.json' /etc/hosts"
expect 2 "sed s///w flag" \
  "sed 's/a/b/w .claude/settings.json' /etc/hosts"
expect 2 "sed W-command" \
  "sed -n 'W .claude/settings.json' /etc/hosts"
# find writes through three flags READER_WRITE_FLAGS['find'] does not list.
expect 2 "find -fprint into .claude" \
  "find /tmp -name x -fprint .claude/settings.json"
expect 2 "find -fls into .claude" \
  "find /tmp -name x -fls .claude/settings.json"
# Readers whose write channel is a plain output-file argument.
expect 2 "sort -o" \
  "sort -o .claude/settings.json /dev/null"
expect 2 "sort --output=" \
  "sort --output=.claude/settings.json /dev/null"
expect 2 "uniq second positional is its OUTPUT file" \
  "uniq /dev/null .claude/settings.json"
expect 2 "tree -o" \
  "tree -o .claude/settings.json ."
expect 2 "xxd second positional is its OUTPUT file" \
  "xxd /dev/null .claude/settings.json"
expect 2 "yq -i" \
  "yq -i '.a=1' .claude/settings.json"
expect 2 "sort -o beside a same-command --baseline" \
  "sort -o .claude/settings.json /dev/null; python3 $TRIP --baseline"

echo
echo "== phase 2b: the path GLUED TO A FLAG (found while fixing phase 2) =="
# `_stage()` skips any token starting with `-` because a flag is not a path.
# `--output=.claude/x` is a flag AND a path, and this is not awk-specific: it is
# every writer in the system. Measured rc=0 on the pre-fix guard.
expect 2 "sort --output= (long flag, attached value)" \
  "sort --output=.claude/settings.json /dev/null"
expect 2 "sort -o.claude/x (short flag, attached value)" \
  "sort -o.claude/settings.json /dev/null"
expect 2 "tar --file=" \
  "tar --file=.claude/settings.json -c /dev/null"
expect 2 "cp --target-directory=" \
  "cp --target-directory=.claude /etc/hosts"
expect 2 "flag-glued path beside a same-command --baseline" \
  "sort --output=.claude/settings.json /dev/null; python3 $TRIP --baseline"

echo
echo "== phase 3: every pinned allow must survive =="
expect 0 "reading a glob beside a re-baseline (READ_ONLY still holds)" \
  "grep -rn hook .claude/rules/*.md; python3 $TRIP --baseline"
expect 0 "cat reads a .claude file" \
  "cat .claude/settings.json"
expect 0 "jq reads a .claude file (no write channel exists)" \
  "jq . .claude/settings.json"
expect 0 "wc reads a .claude file" \
  "wc -l .claude/settings.json"
expect 0 "the sanctioned re-baseline alone" \
  "python3 $TRIP --register .claude/rules/x.md"
expect 0 "plain literal /tmp fixture beside a re-baseline" \
  "mkdir -p /tmp/x/.claude/rules; python3 $TRIP --register .claude/rules/x.md"
expect 0 "awk on a file that is not .claude" \
  "awk '{print \$1}' /etc/hosts"
expect 0 "sort -o to a target that is not .claude" \
  "sort -o /tmp/out /etc/hosts"
expect 0 "find over a tree that is not .claude" \
  "find /tmp -name x -delete"
# THE ESCAPE HATCH for the cost pinned in phase 4: pipe the file in, so the
# interpreter's own stage names no path at all.
expect 0 "escape hatch: pipe a .claude file into awk" \
  "cat .claude/settings.json | awk '{print \$1}'"
expect 0 "escape hatch: pipe a .claude file into sed" \
  "cat .claude/settings.json | sed -n 1p"
# The flag-value rule must not resurrect the false-block class that four earlier
# rounds hit. A flag whose value is ordinary text or an unrelated path stays ok.
expect 0 "flag value that is not a path at all" \
  "python3 script.py --desc=see-the-guard-notes"
expect 0 "flag value that is an unrelated path" \
  "python3 script.py --output=/tmp/out.json"
expect 0 "flag value naming an UNRELATED tree's .claude (round-5 pin)" \
  "sort --output=/tmp/unrelated-tree/.claude/settings.json /dev/null"
expect 0 "ordinary short flags resolve to nothing" \
  "grep -rn hook .claude/rules"

echo
echo "== phase 4: the NAMED COST, pinned as a block so it stays visible =="
expect 2 "plain awk READ of a .claude path (program text is unreadable)" \
  "awk '{print \$1}' .claude/settings.json"
expect 2 "plain sed READ of a .claude path (program text is unreadable)" \
  "sed -n 1p .claude/settings.json"
expect 2 "plain sort READ of a .claude path (sort can write with -o)" \
  "sort .claude/settings.json"
expect 2 "plain find over .claude (find can write with -delete/-fprint)" \
  "find .claude -name '*.md'"

printf '\npassed=%d failed=%d\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ]
