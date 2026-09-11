#!/usr/bin/env bash
# A LIVE index.lock is another writer, not debris: the updater waits for it,
# says which step is waiting, retries a commit that died on it, and refuses
# the instance only when the lock outlives the bound.
#
# 2026-09-06 14:30, consulting: the q-system commit landed, the config commit
# died seconds later on "Unable to create '.git/index.lock': File exists",
# and the instance was abandoned half-delivered. The holder was a peer
# session's `git status`, which takes that lock for a fraction of a second to
# refresh the index. The stale-lock deletion at the top of the instance loop
# only covers a crashed writer's leftover (sp-2c1bcc3f); a live writer needs a
# wait, not a delete (sp-523c1a25). The run marker written for the hook's
# half (sp-9306036e) is what lets this test hold the lock at exactly the
# right moment: the holder waits for the marker, then takes the lock, so the
# first index write of the run meets a live lock every time.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

# ------------------------------------------------------------------ the fixture
# The same skeleton-plus-instance shape test-kipi-update-system-state-commit.sh
# builds, minus its dirty-tree provocations: one clean instance whose
# q-system/tracked.md differs from the skeleton's, so the run has exactly one
# thing to stage and commit.
build() {
  local work="$1" sk="$work/skel" inst="$work/inst"
  mkdir -p "$sk/q-system/.q-system/scripts" "$sk/q-system/.q-system/state" \
           "$sk/q-system/hooks" "$sk/plugins/demo" "$sk/.claude/rules"
  for f in kipi-update.sh kipi-update-preserve-scan.py kipi-update-deletion-guard.py \
           validate-separation.py; do
    cp "$ROOT/$f" "$sk/$f"
  done
  # The two gates the updater is fail-closed on, plus the replica-divergence
  # gate when the checkout carries it (it disarms on this one-instance
  # population either way; test-kipi-update-system-state-commit.sh runs
  # without it).
  for f in propagation-leak-gate.py containment-targets.py fleet-replica-divergence.py; do
    if [ -f "$ROOT/q-system/.q-system/scripts/$f" ]; then
      cp "$ROOT/q-system/.q-system/scripts/$f" "$sk/q-system/.q-system/scripts/$f"
    fi
  done
  cp "$ROOT/q-system/hooks/auto-commit.py" "$sk/q-system/hooks/auto-commit.py"
  cat > "$sk/q-system/.q-system/state/propagation-leak-baseline.json" <<'JSON'
{
  "schema_version": 1,
  "blocking_classes": ["case_proof_gap", "client_identity", "dated_interaction",
                       "pricing", "relationship", "source_identity",
                       "sourced_interaction"],
  "classifier_sha256": null,
  "entries": []
}
JSON
  printf 'generic skeleton content\n' > "$sk/q-system/tracked.md"
  printf 'plugin v2\n' > "$sk/plugins/demo/content.txt"
  printf '# demo rule\n' > "$sk/.claude/rules/demo.md"
  ( cd "$sk" && G init -q -b main && G add -A -f && G commit -qm skel )
  printf '{"instances":[{"name":"testinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$inst" > "$sk/instance-registry.json"

  mkdir -p "$inst/q-system/.q-system" "$inst/plugins/demo" "$inst/.claude"
  printf 'instance state\n' > "$inst/q-system/tracked.md"
  printf 'plugin v1\n' > "$inst/plugins/demo/content.txt"
  ( cd "$inst" && G init -q -b main && G add -A -f && G commit -qm inst )
}

# The lock holder. It waits for the updater's run marker (written after the
# stale-lock cleanup, before any index write), takes index.lock, and releases
# it only after the updater has SAID it is waiting. That handshake is what
# makes the green case a test of the wait path rather than of timing: a
# build that never waits never prints the line, so the lock is never released
# and the run fails.
hold_lock() {
  local inst="$1" log="$2" release="$3"
  local marker="$inst/.git/kipi-update.run" lock="$inst/.git/index.lock"
  local spins=0
  while [ ! -f "$marker" ]; do
    sleep 0.1
    spins=$((spins + 1))
    [ "$spins" -gt 600 ] && return 0
  done
  : > "$lock"
  local release_on=""
  case "$release" in
    after-wait-line) release_on="waiting for index.lock at" ;;
    after-refusal) release_on="index.lock held past" ;;
  esac
  if [ -n "$release_on" ]; then
    spins=0
    while ! grep -q "$release_on" "$log" 2>/dev/null; do
      sleep 0.1
      spins=$((spins + 1))
      [ "$spins" -gt 600 ] && return 0
    done
    sleep 1
    rm -- "$lock"
  fi
}

# ------------------------------------------------------------------ property 1
assert_a_live_lock_is_waited_out_and_the_sync_lands() {
  local work sk inst; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  : > "$work/out"
  hold_lock "$inst" "$work/out" after-wait-line &
  local holder=$!
  KIPI_UPDATE_LOCK_WAIT_S=20 bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true
  wait "$holder" || true

  grep -q "waiting for index.lock at q-system sync staging" "$work/out" || \
    fail "the updater never said it was waiting: $(tail -n 20 "$work/out")"
  grep -q "Updated: 1" "$work/out" || \
    fail "the sync did not land after the lock cleared: $(tail -n 20 "$work/out")"
  # The q-system commit is followed by the config+plugins commit in this
  # fixture, so the sync commit is in the log, not necessarily at HEAD.
  #
  # Read the log into a variable and match the VARIABLE, never `git log |
  # grep -q`. Under this file's `set -euo pipefail`, grep -q exits on the
  # first match and closes its stdin, git log dies of SIGPIPE, and pipefail
  # makes the whole pipeline non-zero although the match happened. Measured
  # at about 1 failure in 11 runs (PR #314 review round 4).
  local subjects; subjects="$(G -C "$inst" log --format=%s)"
  case "$subjects" in
    *"sync q-system from skeleton"*) ;;
    *) fail "the q-system sync commit is not in the instance history: $subjects" ;;
  esac
  [ ! -f "$inst/.git/kipi-update.run" ] || fail "the run marker survived a successful run"
  [ ! -f "$inst/.git/index.lock" ] || fail "index.lock survived the run"
  echo "PASS: a live index.lock is waited out, the step is named, and the sync lands"
}

# ------------------------------------------------------------------ property 2
# The refusal path restores the checkpoint with git commands that take the
# SAME lock. When the writer lets go after the refusal, the restore waits it
# out and the tree is clean again; when it never lets go, the run says so in
# one loud line instead of pretending (PR #314 review, round 1: a silent
# no-op restore left the instance dirty and refused by every later run).
assert_a_lock_past_the_bound_refuses_the_instance_by_name_and_restores_the_tree() {
  local work sk inst; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  : > "$work/out"
  hold_lock "$inst" "$work/out" after-refusal &
  local holder=$!
  KIPI_UPDATE_LOCK_WAIT_S=3 bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true
  wait "$holder" || true

  grep -q "index.lock held past 3s at q-system sync staging" "$work/out" || \
    fail "the refusal does not name the bound and the step: $(tail -n 20 "$work/out")"
  grep -q "Failed:  1" "$work/out" || \
    fail "a lock past the bound did not fail the instance: $(tail -n 20 "$work/out")"
  local subject; subject="$(G -C "$inst" log -1 --format=%s)"
  [ "$subject" = "inst" ] || fail "a refused run left a commit behind: $subject"
  [ -z "$(G -C "$inst" status --porcelain)" ] || \
    fail "a refused run left the tree dirty after the lock cleared: $(G -C "$inst" status --porcelain)"
  [ ! -f "$inst/.git/kipi-update.run" ] || fail "the run marker survived a refused run"
  [ ! -f "$inst/.git/index.lock" ] || fail "index.lock survived the run"
  echo "PASS: a lock past the bound refuses the instance, names the step, commits nothing, and restores the tree once the lock clears"
}

assert_a_lock_that_never_clears_is_reported_not_papered_over() {
  local work sk inst; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  : > "$work/out"
  hold_lock "$inst" "$work/out" never &
  local holder=$!
  KIPI_UPDATE_LOCK_WAIT_S=2 bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true
  kill "$holder" 2>/dev/null || true
  wait "$holder" 2>/dev/null || true
  rm -f -- "$inst/.git/index.lock"

  grep -q "restore could NOT run: index.lock still held" "$work/out" || \
    fail "a restore that could not run was silent: $(tail -n 20 "$work/out")"
  grep -q "Failed:  1" "$work/out" || fail "the instance was not counted as failed"
  echo "PASS: when the writer never lets go, the restore says so loudly instead of no-op'ing"
}

# ------------------------------------------------------------------ property 2b
# The marker is also the one-run-per-instance lock: a live marker from another
# pid refuses the run and is left in place; only the writer's own marker is
# ever removed.
assert_a_live_foreign_marker_refuses_the_run_and_survives_it() {
  local work sk inst; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  sleep 300 &
  local other=$!
  printf '%s %s\n' "$other" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$inst/.git/kipi-update.run"
  bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true
  local owner; owner="$(cut -d' ' -f1 "$inst/.git/kipi-update.run" 2>/dev/null || echo gone)"
  kill "$other" 2>/dev/null || true
  wait "$other" 2>/dev/null || true

  grep -q "another fleet update is applying this instance right now (pid $other)" "$work/out" || \
    fail "a live foreign marker did not refuse the run: $(tail -n 15 "$work/out")"
  grep -q "Failed:  1" "$work/out" || fail "the overlapped instance was not counted as failed"
  [ "$owner" = "$other" ] || fail "the foreign marker was removed or rewritten (owner now: $owner)"
  [ "$(G -C "$inst" log -1 --format=%s)" = "inst" ] || fail "an overlapped run committed"
  echo "PASS: a live foreign marker refuses the run, names its pid, and is left for its owner"
}

assert_a_stale_foreign_marker_is_replaced_and_the_sync_lands() {
  local work sk inst; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  # A pid that is dead by construction: our own child, reaped before use.
  sleep 0 &
  local dead=$!
  wait "$dead" 2>/dev/null || true
  kill -0 "$dead" 2>/dev/null && fail "the dead-pid fixture is still alive; the case would not exercise the dead-pid branch"
  printf '%s %s\n' "$dead" "2026-01-01T00:00:00Z" > "$inst/.git/kipi-update.run"
  bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true
  grep -q "Updated: 1" "$work/out" || fail "a stale foreign marker blocked the run: $(tail -n 15 "$work/out")"
  [ ! -f "$inst/.git/kipi-update.run" ] || fail "the stale marker survived a successful run"
  echo "PASS: a stale foreign marker (dead pid or old stamp) is replaced and the sync lands"
}

# ------------------------------------------------------------------ property 3
# The mutant. Redefine wait_for_index_lock as a no-op just before the main loop
# (a later bash definition wins) and re-run the green case: the holder never
# sees the waiting line, never releases, and the first index write dies on the
# lock. If this stays green, property 1 was passing on timing, not on the wait.
assert_without_the_wait_the_green_case_goes_red() {
  local work sk inst; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  python3 - "$sk/kipi-update.sh" <<'PY'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
needle = "while IFS='|' read -r name path prefix itype declared; do"
assert text.count(needle) == 1, "main loop header moved; update the mutant"
text = text.replace(needle, "wait_for_index_lock() { return 0; }\n" + needle)
open(path, "w", encoding="utf-8").write(text)
PY
  : > "$work/out"
  hold_lock "$inst" "$work/out" after-wait-line &
  local holder=$!
  KIPI_UPDATE_LOCK_WAIT_S=20 bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true
  kill "$holder" 2>/dev/null || true
  wait "$holder" 2>/dev/null || true
  rm -f -- "$inst/.git/index.lock"

  if grep -q "Updated: 1" "$work/out"; then
    fail "the mutant without the wait still synced; property 1 is decoration"
  fi
  grep -q "Failed:  1" "$work/out" || \
    fail "the mutant neither synced nor failed the instance: $(tail -n 20 "$work/out")"
  echo "PASS: removing the wait makes the live-lock case red (the wait is load-bearing)"
}

# ------------------------------------------------------------------ property 4
# The retry half, exercised directly. The helper functions are extracted from
# the updater's own text, never restated here, so the test cannot drift from
# the code it pins (floor: the extraction is non-empty).
assert_a_commit_that_dies_on_the_lock_is_retried_and_other_errors_are_not() {
  local work; work="$(mktemp -d)"
  sed -n '/^index_lock_path() {$/,/^}$/p;/^wait_for_index_lock() {$/,/^}$/p;/^retry_on_index_lock() {$/,/^}$/p' \
    "$ROOT/kipi-update.sh" > "$work/helpers.sh"
  grep -q '^retry_on_index_lock() {' "$work/helpers.sh" || fail "could not extract retry_on_index_lock from kipi-update.sh"
  grep -q '^wait_for_index_lock() {' "$work/helpers.sh" || fail "could not extract wait_for_index_lock from kipi-update.sh"
  mkdir -p "$work/repo" && ( cd "$work/repo" && G init -q -b main )

  cat > "$work/case.sh" <<'SH'
set -euo pipefail
source "$1/helpers.sh"
LOCK_WAIT_S=5
LOCK_RETRY_MAX=3
counter="$1/count"
: > "$counter"
flaky_commit() {
  local repo="$1"
  echo x >> "$counter"
  if [ "$(wc -l < "$counter" | tr -d ' ')" -lt 3 ]; then
    echo "fatal: Unable to create '$repo/.git/index.lock': File exists." >&2
    return 128
  fi
  return 0
}
other_failure() {
  echo x >> "$counter"
  echo "error: pathspec 'nope' did not match any file(s) known to git" >&2
  return 1
}
case "$3" in
  flaky) retry_on_index_lock "$2" "unit commit" flaky_commit "$2" ;;
  other) retry_on_index_lock "$2" "unit commit" other_failure ;;
esac
SH
  local out rc
  out="$(bash "$work/case.sh" "$work" "$work/repo" flaky 2>&1)" && rc=0 || rc=$?
  [ "$rc" -eq 0 ] || fail "a commit that succeeds on attempt 3 returned rc=$rc: $out"
  [ "$(wc -l < "$work/count" | tr -d ' ')" -eq 3 ] || fail "expected 3 attempts, got $(wc -l < "$work/count")"
  echo "$out" | grep -q "attempt 1 of 3" || fail "attempt 1 was not logged: $out"
  echo "$out" | grep -q "attempt 2 of 3" || fail "attempt 2 was not logged: $out"

  out="$(bash "$work/case.sh" "$work" "$work/repo" other 2>&1)" && rc=0 || rc=$?
  [ "$rc" -eq 1 ] || fail "a non-lock failure did not return its own rc (got $rc): $out"
  [ "$(wc -l < "$work/count" | tr -d ' ')" -eq 1 ] || fail "a non-lock failure was retried"
  echo "$out" | grep -q "did not match" || fail "the original stderr was swallowed: $out"
  echo "PASS: a commit that dies on the live lock is retried up to the cap; any other error returns on attempt 1"
}

assert_a_commit_that_dies_on_the_lock_is_retried_and_other_errors_are_not
assert_a_live_lock_is_waited_out_and_the_sync_lands
assert_a_lock_past_the_bound_refuses_the_instance_by_name_and_restores_the_tree
assert_a_lock_that_never_clears_is_reported_not_papered_over
assert_a_live_foreign_marker_refuses_the_run_and_survives_it
assert_a_stale_foreign_marker_is_replaced_and_the_sync_lands
assert_without_the_wait_the_green_case_goes_red
