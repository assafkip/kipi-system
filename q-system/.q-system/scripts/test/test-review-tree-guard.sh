#!/usr/bin/env bash
# Reproducer for the tree-vs-PR-head guard in pr-review-agent.sh (ASK-221,
# sp-a72a9567). Pairs with the guard at pr-review-agent.sh:204-213.
#
# THE DEFECT IT PINS. $SKEL comes from the script's own location; the diff comes
# from `gh pr diff <N>`. Nothing compared them. Run from worktree A against a PR
# on branch B and codex reads A's files, then the verdict record and the commit
# status attribute A's findings to B's head sha. Observed live 2026-07-29: a run
# from the ask-221 worktree against PR #35 returned `codex_ran=yes` and
# `verdict: APPROVE` with three findings in a file PR #35 does not touch.
#
# WHY THIS FILE AND NOT A SECTION IN test-severity-floor.sh. That suite's whole
# reviewer harness reports `SHA_A=a1b2c3d4...`, a FABRICATED sha. `git cat-file -e`
# misses it, so every one of those cases takes the guard's tier-1 WARN branch and
# the REFUSAL branch is never executed. Reaching the refusal needs a sha that is a
# REAL object and NOT an ancestor -- which needs its own sandbox repo, because you
# cannot manufacture one inside a tree whose history the suite also asserts on.
#
# HOW THE NON-ANCESTOR IS MADE. `git commit-tree` on HEAD's tree with no parent:
# a real object in the store, reachable by cat-file, and not in HEAD's history.
# Deterministic and self-contained -- it does not depend on which remote branches
# happen to be fetched, which is what makes a "pick another branch's sha" version
# of this test pass or fail by accident on a fresh clone.
#
# NEGATIVE SELF-TEST (case 2). A guard that refuses everything would pass case 1
# while breaking every real review. Case 2 drives the SAME harness with the
# sandbox repo's actual HEAD and asserts codex DID run and a verdict WAS derived.
# Case 1 without case 2 is not evidence.
#
# Point it at an older copy to watch it fail:
#   KIPI_TEST_REVIEWER_REF=de2a9c3 bash test-review-tree-guard.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_SCRIPTS="$SCRIPT_DIR/.."
ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
REF="${KIPI_TEST_REVIEWER_REF:-}"

PASS=0
ok()   { PASS=$((PASS+1)); echo "  ok: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

command -v git >/dev/null 2>&1 || fail "git not on PATH"
command -v python3 >/dev/null 2>&1 || fail "python3 not on PATH (the record writer is a real python3 heredoc)"

W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
REPO="$W/repo"
S="$REPO/q-system/.q-system/scripts"
mkdir -p "$S/test" "$W/bin" "$W/home"

# The two scripts under test, from the working tree or from a ref. Both come from
# the SAME source: the reviewer sources the lib, and mixing an old reviewer with a
# new lib would test a combination that never shipped.
for f in pr-review-agent.sh pr-verdict-lib.sh; do
  if [ -n "$REF" ]; then
    git -C "$ROOT" show "$REF:q-system/.q-system/scripts/$f" > "$S/$f" \
      || fail "cannot read $f at ref $REF"
  else
    cp "$SRC_SCRIPTS/$f" "$S/$f" || fail "cannot copy $f from the working tree"
  fi
done
REVIEWER="$S/pr-review-agent.sh"
echo "reviewer under test: ${REF:-working tree} ($(wc -l < "$REVIEWER" | tr -d ' ') lines)"

# A sandbox git repo, so the guard has a real history to reason about and the
# founder's object store is never written to.
git -C "$REPO" init -q 2>/dev/null || fail "git init failed"
printf 'sandbox\n' > "$REPO/marker.txt"
git -C "$REPO" add -A >/dev/null 2>&1
git -C "$REPO" -c user.name=guardtest -c user.email=guard@test \
  commit -q -m "sandbox base" --no-verify >/dev/null 2>&1 \
  || fail "sandbox commit failed"
REAL_HEAD="$(git -C "$REPO" rev-parse HEAD)"
ORPHAN="$(git -C "$REPO" -c user.name=guardtest -c user.email=guard@test \
  commit-tree "$(git -C "$REPO" rev-parse 'HEAD^{tree}')" -m "non-ancestor" 2>/dev/null)"
[ -n "$ORPHAN" ] || fail "could not build a parentless commit with commit-tree"
ABSENT="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"

# The premises the whole test rests on, asserted rather than assumed.
git -C "$REPO" cat-file -e "${ORPHAN}^{commit}" 2>/dev/null \
  || fail "premise broken: the orphan commit is not in the sandbox object store"
git -C "$REPO" merge-base --is-ancestor "$ORPHAN" HEAD 2>/dev/null \
  && fail "premise broken: the orphan commit IS an ancestor of HEAD"
git -C "$REPO" cat-file -e "${ABSENT}^{commit}" 2>/dev/null \
  && fail "premise broken: the fabricated sha exists in the object store"
ok "premises: orphan ${ORPHAN:0:12} is a real object and not an ancestor; ${ABSENT:0:12} is absent"

# The notify stub RECORDS, because "did it page?" must be answered by a side
# effect. Case 5 asserts a page fired for a review that never reached the issue.
# $W is expanded HERE (unquoted heredoc) so the stub writes to the sandbox; "$*" is
# escaped so it stays a reference the stub evaluates at call time. Getting this
# backwards writes to /notify.log and the page assertion fails for the wrong reason.
cat > "$W/notify.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$W/notify.log"
exit 0
EOF
chmod +x "$W/notify.sh"
cat > "$W/review-body.txt" <<'EOF'
## VERDICT: APPROVE

Nothing survived reproduction.

FINDINGS:
END FINDINGS
EOF

# $1 = the sha `gh pr view` reports. The codex stub TOUCHES A MARKER: "did the
# reviewer dispatch?" has to be answered by a side effect, not by stdout prose --
# the live symptom was `codex_ran=yes` printed next to a bogus verdict, so prose
# is not admissible evidence here.
run_case() {
  local name="$1" oid="$2"; shift 2
  local d="$W/$name"; mkdir -p "$d/bin" "$d/home"
  cat > "$d/bin/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$d/gh-calls.log"
case "\$1 \$2" in
  "pr view") printf '$oid\ttree guard case $name\n' ;;
  "pr diff") printf 'diff --git a/marker.txt b/marker.txt\n' ;;
esac
exit 0
EOF
  cat > "$d/bin/codex" <<EOF
#!/usr/bin/env bash
: > "$d/codex-ran"
cat "$W/review-body.txt"
EOF
  cat > "$d/bin/claude" <<EOF
#!/usr/bin/env bash
: > "$d/claude-ran"
cat "$W/review-body.txt"
EOF
  chmod +x "$d/bin/gh" "$d/bin/codex" "$d/bin/claude"
  ( PATH="$d/bin:$PATH" HOME="$d/home" KIPI_NOTIFY="$W/notify.sh" \
      bash "$REVIEWER" 901 "$@" ) >"$d/out.txt" 2>"$d/err.txt"
  RC=$?
  CASE_DIR="$d"
}

record() { echo "$1/home/.config/kipi/pr-reviews/pr-901.verdict.json"; }

# --- case 1: the defect. A real object that is not in this tree's history. -----
run_case refuse "$ORPHAN"
[ "$RC" -ne 0 ] || fail "THE DEFECT: the reviewer exited 0 on PR #901 whose head $ORPHAN is NOT in
      this tree's history. Every finding it produced would cite code absent from that PR's diff,
      stamped with that PR's sha. stdout was:
$(sed 's/^/        /' "$CASE_DIR/out.txt")"
ok "a PR head that is not an ancestor of the tree exits non-zero"

grep -q 'REFUSING' "$CASE_DIR/err.txt" \
  || fail "it failed but never said why. stderr was:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
ok "the refusal names itself on stderr"

[ ! -f "$CASE_DIR/codex-ran" ] \
  || fail "THE EXPENSIVE HALF OF THE DEFECT: codex was DISPATCHED against the wrong tree before
      anything refused. The live 2026-07-29 run reported codex_ran=yes and verdict APPROVE this
      way. Refusing after the model has already spoken is not a guard."
ok "codex is never dispatched (the guard refuses BEFORE the model runs)"

[ ! -f "$CASE_DIR/claude-ran" ] \
  || fail "the Opus fallback ran on a refused tree, which would fill the required status slot with
      a review of the wrong code."
ok "the Opus fallback is not reached either"

[ ! -f "$(record "$CASE_DIR")" ] \
  || fail "a verdict record was written for a review that must not have happened:
      $(cat "$(record "$CASE_DIR")")"
ok "no verdict record is written"

grep -q 'statuses/' "$CASE_DIR/gh-calls.log" 2>/dev/null \
  && fail "a commit status was posted on a refused review. gh calls were:
$(sed 's/^/        /' "$CASE_DIR/gh-calls.log")"
ok "no commit status is posted (absent is not approved)"

# --- case 2: the negative self-test. The guard must let a real head through. ---
run_case allow "$REAL_HEAD"
[ -f "$CASE_DIR/codex-ran" ] \
  || fail "THE GUARD REFUSES EVERYTHING. Its own tree's HEAD ($REAL_HEAD) did not reach codex, so
      case 1 proves nothing -- a check that cannot pass is not a check. stderr was:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
ok "the tree's own HEAD reaches codex (the guard can pass, so case 1 is meaningful)"

grep -q 'REFUSING' "$CASE_DIR/err.txt" && fail "it refused its own HEAD"
[ -f "$(record "$CASE_DIR")" ] \
  || fail "no verdict record for the healthy case; the harness itself is broken above the guard.
      stdout:
$(sed 's/^/        /' "$CASE_DIR/out.txt")"
python3 -c 'import json,sys; v=json.load(open(sys.argv[1]))["verdict"]; sys.exit(0 if v=="APPROVE" else 1)' \
  "$(record "$CASE_DIR")" \
  || fail "the healthy case did not derive APPROVE from the stubbed review:
      $(cat "$(record "$CASE_DIR")")"
ok "the healthy case derives APPROVE and writes the verdict record"

# --- case 3: tier 1. An UNKNOWN object warns and proceeds, it does not refuse. --
# A stale or partial clone cannot prove ancestry either way. Inventing a refusal
# there would wedge the loop on a fetch problem -- and it is the branch every
# existing test-severity-floor.sh reviewer case actually takes.
run_case unknown "$ABSENT"
grep -q 'REFUSING' "$CASE_DIR/err.txt" \
  && fail "a sha that is merely ABSENT from the object store was treated as a mismatch. That wedges
      the whole loop on a stale clone, and it breaks every reviewer case in test-severity-floor.sh,
      all of which report a fabricated sha."
grep -q 'WARN' "$CASE_DIR/err.txt" \
  || fail "an unprovable tree/PR match proceeded SILENTLY. stderr was:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
[ -f "$CASE_DIR/codex-ran" ] || fail "the unknown-object case did not reach codex"
ok "an absent object warns out loud and proceeds (tier 1, not a refusal)"


# --- case 4: THE AUTONOMOUS CALL SHAPE (codex round 1 of PR #34, major) ---------
# Cases 1-3 all run the reviewer out of the same checkout whose HEAD they ask about,
# so they never exercised the shape the LIVE loop actually uses. linear-worker.sh
# runs `bash $SCRIPT_DIR/pr-review-agent.sh` from the MAIN checkout while the PR's
# commits sit in a worktree it cut under $STATE_DIR/worktrees/<issue>. $SKEL follows
# BASH_SOURCE, not cwd, so the reviewer asked main's HEAD about a branch commit,
# refused, and the worker logged `|| say WARN ... (the PR stands, unreviewed)`. The
# gate's success case was "the loop reviews nothing", silently.
#
# The commit here is a REAL object that is NOT an ancestor of $REPO's HEAD -- the
# same premise as case 1. What separates them is only whether some worktree holds
# it. Case 1 stays as this case's negative self-test: if the resolver ever devolved
# into "always proceed", case 1 goes red.
git -C "$REPO" worktree add -q -b feature "$W/wt" HEAD 2>/dev/null \
  || fail "could not add a linked worktree to the sandbox repo"
printf 'branch work\n' > "$W/wt/marker.txt"
git -C "$W/wt" add -A >/dev/null 2>&1
git -C "$W/wt" -c user.name=guardtest -c user.email=guard@test \
  commit -q -m "work on the branch" --no-verify >/dev/null 2>&1 \
  || fail "could not commit inside the linked worktree"
WT_HEAD="$(git -C "$W/wt" rev-parse HEAD)"

git -C "$REPO" merge-base --is-ancestor "$WT_HEAD" HEAD 2>/dev/null \
  && fail "premise broken: the worktree commit IS an ancestor of the main checkout's HEAD, so this
      case would pass even with no resolver at all"
git -C "$REPO" cat-file -e "${WT_HEAD}^{commit}" 2>/dev/null \
  || fail "premise broken: worktrees are supposed to share the object store, but the main checkout
      cannot see $WT_HEAD"
ok "premises: ${WT_HEAD:0:12} is visible from the main checkout and is NOT in its history"

run_case worktree "$WT_HEAD"
grep -q 'REFUSING' "$CASE_DIR/err.txt" \
  && fail "THE DEFECT: the reviewer REFUSED the autonomous call shape. The script lives in the main
      checkout and the PR head lives in a linked worktree, which is how linear-worker.sh:1133 calls
      it on every run. The worker swallows this as a WARN, so the real-world symptom is a loop that
      reviews nothing and says almost nothing. stderr was:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
ok "a PR head held by a linked worktree is not refused"

[ -f "$CASE_DIR/codex-ran" ] \
  || fail "the reviewer did not refuse, but codex was never dispatched either, so the autonomous
      path still produces no review. stdout was:
$(sed 's/^/        /' "$CASE_DIR/out.txt")"
ok "codex is dispatched for the worktree-held head"

grep -q "$W/wt" "$CASE_DIR/out.txt" \
  || fail "codex ran but the reviewer never named the tree it resolved to. Without that line there
      is no way to tell from a log whether it read the PR's files or main's. stdout was:
$(sed 's/^/        /' "$CASE_DIR/out.txt")"
ok "the resolved tree is named on stdout (provenance is auditable in the worker log)"

python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d["head_sha"]==sys.argv[2] else 1)' \
  "$(record "$CASE_DIR")" "$WT_HEAD" \
  || fail "the verdict record does not pin the worktree head it actually reviewed:
      $(cat "$(record "$CASE_DIR")")"
ok "the verdict record pins the worktree's head sha"


# --- case 5: a review that cannot reach the issue must not vanish (sp-583dc1a0) --
# codex round 2 of PR #34, minor. The Linear post ended in `>/dev/null 2>&1 || true`:
# every OTHER failure on the post path announces itself (the PR comment warns, a
# failed commit status warns that NO gate moved), but a failed Linear post printed
# nothing, threw the reason away, and the run still exited 0 and printed `done`.
# Linear is the one surface Sana reads. A silently lost review means the gate is set
# from findings she was never shown and the rework conversation never starts, while
# every log line says the run was fine.
#
# The harness has no linear-sync.py, so `python3 "$SYNC"` cannot succeed here. That
# is the whole fixture: the failure is real, not simulated with a flag.
run_case postloss "$REAL_HEAD" --post --issue ASK-901

[ "$RC" -eq 0 ]   || fail "the run exited $RC because the ISSUE post failed. The gate above it was already set
      from a review that really ran, so failing here makes the worker log \`codex reviewer failed\`
      for a review that succeeded. Loud, not fatal. stderr was:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
ok "a failed issue post does not fail the run (the gate it already set is legitimate)"

grep -q 'could not post the review to ASK-901' "$CASE_DIR/err.txt"   || fail "THE DEFECT: the review never reached ASK-901 and NOTHING said so. The run printed
      \`done\` and exited 0. Sana cannot answer findings she was never shown, and no log line
      reveals that the conversation never started. stderr was:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
ok "a failed issue post is announced on stderr, naming the issue"

grep -q 'no findings to answer\|cannot start\|Reason:' "$CASE_DIR/err.txt"   || fail "it warned, but without the CONSEQUENCE or the reason. An operator seeing this needs to
      know the gate moved without the findings landing, and why the post failed. stderr was:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
ok "the warning carries the consequence and the underlying reason"

grep -q 'did NOT reach ASK-901' "$W/notify.log" 2>/dev/null   || fail "no page fired. This happens in UNATTENDED runs, where stderr goes to a log nobody is
      watching -- that is exactly the case founder-notifications exists for. notify.log was:
$(sed 's/^/        /' "$W/notify.log" 2>/dev/null || echo '        (absent)')"
ok "a page fires, so an unattended loss is not invisible"

grep -q 'review posted to ASK-901' "$CASE_DIR/out.txt"   && fail "it claimed the review was posted to ASK-901 while the post actually failed. A false
      success line is worse than silence."
ok "it does not claim success for a post that failed"

echo "PASS: $PASS/$PASS tree-guard checks"
