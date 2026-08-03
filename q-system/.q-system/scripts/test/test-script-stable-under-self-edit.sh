#!/usr/bin/env bash
# Reproducer + regression test for ASK-346.
#
# THE DEFECT
# ----------
# bash does not read a script into memory. It reads a chunk, executes it, then
# SEEKS BACK to a saved byte offset for the next command. If the file changes on
# disk while the script is still running, that offset now points into the middle
# of a different line, and bash resumes parsing from there. Bare words that live
# INSIDE a quoted string become commands.
#
# This is exactly what killed the ASK-288 converge run on 2026-08-03:
#   converge.sh: line 872: of: command not found
#   converge.sh: line 872: not: command not found
#   converge.sh: line 876: syntax error near unexpected token `fi'
# Line 872 on disk is `fi`. The words `of` and `not` appear ONLY inside the
# double-quoted STALL_LOG/STALL_PAGE strings at 868 and 871. No correct read can
# execute them. `bash -n` passes on every committed version -- the file was never
# syntactically wrong, it was edited underneath a live reader. Commit d142466
# landed 2026-08-03T03:45:48Z, seven minutes into a run that started 03:38:26Z.
# linear-worker.log carries the same signature (`ial: command not found`), so this
# is a class that spans every long-running script in the fleet, not one bug.
#
# THE FIX UNDER TEST
# ------------------
# Wrap the whole script body in a `{ ... }` compound command AND make the last
# statement inside it an explicit `exit`. bash must parse a compound command to
# completion before executing any of it, so the body is consumed at startup and a
# mid-run edit cannot reach it.
#
# The `exit` is NOT decoration, and the first draft of this test proved it: a
# brace wrap ALONE still failed with rc=2. The body ran correctly and printed its
# result, then bash seeked past the closing brace to look for the next command,
# landed at a stale offset in a file that had grown, and died on the leftovers
# ("unexpected EOF while looking for matching quote"). Wrapping protects what bash
# has already parsed; only exiting stops it from reading again. Both halves are
# load-bearing and test 3 below holds each one separately.
#
# Deliberately NOT a snapshot-and-exec into /tmp: converge.sh:30 derives SCRIPT_DIR
# from BASH_SOURCE, and SKEL, NOTIFY and pr-verdict-lib.sh all hang off it.
# Re-execing a copy would silently repoint every one of them.
set -uo pipefail

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILED=0

pass() { printf 'PASS: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1"; FAILED=1; }

# The one correct output. Every assertion below compares against this LITERAL,
# never against "whatever the other run did" -- a baseline captured from the same
# code cannot see a change that moves both sides.
readonly WANT_OUT='START
END:a head of steam is not the same as progress'

# Build a victim script.
#   wrap=plain    -> body at top level, explicit exit at the end
#   wrap=braced   -> body inside { }, explicit exit INSIDE the braces
#   wrap=braceonly-> body inside { }, NO exit (isolates the second half of the fix)
# The PAD lines make the file long enough that bash's read buffer cannot swallow
# it whole; the tail must land past the first chunk or the defect cannot show. The
# quoted strings supply the bare words that become commands once the offset slips.
make_victim() {
  local path="$1" wrap="$2"
  {
    printf '#!/usr/bin/env bash\n'
    [ "$wrap" != "plain" ] && printf '{\n'
    # The insertion point must sit BEHIND the byte offset bash parks at, so the
    # shift moves ground bash has already passed. Putting it after the wait loop
    # instead makes the injected lines land exactly on the resume offset, they
    # parse as whole valid statements, and nothing breaks -- an earlier draft of
    # this test sat green for exactly that reason and proved nothing.
    printf '# --- INSERT HERE ---\n'
    printf 'echo START\n'
    printf 'while [ ! -f "$1" ]; do sleep 0.05; done\n'
    for i in $(seq 1 400); do
      printf 'PAD_%d="padding line %d of the victim, not a real assignment"\n' "$i" "$i"
    done
    printf 'MSG="a head of steam is not the same as progress"\n'
    printf 'echo "END:$MSG"\n'
    [ "$wrap" != "braceonly" ] && printf 'exit 0\n'
    [ "$wrap" != "plain" ] && printf '}\n'
  } > "$path"
  return 0
}

# Run the victim; while it is parked in its wait loop, insert lines in the MIDDLE
# of the file. Middle-insertion is the faithful shape: commit d142466 edited the
# body of converge.sh, shifting every byte offset after the insertion point while
# leaving the head alone. Prepending would shift the whole file and is a different,
# easier case.
run_with_midrun_edit() {
  local path="$1" do_edit="$2" out="$3"
  local gate="$TMP/gate.$RANDOM"
  rm -f "$gate"
  bash "$path" "$gate" > "$out" 2>&1 &
  local pid=$!
  local waited=0
  while ! grep -q START "$out" 2>/dev/null; do
    sleep 0.05; waited=$((waited + 1))
    if [ "$waited" -gt 100 ]; then echo "HARNESS-TIMEOUT"; kill "$pid" 2>/dev/null; return 0; fi
  done
  if [ "$do_edit" = "edit" ]; then
    local tmpf="$TMP/edit.$RANDOM"
    awk '{print} /--- INSERT HERE ---/{for(i=0;i<10;i++) print "INJECTED_" i "=\"a line that landed mid-run\""}' \
      "$path" > "$tmpf"
    cat "$tmpf" > "$path"   # in-place rewrite: same inode, shifted contents
  fi
  touch "$gate"
  wait "$pid"; local rc=$?
  echo "$rc"
}

# Corruption == the run did not produce EXACTLY the one correct result.
# Deliberately not "rc != 0" and not "stderr mentions something": a run that
# re-executes its own body and still exits 0 is corrupt, and the first draft of
# this test saw exactly that (START printed twice, rc=0).
is_clean() {
  local rc="$1" out="$2"
  [ "$rc" = "0" ] && [ "$(cat "$out")" = "$WANT_OUT" ]
}

show() { sed 's/^/    /' "$1" | grep -vE '^\s+(PAD|INJECTED)' | head -8; }

echo "=== 1. NEGATIVE SELF-TEST: unwrapped, NOT edited -> must be clean ==="
# If this fails the harness is broken and every result below is noise.
V="$TMP/victim_clean.sh"; O="$TMP/out_clean.txt"
make_victim "$V" "plain"
RC="$(run_with_midrun_edit "$V" "noedit" "$O")"
if is_clean "$RC" "$O"; then
  pass "unedited run produces exactly the wanted output (rc=0) -- harness can go green"
else
  fail "unedited run was NOT clean (rc=$RC). Harness is broken; ignore everything below."
  show "$O"
fi

echo
echo "=== 2. THE DEFECT: unwrapped, edited mid-run -> must corrupt ==="
V="$TMP/victim_edit.sh"; O="$TMP/out_edit.txt"
make_victim "$V" "plain"
RC="$(run_with_midrun_edit "$V" "edit" "$O")"
if is_clean "$RC" "$O"; then
  fail "mid-run edit did NOT corrupt (rc=$RC). The reproducer no longer reproduces, so \
tests 3a/3b prove nothing and must not be trusted until this is repaired."
  show "$O"
else
  pass "mid-run edit corrupts an unwrapped script (rc=$RC, output != wanted)"
  show "$O"
fi

echo
echo "=== 3a. HALF A FIX: braces but no exit, edited mid-run -> still corrupts ==="
# This case is why the fix is two things, not one. Keep it: if someone later drops
# the trailing exit as redundant, this is the test that goes red.
V="$TMP/victim_braceonly.sh"; O="$TMP/out_braceonly.txt"
make_victim "$V" "braceonly"
RC="$(run_with_midrun_edit "$V" "edit" "$O")"
if is_clean "$RC" "$O"; then
  fail "braces alone were sufficient (rc=$RC) -- if that is now true the trailing exit is \
not load-bearing and the fix comment must be corrected."
  show "$O"
else
  pass "braces WITHOUT a trailing exit still corrupt (rc=$RC): bash reads past the brace"
  show "$O"
fi

echo
echo "=== 3b. THE FIX: braces + trailing exit, edited mid-run -> must survive ==="
V="$TMP/victim_wrapped.sh"; O="$TMP/out_wrapped.txt"
make_victim "$V" "braced"
RC="$(run_with_midrun_edit "$V" "edit" "$O")"
if is_clean "$RC" "$O"; then
  pass "braces + exit survive the identical mid-run edit (rc=0, exactly the wanted output)"
else
  fail "braces + exit still corrupted (rc=$RC)"
  show "$O"
fi

echo
echo "=== 4. LOAD-PATH PROOF: the real scripts carry the wrap ==="
# Grepping that the text exists is not proof the shape is correct, so parse each
# file and confirm bash still accepts it, THEN confirm the wrap is the outermost
# construct (line 2 opens it, last line closes it).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$HERE/.."
for s in converge.sh linear-worker.sh; do
  f="$SCRIPTS_DIR/$s"
  if [ ! -f "$f" ]; then fail "$s not found at $f"; continue; fi
  if ! bash -n "$f" 2>/dev/null; then fail "$s does not parse"; continue; fi
  # The shebang starts with '#', so it is already excluded here and the wrap is
  # the FIRST surviving line. An earlier draft took '2p' and reported the line
  # after the wrap, which would have called a correctly-wrapped file broken.
  first_code="$(grep -nvE '^\s*(#|$)' "$f" | sed -n '1p' | cut -d: -f2-)"
  last_code="$(grep -vE '^\s*(#|$)' "$f" | tail -1)"
  if [ "$first_code" = "{" ] && [ "$last_code" = "}" ]; then
    pass "$s is brace-wrapped end to end and parses"
  else
    fail "$s missing the wrap (first code line after shebang: '$first_code', last: '$last_code')"
  fi
done

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL PASS"; else echo "SUITE FAILED"; fi
exit "$FAILED"
