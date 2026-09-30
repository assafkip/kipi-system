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
# What it proves, against a hermetic temp repo whose hooks are real scripts:
#   1. the script names no --no-verify anywhere outside comments;
#   2. the pre-commit and commit-msg hooks actually RUN on the daily commit;
#   3. the commit lands with the REAL linear-issue-ref-check.py as its
#      commit-msg hook, so the message passes that gate on its own merits;
#   4. negative control: a commit-msg hook that refuses leaves NO commit and
#      the job log says the commit did not land. On the pre-fix script this
#      case fails too, because --no-verify committed straight past the refusal.
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

# build_fixture <commit-msg mode: real|refuse> -> echoes the temp root
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

  printf '#!/bin/bash\ntouch "%s/pre-commit.ran"\nexit 0\n' "$tmp" > "$hooks/pre-commit"
  if [ "$mode" = "real" ]; then
    printf '#!/bin/bash\ntouch "%s/commit-msg.ran"\nLINEAR_BYPASS_LEDGER="%s/bypass.jsonl" exec python3 "%s/q-system/.q-system/scripts/linear-issue-ref-check.py" "$1"\n' \
      "$tmp" "$tmp" "$skel" > "$hooks/commit-msg"
  else
    printf '#!/bin/bash\ntouch "%s/commit-msg.ran"\necho "fixture: refused" >&2\nexit 1\n' "$tmp" > "$hooks/commit-msg"
  fi
  chmod +x "$hooks/pre-commit" "$hooks/commit-msg"
  printf '%s' "$tmp"
}

run_job() {
  local tmp="$1"
  PATH="$tmp/bin:$PATH" \
  KIPI_DISTILL_CMD='echo "{\"scanned\": 1, \"published\": [\"a lesson\"], \"held\": []}"' \
  KIPI_PROPAGATE_CMD='true' KIPI_NOTIFY_CMD='true' KIPI_NOTION_SYNC_CMD='true' \
  KIPI_LESSONS_LOG="$tmp/lessons-daily.log" \
  KIPI_STREAK_FILE="$tmp/streak.json" KIPI_ESCALATIONS_FILE="$tmp/esc.jsonl" \
    bash "$tmp/skel/q-system/.q-system/scripts/lessons-daily.sh" >/dev/null 2>&1
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
else
  bad "daily commit did not land; log: $(tail -3 "$T/lessons-daily.log" 2>/dev/null | tr '\n' ' ')"
fi
rm -rf "$T"

# --- 4. negative control: a refusing hook must stop the commit, visibly ----
T="$(build_fixture refuse)"
run_job "$T"
echo "      fixture: $T/skel (commits=$(commits "$T"))"
[ "$(commits "$T")" = "0" ] && ok "refusing commit-msg hook leaves no commit" \
                            || bad "commit landed past a refusing commit-msg hook"
grep -q 'lessons commit did not land' "$T/lessons-daily.log" 2>/dev/null \
  && ok "job log records the refused commit" \
  || bad "job log is silent about the refused commit"
rm -rf "$T"

echo "---"
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
