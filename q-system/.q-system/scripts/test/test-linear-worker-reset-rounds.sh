#!/usr/bin/env bash
# Reproducer + acceptance criterion for "--reset-rounds reports success
# unconditionally" (ASK-208, PR #22 review round 4, finding 1).
#
# THE DEFECT: the round cap added in round 3 has exactly ONE way out, and it
# wrote the ledger with `>/dev/null 2>&1 || true` and then printed "review round
# count reset to 0; the next run will dispatch again" no matter what happened.
# It never validated the issue id, never normalized case, and never read back
# what it wrote. So all three of these printed success and exited 0:
#
#   * a lowercase id      -> a PHANTOM ledger key `ask-208` at rounds 0, while
#                            the real `ASK-208` stayed capped
#   * an unwritable ledger-> nothing written at all
#   * a corrupt ledger    -> `except Exception: d={}` then a full rewrite, which
#                            silently DESTROYS every other issue's counters
#
# BLAST RADIUS AT 3AM: the worker pages once on the cap transition and then sets
# capped_notified, so it never pages again. The operator runs the reset, is told
# it worked, and walks away. The issue stays capped and goes permanently dark --
# the worker going dark right after the operator did the right thing is the
# exact regression round 2 of this PR raised one layer up.
#
# THE LAYER ABOVE THE RESET: --issue has a SECOND reader. The picker matches
# `i["identifier"] == only` exactly, so `--issue ask-aaa` also silently yields
# zero ready issues on the normal work path. Two readers of one input with
# different semantics is the defect even when each is individually defensible,
# so case 1 asserts the reset AND the dispatch that has to follow it.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
WORKER="$ROOT/q-system/.q-system/scripts/linear-worker.sh"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$WORKER" ] || fail "linear-worker.sh does not exist at $WORKER"
REAL_PY="$(command -v python3)" || fail "python3 not on PATH"
REAL_GIT="$(command -v git)"    || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID 2>/dev/null || true
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

git init -q --bare "$WORK/origin"
git -C "$WORK/origin" symbolic-ref HEAD refs/heads/main
git init -q "$WORK/skel"
G -C "$WORK/skel" commit -q --allow-empty -m c1
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "$WORK/origin"
git -C "$WORK/skel" push -q -u origin main

STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home" "$WORK/state/pr-reviews"
ATT="$WORK/state/linear-worker-attempts.json"

# The picker stub reproduces the REAL picker's semantics, exact match included
# (`pool = [i for i in issues if i["identifier"] == only]`). A stub that returned
# the issue regardless of the filter would hide half this finding: the reset
# could be fixed while `kipi work --issue ask-aaa` stayed silently dark.
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '%s\n' "\${2:-}" >> "$WORK/picker-arg.txt"
      case "\${2:-}" in
        ""|ASK-AAA) printf '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"}],"total_open":1}\n' ;;
        *)          printf '{"ready":[],"total_open":1}\n' ;;
      esac
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "pr list"*)                      echo 999 ;;
  "pr view 999 --json mergeable"*) echo CONFLICTING ;;
esac
exit 0
EOF
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
case "\$*" in
  *"You are Sana"*) echo "round" >> "$WORK/dispatched.txt" ;;
esac
exit 0
EOF
cat > "$WORK/notify-recorder.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$WORK/pages.txt"
EOF
chmod +x "$STUB/python3" "$STUB/gh" "$STUB/claude" "$WORK/notify-recorder.sh"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

printf '{"verdict":"REQUEST CHANGES","pr":999}\n' > "$WORK/state/pr-reviews/pr-999.verdict.json"
: > "$WORK/dispatched.txt"; : > "$WORK/pages.txt"; : > "$WORK/picker-arg.txt"

CAP=3
run_worker() {
  ( cd "$WORK/skel" \
    && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state" \
       KIPI_NOTIFY="$WORK/notify-recorder.sh" KIPI_MAX_ROUNDS="$CAP" \
       bash "$WORKER" "$@" ) >"$WORK/run.out" 2>&1
  echo $? > "$WORK/rc"
}
rc()    { cat "$WORK/rc"; }
count() { wc -l < "$1" | tr -d ' '; }
capped_ledger() { printf '{"ASK-AAA":{"count":0,"rounds":9,"capped_notified":true}}\n' > "$ATT"; }
jkey()  { "$REAL_PY" -c "
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: print('CORRUPT'); raise SystemExit(0)
print(json.dumps(d.get(sys.argv[2],'MISSING')))" "$ATT" "$1"; }

# --- 1. a lowercase id must not create a phantom key -----------------------
capped_ledger
run_worker --reset-rounds --issue ask-aaa
[ "$(jkey ask-aaa)" = '"MISSING"' ] \
  || fail "PHANTOM KEY: --reset-rounds --issue ask-aaa wrote a new lowercase entry
      $(jkey ask-aaa) while the real ASK-AAA stayed $(jkey ASK-AAA). The operator
      is told it worked; the issue stays capped and never pages again."
[ "$("$REAL_PY" -c "import json;print(json.load(open('$ATT'))['ASK-AAA']['rounds'])")" = "0" ] \
  || fail "ASK-AAA was not reset by a lowercase id: $(jkey ASK-AAA)"
ok "a lowercase issue id resets the REAL entry, with no phantom key"

# The other reader of the same input. A reset that works while the work path
# still matches case-sensitively leaves the issue just as dark.
: > "$WORK/dispatched.txt"
run_worker --apply --issue ask-aaa --limit 1
[ "$(count "$WORK/dispatched.txt")" = "1" ] \
  || fail "SECOND READER: after a successful reset, --apply --issue ask-aaa dispatched
      nothing. The picker matches identifiers exactly, so the id has to be
      normalized once at the entry point, not inside the reset branch.
      picker saw: $(tail -1 "$WORK/picker-arg.txt")"
ok "the same lowercase id also reaches the picker (one normalization, both readers)"

# --- 2. a failed write must not report success -----------------------------
# The reviewer's own repro. Root can write to a 0444 file, so this case is only
# meaningful unprivileged; it is announced rather than silently skipped.
if [ "$(id -u)" = "0" ]; then
  echo "  -- case 2 (unwritable ledger) not meaningful as root; not counted"
else
  capped_ledger
  chmod 444 "$ATT"
  run_worker --reset-rounds --issue ASK-AAA
  RC2="$(rc)"
  chmod 644 "$ATT"
  [ "$RC2" != "0" ] \
    || fail "SILENT SUCCESS: the reset exited 0 against an unwritable ledger.
      It printed: $(tail -1 "$WORK/run.out")"
  grep -q "will dispatch again" "$WORK/run.out" \
    && fail "the reset claimed 'the next run will dispatch again' after writing nothing:
      $(tail -1 "$WORK/run.out")"
  [ "$("$REAL_PY" -c "import json;print(json.load(open('$ATT'))['ASK-AAA']['rounds'])")" = "9" ] \
    || fail "the ledger changed despite the write failing: $(jkey ASK-AAA)"
  ok "an unwritable ledger fails loudly instead of claiming the reset happened"
fi

# --- 3. a typo'd id says so instead of inventing an entry ------------------
capped_ledger
run_worker --reset-rounds --issue ASK-TYPO
[ "$(rc)" != "0" ] \
  || fail "SILENT SUCCESS: resetting an issue with no recorded rounds exited 0.
      It printed: $(tail -1 "$WORK/run.out")"
[ "$(jkey ASK-TYPO)" = '"MISSING"' ] \
  || fail "a typo'd id created a ledger entry: $(jkey ASK-TYPO)"
ok "an id with no recorded rounds is reported, not invented"

# --- 4. the happy path reports the value it read BACK ----------------------
# "reset to 0" was a claim. The number has to come off disk after the write, or
# the operator is trusting a print statement instead of the ledger.
capped_ledger
run_worker --reset-rounds --issue ASK-AAA
[ "$(rc)" = "0" ] || fail "a valid reset failed: $(tail -2 "$WORK/run.out")"
grep -q "9" "$WORK/run.out" \
  || fail "the reset does not report the previous round count it replaced (was 9):
      $(tail -1 "$WORK/run.out")"
[ "$("$REAL_PY" -c "import json;d=json.load(open('$ATT'))['ASK-AAA'];print(d['rounds'],d.get('capped_notified'))")" = "0 None" ] \
  || fail "the reset left the ledger wrong: $(jkey ASK-AAA)"
ok "a valid reset reports the previous count read back off disk, and clears capped_notified"

: > "$WORK/dispatched.txt"
run_worker --apply --issue ASK-AAA --limit 1
[ "$(count "$WORK/dispatched.txt")" = "1" ] \
  || fail "after a reported reset the worker still refused; the cap is permanent darkness"
ok "the issue dispatches again after the reset (the way back is real)"

# --- 5. a corrupt ledger is not silently rewritten -------------------------
# `except Exception: d={}` + a full json.dump would drop every OTHER issue's
# counters on the floor to satisfy one reset. Data loss, reported as success.
printf 'not json at all\n' > "$ATT"
run_worker --reset-rounds --issue ASK-AAA
[ "$(rc)" != "0" ] \
  || fail "SILENT SUCCESS: the reset exited 0 against a corrupt ledger:
      $(tail -1 "$WORK/run.out")"
[ "$(cat "$ATT")" = "not json at all" ] \
  || fail "DATA LOSS: a corrupt ledger was overwritten by the reset. Every other
      issue's attempt and round counters are gone. File now: $(cat "$ATT")"
ok "a corrupt ledger is left alone and reported, not overwritten"

# --- 6. the refusal to reset does not turn into silence --------------------
# After a FAILED reset the issue must still be visibly capped. A half-written
# ledger that reads as uncapped would be the worst of both.
capped_ledger
chmod 444 "$ATT" 2>/dev/null || true
run_worker --reset-rounds --issue ASK-AAA
chmod 644 "$ATT" 2>/dev/null || true
run_worker --issue ASK-AAA --limit 1
grep -qi "round cap" "$WORK/run.out" \
  || fail "after a failed reset the dry run no longer reports the cap:
      $(tail -2 "$WORK/run.out")"
ok "a failed reset leaves the issue visibly capped in the dry run"

bash -n "$WORKER" || fail "linear-worker.sh does not parse"
ok "linear-worker.sh parses (bash -n)"

echo "PASS: worker reset-rounds ($PASS checks)"
