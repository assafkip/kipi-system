#!/bin/bash
# Pins that lessons-daily.sh's daily lesson commit goes THROUGH the repo's
# hooks (ASK-2290).
#
# Why this test exists: the persist step ran `git commit --no-verify`, so no
# pre-commit gate and no commit-msg gate ever saw the daily lesson commits.
# Its message named no Linear issue, so the linear-issue-ref gate would have
# refused it every night; --no-verify hid that, and `>/dev/null 2>&1 || true`
# hid everything else. A bypass on an unattended job is invisible by design.
#
# What it proves, against a hermetic temp repo. The commit-msg hook is the
# REAL linear-issue-ref-check.py (the one gate this message could fail; the
# client-name guard is not installed here); the pre-commit hook is a stub that records it
# ran (the production lefthook chain needs the whole repo, so it cannot run
# hermetically; what is pinned here is that the chain is no longer skipped):
#   1. the script names no --no-verify anywhere outside comments;
#   2. the pre-commit and commit-msg hooks actually RUN on the daily commit;
#   3. the commit lands with the REAL linear-issue-ref-check.py as its
#      commit-msg hook, so the message passes that gate on its own merits;
#   4. negative control: a refusing commit-msg or pre-commit hook leaves NO
#      commit, the alert says so, and the job exits non-zero (the exit code is
#      this job's wire to Linear, ASK-182), and neither the Notion mirror nor
#      the fleet fan-out runs. On the pre-fix script this fails
#      too, because --no-verify committed straight past the refusal;
#   5. a run with nothing new to stage is NOT a failure (held lessons are
#      gitignored), so the exit-1 path cannot page on a quiet held-only night.
#
# Never touches the live repo, log, Slack, Linear ledger or fleet.
set -uo pipefail

# A hook that runs this test exports GIT_DIR; it outranks `git -C`, and the
# fixture commit would land in the REAL repo. Scrub before any git call.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR \
      GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_PREFIX

SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$SCRIPTS/lessons-daily.sh"
CHECKER="$SCRIPTS/linear-issue-ref-check.py"
PASS=0
FAIL=0

ok()  { echo "PASS  $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL  $1"; FAIL=$((FAIL + 1)); }

# --- 1. static: no --no-verify in executable lines -------------------------
# grep -c, not -q: under pipefail an early-exiting -q SIGPIPEs the left side
# and a FOUND match reads as not found (exit 141).
if [ "$(grep -vE '^[[:space:]]*#' "$SUT" | grep -ce '--no-verify')" != "0" ]; then
  bad "lessons-daily.sh commits with --no-verify"
else
  ok "lessons-daily.sh carries no --no-verify"
fi

# build_fixture <mode: real|refuse|refuse-precommit> -> echoes the temp root
build_fixture() {
  local mode="$1" tmp skel hooks
  tmp="$(mktemp -d)"
  skel="$tmp/skel"
  hooks="$skel/.git/hooks"
  mkdir -p "$skel/q-system/.q-system/scripts" "$skel/q-system/lessons" \
           "$skel/lesson-candidates" "$tmp/bin"
  cp "$SUT" "$skel/q-system/.q-system/scripts/lessons-daily.sh"
  cp "$CHECKER" "$skel/q-system/.q-system/scripts/linear-issue-ref-check.py"
  printf '# a lesson\n' > "$skel/q-system/lessons/fixture-lesson.md"
  printf '#!/bin/bash\nexit 0\n' > "$tmp/bin/claude"
  chmod +x "$tmp/bin/claude"

  git -C "$skel" init --quiet
  git -C "$skel" config user.email "test@example.com"
  git -C "$skel" config user.name "test"
  # A global core.hooksPath would silently skip .git/hooks; pin it locally.
  git -C "$skel" config core.hooksPath "$hooks"
  mkdir -p "$hooks"

  local pre_rc=0
  [ "$mode" = "refuse-precommit" ] && pre_rc=75   # verify.sh's collision code
  printf '#!/bin/bash\ntouch "%s/pre-commit.ran"\nexit %s\n' "$tmp" "$pre_rc" > "$hooks/pre-commit"
  if [ "$mode" != "refuse" ]; then
    printf '#!/bin/bash\ntouch "%s/commit-msg.ran"\nLINEAR_BYPASS_LEDGER="%s/bypass.jsonl" exec python3 "%s/q-system/.q-system/scripts/linear-issue-ref-check.py" "$1"\n' \
      "$tmp" "$tmp" "$skel" > "$hooks/commit-msg"
  else
    printf '#!/bin/bash\ntouch "%s/commit-msg.ran"\necho "fixture: refused" >&2\nexit 1\n' "$tmp" > "$hooks/commit-msg"
  fi
  chmod +x "$hooks/pre-commit" "$hooks/commit-msg"
  printf '%s' "$tmp"
}

# run_job <tmp> [distill-json]; sets JOB_RC. Alerts land in <tmp>/notify.txt.
PUBLISHED='{"scanned": 1, "published": ["a lesson"], "held": []}'
run_job() {
  local tmp="$1" summary="${2:-$PUBLISHED}"
  printf '%s' "$summary" > "$tmp/summary.json"
  PATH="$tmp/bin:$PATH" \
  KIPI_DISTILL_CMD="cat '$tmp/summary.json'" \
  KIPI_PROPAGATE_CMD="touch '$tmp/propagated'" \
  KIPI_NOTION_SYNC_CMD="touch '$tmp/notion-synced'" \
  KIPI_NOTIFY_CMD="printf '%s\\n' \"\$1\" >> '$tmp/notify.txt'" \
  KIPI_LESSONS_LOG="$tmp/lessons-daily.log" \
  KIPI_STREAK_FILE="$tmp/streak.json" KIPI_ESCALATIONS_FILE="$tmp/esc.jsonl" \
    bash "$tmp/skel/q-system/.q-system/scripts/lessons-daily.sh" >/dev/null 2>&1
  JOB_RC=$?
}

commits() { git -C "$1/skel" rev-list --count HEAD 2>/dev/null || echo 0; }

# --- 2 + 3. real checker as commit-msg hook --------------------------------
T="$(build_fixture real)"
run_job "$T"
# Print the target's identity so a fixture that silently failed setup cannot
# pass as the thing under test.
echo "      fixture: $T/skel (commits=$(commits "$T"))"
[ -f "$T/pre-commit.ran" ] && ok "pre-commit hook ran on the daily commit" \
                           || bad "pre-commit hook never ran on the daily commit"
[ -f "$T/commit-msg.ran" ] && ok "commit-msg hook ran on the daily commit" \
                           || bad "commit-msg hook never ran on the daily commit"
if [ "$(commits "$T")" = "1" ]; then
  ok "daily commit landed through the real linear-issue-ref-check hook"
  MSGF="$T/landed-msg"
  git -C "$T/skel" log -1 --format=%B > "$MSGF"
  if LINEAR_BYPASS_LEDGER="$T/direct.jsonl" python3 "$CHECKER" "$MSGF" >/dev/null 2>&1; then
    ok "landed message passes linear-issue-ref-check on its own"
  else
    bad "landed message fails linear-issue-ref-check: $(head -1 "$MSGF")"
  fi
  case "$(cat "$MSGF")" in
    *"—"*) bad "commit message carries an emdash" ;;
    *)     ok "commit message carries no emdash" ;;
  esac
  [ "$JOB_RC" -eq 0 ] && ok "clean run exits 0" || bad "clean run exits $JOB_RC"
  [ -e "$T/propagated" ] && ok "clean run still propagates" || bad "clean run did not propagate"
else
  bad "daily commit did not land; log: $(tail -3 "$T/lessons-daily.log" 2>/dev/null | tr '\n' ' ')"
fi
rm -rf "$T"

# --- 3b. a foreign staged file does not ride the lesson commit ------------
T="$(build_fixture real)"
printf 'x\n' > "$T/skel/foreign.txt"; git -C "$T/skel" add foreign.txt
run_job "$T"
if git -C "$T/skel" show --name-only --format= HEAD 2>/dev/null | grep -qx foreign.txt; then
  bad "foreign staged file rode the lesson commit"
else
  ok "lesson commit carries only lesson paths (commits=$(commits "$T"))"
fi
rm -rf "$T"

# --- 4. negative control: a refusing hook must stop the commit, loudly ----
for mode in refuse refuse-precommit; do
  T="$(build_fixture "$mode")"
  run_job "$T"
  echo "      fixture ($mode): $T/skel (commits=$(commits "$T"), exit=$JOB_RC)"
  [ "$(commits "$T")" = "0" ] && ok "$mode: no commit lands" \
                              || bad "$mode: commit landed past a refusing hook"
  grep -q 'lessons commit did not land' "$T/lessons-daily.log" 2>/dev/null \
    && ok "$mode: job log records the refused commit" \
    || bad "$mode: job log is silent about the refused commit"
  grep -q 'lessons commit FAILED' "$T/notify.txt" 2>/dev/null \
    && ok "$mode: alert names the refused commit" \
    || bad "$mode: alert is silent about the refused commit"
  [ "$JOB_RC" -ne 0 ] && ok "$mode: job exits non-zero" \
                      || bad "$mode: job exits 0 after a refused commit"
  [ ! -e "$T/propagated" ] && [ ! -e "$T/notion-synced" ] \
    && ok "$mode: refused lessons are not propagated or mirrored" \
    || bad "$mode: refused lessons still shipped (propagated or mirrored)"
  rm -rf "$T"
done

# --- 5. nothing to stage is a quiet night, not a failure -------------------
T="$(build_fixture real)"
git -C "$T/skel" add -A && git -C "$T/skel" commit -qm "seed [no-issue: fixture]" >/dev/null 2>&1
run_job "$T" '{"scanned": 1, "published": [], "held": ["h"]}'
echo "      fixture (held-only): $T/skel (commits=$(commits "$T"), exit=$JOB_RC)"
[ "$(commits "$T")" = "1" ] && [ "$JOB_RC" -eq 0 ] \
  && ok "held-only run with nothing staged exits 0, no new commit" \
  || bad "held-only run: commits=$(commits "$T") exit=$JOB_RC (want 1 and 0)"
rm -rf "$T"

echo "---"
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
