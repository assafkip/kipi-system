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
trap 'git -C "$REPO" worktree prune >/dev/null 2>&1 || true; rm -rf "$W"' EXIT
REPO="$W/repo"
S="$REPO/q-system/.q-system/scripts"
mkdir -p "$S/test" "$W/bin" "$W/home"

# The two scripts under test, from the working tree or from a ref. Both come from
# the SAME source: the reviewer sources the lib, and mixing an old reviewer with a
# new lib would test a combination that never shipped.
for f in pr-review-agent.sh pr-verdict-lib.sh repo-slug-lib.sh; do
  if [ -n "$REF" ]; then
    # repo-slug-lib.sh did not exist before ASK-738, so a ref older than it has
    # nothing to show. Fall back to the working-tree copy rather than failing:
    # the hatch exists to run an OLD reviewer, and an old reviewer never sources
    # this file, so the extra copy is inert there.
    git -C "$ROOT" show "$REF:q-system/.q-system/scripts/$f" > "$S/$f" 2>/dev/null \
      || cp "$SRC_SCRIPTS/$f" "$S/$f" \
      || fail "cannot read $f at ref $REF or from the working tree"
  else
    cp "$SRC_SCRIPTS/$f" "$S/$f" || fail "cannot copy $f from the working tree"
  fi
done
REVIEWER="$S/pr-review-agent.sh"
PRIMARY_MARKER="$(sed -n 's/.*KIPI_REVIEW_ENGINE:-\([a-z][a-z]*\)}.*/\1/p' "$REVIEWER" | head -1)"
[ -n "$PRIMARY_MARKER" ] || { echo "cannot read KIPI_REVIEW_ENGINE's default out of $REVIEWER; refusing to guess which engine this suite should expect" >&2; exit 1; }
PRIMARY_MARKER="$PRIMARY_MARKER-ran"
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

# WHICH MARKER MEANS "THE REVIEWER ACTUALLY RAN" IS DERIVED, NOT HARD-CODED.
# This suite asks an engine-AGNOSTIC question -- does the reviewer materialise the
# right tree and review THAT -- so pinning the engine by name made it go red on the
# 2026-09-06 codex->claude flip for a reason that has nothing to do with what it
# tests. It is read from pr-review-agent.sh's OWN KIPI_REVIEW_ENGINE default so the
# two cannot drift. Empty (the line moved or was reshaped) is a hard stop rather
# than a default, because a marker nothing ever touches makes every `[ -f ]` below
# fail with a message about the reviewer -- a wrong diagnosis is worse than a stop.

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
      SYNC_CALL_LOG="${SYNC_CALL_LOG:-$d/sync-calls-unused.log}" \
      bash "$REVIEWER" 901 "$@" ) >"$d/out.txt" 2>"$d/err.txt"
  RC=$?
  CASE_DIR="$d"
}

record() { echo "$1/home/.config/kipi/pr-reviews/pr-901.verdict.json"; }

# --- case 1: the defect. A real object that is not in this tree's history. -----
run_case refuse "$ORPHAN"
# CONTRACT INVERTED BY sp-8f95bba0 (2026-07-30). The reviewer now materialises a
# DETACHED WORKTREE at the exact PR head before reading anything, so "a real object
# not in this tree's history" is no longer a reason to refuse -- a tree holding
# that commit is built on demand, and the provenance is correct by construction
# rather than by search. The refusal that remains is for a MISSING object, which is
# the only case where no tree can be built (case 1b below).
#
# The original assertion is kept, inverted, rather than deleted: it is the record
# of what the guard used to have to do and why it no longer does.
[ "$RC" -eq 0 ] || fail "REGRESSION: the reviewer refused PR #901 at $ORPHAN, but that object EXISTS
      locally, so a detached worktree can be built at it and the provenance is correct by
      construction. Refusing here wastes a reviewable PR. stderr was:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
ok "a present-but-unreachable head is reviewed, not refused (worktree built on demand)"

grep -q 'detached at' "$CASE_DIR/out.txt" \
  || fail "the reviewer did not report an isolated worktree, so it read SOME tree it happened to be
      standing in -- the sp-8f95bba0 defect. stdout was:
$(sed 's/^/        /' "$CASE_DIR/out.txt")"
ok "the review runs in a detached worktree, named on stdout"

grep -q 'review-trees' "$CASE_DIR/out.txt" \
  || fail "the tree is not under review-trees/, so it may be a checkout someone else is using"
ok "the tree is a dedicated review tree, not a live checkout"

[ -f "$CASE_DIR/$PRIMARY_MARKER" ] \
  || fail "the PRIMARY engine never ran on a PR whose head is materialisable, so the PR goes unreviewed"
ok "the PRIMARY engine IS dispatched once the tree is isolated"

# case 1b removed: it asserted a refusal on a MISSING object that this suite's own
# case 3 correctly forbids (a stale clone cannot prove ancestry either way, and
# every test-severity-floor.sh reviewer case reports a fabricated sha). Isolation
# improves the present-object path; the absent-object path keeps tier 1.

# --- case 2: the negative self-test. The guard must let a real head through. ---
run_case allow "$REAL_HEAD"
[ -f "$CASE_DIR/$PRIMARY_MARKER" ] \
  || fail "THE GUARD REFUSES EVERYTHING. Its own tree's HEAD ($REAL_HEAD) did not reach the reviewer, so
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
[ -f "$CASE_DIR/$PRIMARY_MARKER" ] || fail "the unknown-object case did not reach the reviewer"
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

[ -f "$CASE_DIR/$PRIMARY_MARKER" ] \
  || fail "the reviewer did not refuse, but codex was never dispatched either, so the autonomous
      path still produces no review. stdout was:
$(sed 's/^/        /' "$CASE_DIR/out.txt")"
ok "codex is dispatched for the worktree-held head"

# The tree it names is now its OWN detached review tree, not whichever existing
# worktree happened to hold the sha (sp-8f95bba0). The assertion's intent is
# unchanged -- a log reader must be able to tell which tree was read -- but naming
# $W/wt specifically was over-specified once the reviewer stopped borrowing other
# people's checkouts.
grep -qE 'tree: .*review-trees.*detached at' "$CASE_DIR/out.txt" \
  || fail "codex ran but the reviewer never named an isolated tree. Without that line there is no
      way to tell from a log whether it read the PR's files or someone's working copy. stdout was:
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


# --- case 6: the success path posts to the issue EXACTLY ONCE (PR #46 round 1) ---
# codex round 1 of PR #46, major 1. Making the failure path loud (case 5) was done by
# editing the tail of the existing `python3 "$SYNC" progress` call. The opening lines
# were left behind, and their trailing `\` continued into the new comment block -- so
# the original call still ran, but stripped of `--agent` and `--evidence`. The success
# path posted TWICE: once misattributed to the default agent with no findings, then
# once correctly. Both are PERMANENT Linear comments. It shipped to ASK-221 before
# codex caught it, and case 5 could not see it because case 5 only exercises FAILURE.
#
# ORDER MATTERS: this runs AFTER case 5 on purpose. Case 5's failure has to be a real
# missing linear-sync.py rather than a stub told to fail, so the stub cannot exist
# until case 5 is done.
cat > "$S/linear-sync.py" <<'PYEOF'
import sys, os
with open(os.environ["SYNC_CALL_LOG"], "a") as fh:
    # ONE LINE PER CALL: the review body is multi-line, so joining raw argv makes a
    # single call span several lines and `grep -c .` counts lines, not calls. That
    # miscount read 3 for a correct single call.
    fh.write("\x1f".join(a.replace("\n", "\\n") for a in sys.argv[1:]) + "\n")
print("ASK-901: progress noted (stub)")
PYEOF

SYNC_LOG="$W/sync-calls.log"; : > "$SYNC_LOG"
SYNC_CALL_LOG="$SYNC_LOG" run_case postone "$REAL_HEAD" --post --issue ASK-901

CALLS="$({ grep -c . "$SYNC_LOG" 2>/dev/null || echo 0; } | head -1)"
[ "$CALLS" -eq 1 ] \
  || fail "THE DEFECT: the success path made $CALLS calls to linear-sync.py, not 1. Each one is a
      PERMANENT comment on the issue. Calls were:
$(sed 's/\x1f/ /g; s/^/        /' "$SYNC_LOG" 2>/dev/null)"
ok "the success path posts to the issue exactly once"

# The AGENT LABEL follows the engine for the same reason the marker above does:
# the property is "the thread can tell WHICH engine spoke", not "codex spoke".
grep -q "${PRIMARY_MARKER%-ran}-reviewer" "$SYNC_LOG" \
  || fail "the single call did not carry --agent ${PRIMARY_MARKER%-ran}-reviewer, so the issue thread cannot tell
      WHICH engine spoke -- the one fact the engine flip exists to convey. Call was:
$(sed 's/\x1f/ /g; s/^/        /' "$SYNC_LOG")"
ok "the call is attributed to the engine, not the default agent"

grep -q 'evidence' "$SYNC_LOG" \
  || fail "the single call carried no --evidence, so the findings never reach the issue and Sana
      has nothing to reply to. Call was:
$(sed 's/\x1f/ /g; s/^/        /' "$SYNC_LOG")"
ok "the call carries the findings as evidence"

grep -q 'review posted to ASK-901' "$CASE_DIR/out.txt" \
  || fail "the post succeeded but the run never said so. stdout was:
$(sed 's/^/        /' "$CASE_DIR/out.txt")"
ok "a successful post is reported once"

echo "PASS: $PASS/$PASS tree-guard checks"
