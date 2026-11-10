#!/usr/bin/env bash
# Reproducer + acceptance criterion for "--ready-json is read-only by
# construction" (ASK-4311; PR #717 review round 1, finding 2 -- major).
#
# THE DEFECT. `--ready-json` exists so the daily API-credit report can ask the
# PICKER how many tickets are left, instead of re-implementing ready() and
# drifting from it. Its own comment at linear-worker.sh:1443 says "Read-only by
# construction: everything with a side effect happens below this line". That was
# false. Three things ran ABOVE the flag's early exit:
#
#   1. the usage breaker, which exits 3 and prints no pick list when it holds;
#   2. `git fetch origin`, which on failure FILES A LINEAR TICKET through
#      $NOTIFY and exits 9;
#   3. the default-branch resolution, which also pages and exits 9.
#
# So a daily REPORT could page Sana's triage queue at 03:00 for an expired
# credential, and the "tickets left to be done" line could read COULD NOT READ
# for reasons that have nothing to do with the board. None of the three is
# needed to answer the question: the picker reads Linear plus the registry, and
# nothing below the flag runs in this mode.
#
# WHY THE CONTRAST CASES ARE HALF THE TEST. A fix that silenced the fetch guard
# or the brake for EVERY run would pass cases 1 and 3 and be strictly worse than
# the bug: a real round would then cut a worktree from a stale base, or spend
# while the brake is holding. Cases 5 and 6 drive --apply through the same two
# broken environments and demand the old behaviour exactly -- exit 9 with a page,
# and exit 3.
#
# Isolation: KIPI_SKEL / KIPI_STATE_DIR / HOME inside a temp dir; python3, gh and
# claude stubbed; $NOTIFY and the breaker redirected to RECORDERS, not no-ops, so
# "did anyone get paged" and "was the brake consulted" are answered by files.
# `git` stays REAL -- an unreachable origin is the subject.
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
STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home"

# Never reach the real reviewer (sp-cb48c3c0): the worker's review step shells
# pr-review-agent.sh, whose default engine is codex.
KIPI_PR_REVIEWER="$STUB/reviewer-noop"
export KIPI_PR_REVIEWER
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/reviewer-noop"; chmod +x "$STUB/reviewer-noop"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/gh"; chmod +x "$STUB/gh"

# A dispatched agent in this test means the run did work it should not have.
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
echo "dispatched" >> "$WORK/worked.txt"
exit 0
EOF
chmod +x "$STUB/claude"

cat > "$WORK/notify-recorder.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$WORK/pages.txt"
EOF
chmod +x "$WORK/notify-recorder.sh"

# The brake, as a RECORDER that always orders a pause. Two questions in one
# file: was it consulted at all, and did its verdict reach the caller.
cat > "$WORK/breaker-pause.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$WORK/breaker-calls.txt"
exit 3
EOF
chmod +x "$WORK/breaker-pause.sh"

export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub; real refs are the subject"

PICK='{"ready":[{"id":"ASK-AAA","title":"t","project":"p"},{"id":"ASK-BBB","title":"t","project":"q"}],"total_open":2,"project_known":true}'
picker_stub() {
  cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '%s\n' '$1'
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
  chmod +x "$STUB/python3"
}
picker_stub "$PICK"

# A repo whose origin does not exist. Every `git fetch origin` here fails.
git init -q "$WORK/skel"
G -C "$WORK/skel" commit -q --allow-empty -m c1
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "$WORK/nowhere.git"       # never created
git -C "$WORK/skel" fetch --quiet origin 2>/dev/null \
  && fail "fixture: the unreachable origin fetched anyway"

run_worker() {  # run_worker <state-dir> <breaker-cmd-or-empty> <args...>
  local state="$1"; shift
  local breaker="$1"; shift
  : > "$WORK/pages.txt"; : > "$WORK/worked.txt"; : > "$WORK/breaker-calls.txt"
  ( cd "$WORK/skel" \
    && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/$state" \
       KIPI_NOTIFY="$WORK/notify-recorder.sh" \
       KIPI_USAGE_BREAKER_CMD="$breaker" \
       bash "$WORKER" "$@" ) >"$WORK/out.txt" 2>"$WORK/err.txt"
}

# ===========================================================================
# PART A -- the read-only question, asked in a broken environment
# ===========================================================================
run_worker state1 "$WORK/breaker-pause.sh" --ready-json
RC=$?

# --- 1. it answered -------------------------------------------------------
if [ "$RC" != "0" ]; then
  fail "--ready-json exited $RC in an environment where only the FETCH is broken.
      The report's 'tickets left to be done' line then reads COULD NOT READ for a
      reason that has nothing to do with the board.
      stdout: $(head -2 "$WORK/out.txt")
      stderr: $(grep -iE 'infra|paused' "$WORK/err.txt" | head -2)"
fi
COUNT="$("$REAL_PY" -c 'import json,sys
try: print(len(json.load(sys.stdin)["ready"]))
except Exception: print(-1)' < "$WORK/out.txt")"
[ "$COUNT" = "2" ] \
  || fail "--ready-json printed no usable pick list (ready=$COUNT): $(head -2 "$WORK/out.txt")"
ok "--ready-json prints the pick list and exits 0 with an unreachable origin and a holding brake"

# --- 1b. stdout is ONLY the pick list -------------------------------------
# The reader is a parser (fleet-api-report.py:98 runs json.loads on it), so one
# stray log line is a failed read. The pre-pick stretch does log to stdout:
# `say()` tees there, and the WIP block announces a repo with no GitHub slug.
LINES="$(wc -l < "$WORK/out.txt" | tr -d ' ')"
[ "$LINES" = "1" ] \
  || fail "--ready-json wrote $LINES lines to stdout; a parser gets all of them.
      stdout: $(head -3 "$WORK/out.txt")"
grep -q "has no GitHub slug" "$WORK/err.txt" \
  || fail "fixture: the WIP log line this case exists for did not appear on stderr
      either, so the case is no longer exercising a stdout-polluting log line"
ok "--ready-json keeps its log lines off stdout (they went to stderr)"

# --- 2. nobody was paged --------------------------------------------------
if [ -s "$WORK/pages.txt" ]; then
  fail "A READ-ONLY REPORT PAGED SANA: --ready-json called \$NOTIFY, which files a
      Linear ticket. The daily report runs this every day, so a broken credential
      becomes a ticket per day from a reporter that was only counting.
      It said: $(head -1 "$WORK/pages.txt")"
fi
ok "--ready-json pages nobody (no Linear ticket from a counting run)"

# --- 3. the brake was never consulted -------------------------------------
if [ -s "$WORK/breaker-calls.txt" ]; then
  fail "--ready-json consulted the usage breaker ($(head -1 "$WORK/breaker-calls.txt")).
      The pick list costs no model call, so the brake has nothing to brake here,
      and its exit 3 replaced the answer with silence."
fi
ok "--ready-json does not consult the usage breaker"

# --- 4. and it did no work ------------------------------------------------
[ ! -s "$WORK/worked.txt" ] || fail "--ready-json dispatched an agent"
[ ! -d "$WORK/state1/worktrees/ask-aaa" ] || fail "--ready-json cut a worktree"
ok "--ready-json cuts no worktree and dispatches no agent"

# ===========================================================================
# PART B -- the contrast: a REAL round must still refuse the same environment
# ===========================================================================

# --- 5. --apply with a holding brake still stops at 3 ---------------------
run_worker state2 "$WORK/breaker-pause.sh" --apply --issue ASK-AAA --limit 1
RC_BRAKE=$?
[ "$RC_BRAKE" = "3" ] \
  || fail "the brake no longer stops a real round (rc=$RC_BRAKE). A ready-json fix
      that disables the brake for every run is worse than the bug it fixed."
[ -s "$WORK/breaker-calls.txt" ] \
  || fail "a real --apply round did not consult the usage breaker at all"
ok "--apply still consults the brake and still stops at exit 3"

# --- 6. --apply with a broken fetch still pages and exits 9 ---------------
run_worker state3 "/usr/bin/true" --apply --issue ASK-AAA --limit 1
RC_FETCH=$?
[ "$RC_FETCH" = "9" ] \
  || fail "a failed git fetch no longer exits 9 on a real round (rc=$RC_FETCH):
      $(grep -i infra "$WORK/err.txt" "$WORK/out.txt" | head -1)"
[ -s "$WORK/pages.txt" ] \
  || fail "a failed git fetch no longer pages on a real round; the ready-json fix
      silenced the guard instead of scoping it"
grep -qi "fetch" "$WORK/pages.txt" \
  || fail "the page no longer names the cause: $(head -1 "$WORK/pages.txt")"
ok "--apply still pages and exits 9 on a failed fetch"

echo "PASS ($PASS checks)"
