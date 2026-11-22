#!/usr/bin/env bash
# A capped PR that is closed and reopened must not get a fresh review count
# (ASK-5485, RULE-2026-11-19-A).
#
# THE DEFECT. On 2026-11-18 five capped PRs were closed and reopened from the same
# branch (#610, #619, #839, #847, #856) so pr-review-agent.sh counted 0 rounds again.
# The ruling: at the cap the route is cap-ladder.py (RCA), never a reopen.
#
# WHAT RED LOOKS LIKE. PR 1 is driven to the cap (3 model calls, then the marker).
# PR 2 on the same head branch, PR 1 CLOSED, must make 0 model calls and carry the
# reopen message. Remove the reopen block and PR 2 calls the stub: red. Controls: a
# PR for a different branch and issue still reaches the model; the successor the
# ladder itself opened (named in its state file) still reaches the model.
#
# Isolation: HOME, KIPI_STATE_DIR, CAP_LADDER_STATE, the repo, gh and claude are
# fixtures in a mktemp dir. No live PR is read and no model is spent.
set -uo pipefail
# NOT A BILLING TEST (ASK-4311). This suite stubs `claude` on PATH and tests its
# own subject, so its runs take the plan path: KIPI_FLEET_API_KEYS=0 makes the
# worker, the reviewer and the dispatcher call `env -u ANTHROPIC_API_KEY claude`
# exactly as before the fleet door. The door has its own suites
# (test_fleet_api_credit.py, test-dispatch-api-key-gate.sh, test-worker-usage-brake.sh).
export KIPI_FLEET_API_KEYS=0

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SRC_DIR="$ROOT/q-system/.q-system/scripts"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$SRC_DIR/pr-review-agent.sh" ] || fail "pr-review-agent.sh missing at $SRC_DIR"
REAL_GIT="$(command -v git)" || fail "git not on PATH"

WORK="$(mktemp -d)"
# THE LANE RULE READS NOTHING LIVE HERE (ASK-4095): an empty ticket table and
# lanes dir, so no run reaches Linear or the real ~/.config/kipi/lanes.
printf '{}' > "$WORK/lane-tickets.json"; mkdir -p "$WORK/lanes"
export KIPI_LANE_TICKETS="$WORK/lane-tickets.json" KIPI_LANES_DIR="$WORK/lanes"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_TARGET_REPO KIPI_REVIEW_ENGINE KIPI_REVIEW_PRIMARY_ENGINE KIPI_REVIEW_MAX_ROUNDS 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB"

mkdir -p "$WORK/skel/q-system/.q-system/scripts"
git init -q "$WORK/skel"
echo "code" > "$WORK/skel/FILE.txt"
cp "$SRC_DIR/pr-review-agent.sh" "$SRC_DIR/pr-verdict-lib.sh" "$SRC_DIR/repo-slug-lib.sh" \
   "$SRC_DIR/env-failure-lib.sh" "$SRC_DIR/reviewer-token-lib.sh" "$SRC_DIR/review-lean-lib.sh" \
   "$WORK/skel/q-system/.q-system/scripts/"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "control code"
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "https://github.com/example-owner/example-repo.git"
AGENT="$WORK/skel/q-system/.q-system/scripts/pr-review-agent.sh"
SHA="$(git -C "$WORK/skel" rev-parse HEAD)"

GH_LOG="$WORK/gh-calls.txt"; : > "$GH_LOG"
cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$GH_LOG"
case "\$*" in
  *"pr view"*"--json body"*) [ -e "$WORK/body-fails-\$3" ] && exit 1; cat "$WORK/body-\$3" 2>/dev/null ;;
  *"pr view"*"headRefName"*) cat "$WORK/meta-\$3" 2>/dev/null ;;
  *"pr view"*"headRefOid"*) printf '%s\t%s\n' "$SHA" "a PR title" ;;
  *"pr diff"*)              echo "diff --git a/FILE.txt b/FILE.txt" ;;
  *"pr comment"*)           [ -s "$WORK/comment-fails" ] && exit 1; echo "https://github.com/example-owner/example-repo/pull/1#issuecomment-1" ;;
  *"commits/"*"/statuses"*) [ -s "$WORK/read-fails" ] && exit 1; cat "$WORK/cur-state" 2>/dev/null ;;
  *"api"*)                  echo '{}' ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"

# The engine under count. A REQUEST CHANGES review, so every round is the kind
# that would send the loop back for another one.
CLAUDE_LOG="$WORK/claude-calls.txt"; : > "$CLAUDE_LOG"
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
echo call >> "$CLAUDE_LOG"
# An environmental failure: output with no findings block, as a provider blip leaves.
[ -s "$WORK/blip" ] && { echo "API Error: 529 overloaded"; exit 0; }
cat <<'REVIEW'
VERDICT: REQUEST CHANGES
FINDINGS:
severity|file|line|what
major|FILE.txt|1|still wrong
END FINDINGS
REVIEW
exit 0
EOF
chmod +x "$STUB/claude"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/codex"; chmod +x "$STUB/codex"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

NOTIFY_LOG="$WORK/notify.txt"; : > "$NOTIFY_LOG"
cat > "$STUB/notify" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$NOTIFY_LOG"
[ -s "$WORK/notify-fails" ] && exit 1
exit 0
EOF
chmod +x "$STUB/notify"
calls() { wc -l <"$CLAUDE_LOG" | tr -d ' '; }
PRNUM=1
run_reviewer() {  # run_reviewer <out-file> [extra args...]
  local out="$1"; shift
  ( cd "$WORK/skel" \
    && HOME="$WORK/home" KIPI_STATE_DIR="$WORK/state" KIPI_NOTIFY="$STUB/notify" \
       bash "$AGENT" "$PRNUM" --engine claude "$@" ) >"$out" 2>&1
  echo $? > "$out.rc"
}

for n in 1 2 3; do
  before="$(calls)"; PRNUM=1 run_reviewer "$WORK/r$n.out" --post; sleep 1
  [ "$(calls)" = "$((before + 1))" ] || fail "round $n did not reach the model once (control broken)"
done
PRNUM=1 run_reviewer "$WORK/r4.out" --post
[ -n "$(find "$WORK/home" -name '.round-cap-*')" ] || fail "PR 1 left no cap marker (control broken)"
ok "positive control: PR 1 reached the cap and left its marker"

export CAP_LADDER_STATE="$WORK/ladder-state.json"; printf '{}' > "$CAP_LADDER_STATE"
printf 'sana/ask-9\tCLOSED\tFix thing (ASK-9)\n' > "$WORK/meta-1"

# Reopen: PR 2, same branch, PR 1 closed while capped.
printf 'sana/ask-9\tOPEN\tFix thing (ASK-9)\n' > "$WORK/meta-2"
before="$(calls)"; : > "$GH_LOG"
PRNUM=2 run_reviewer "$WORK/p2.out" --post
[ "$(calls)" = "$before" ] || fail "a reopened capped branch reached the model:
$(tail -20 "$WORK/p2.out")"
grep -q 'reopens capped PR #1' "$WORK/p2.out" || fail "refusal does not name the reopen"
grep -q 'cap-ladder.py' "$WORK/p2.out" || fail "refusal does not name cap-ladder.py"
[ "$(cat "$WORK/p2.out.rc")" = "0" ] || fail "refusal must exit 0"
ok "same branch, earlier PR closed while capped: 0 model calls, names cap-ladder.py"

# Same issue on a different branch name is still a reopen.
printf 'other-branch\tOPEN\tFix thing again (ASK-9)\n' > "$WORK/meta-3"
before="$(calls)"
PRNUM=3 run_reviewer "$WORK/p3.out" --post
[ "$(calls)" = "$before" ] || fail "same issue on a new branch reached the model"
ok "same issue, new branch: refused"

# Fresh branch, different issue: reviewed.
printf 'sana/ask-77\tOPEN\tOther work (ASK-77)\n' > "$WORK/meta-4"
before="$(calls)"
PRNUM=4 run_reviewer "$WORK/p4.out" --post
[ "$(calls)" = "$((before + 1))" ] || fail "a different branch and issue was refused:
$(tail -20 "$WORK/p4.out")"
ok "different branch and issue: reviewed"

# The ladder's own successor is allowed.
printf '{"ASK-9":{"history":[{"rung":1,"new_pr":"https://github.com/example-owner/example-repo/pull/5"}]}}' > "$CAP_LADDER_STATE"
printf 'sana/ask-9\tOPEN\tFix thing (ASK-9)\n' > "$WORK/meta-5"
before="$(calls)"
PRNUM=5 run_reviewer "$WORK/p5.out" --post
[ "$(calls)" = "$((before + 1))" ] || fail "the successor cap-ladder.py opened was refused:
$(tail -20 "$WORK/p5.out")"
ok "successor named in the ladder state: reviewed"

# A successor that carries "Resumes #1." in its body is the ladder's, even when the
# ladder state names nothing (release() path, or a run killed before write_state).
printf '{}' > "$CAP_LADDER_STATE"
printf 'sana/ask-9\tOPEN\tFix thing (ASK-9)\n' > "$WORK/meta-6"
printf 'Ladder-successor: opened by cap-ladder.py\n\nbody\n' > "$WORK/body-6"
before="$(calls)"
PRNUM=6 run_reviewer "$WORK/p6.out" --post
[ "$(calls)" = "$((before + 1))" ] || fail "a successor with a Resumes #1 body was refused:
$(tail -20 "$WORK/p6.out")"
ok "Ladder-successor line one: reviewed with an empty ladder state"

# A hand-made body with no tag is refused, and the refusal names the override.
printf 'sana/ask-9\tOPEN\tFix thing (ASK-9)\n' > "$WORK/meta-7"
printf 'Just reopening this.\n' > "$WORK/body-7"
before="$(calls)"; : > "$GH_LOG"
PRNUM=7 run_reviewer "$WORK/p7.out" --post
[ "$(calls)" = "$before" ] || fail "an untagged hand-made reopen reached the model"
cp "$GH_LOG" "$WORK/gh-p7.txt"
grep -q 'delete .*round-cap' "$WORK/p7.out" || fail "refusal does not name the marker override"
ok "untagged reopen refused; refusal names the override"

# Line one only: the tag on line 3 is a hand-made reopen.
printf 'sana/ask-9\tOPEN\tFix thing (ASK-9)\n' > "$WORK/meta-8"
printf 'Reopening by hand.\n\nLadder-successor: opened by cap-ladder.py\n' > "$WORK/body-8"
before="$(calls)"
PRNUM=8 run_reviewer "$WORK/p8.out" --post
[ "$(calls)" = "$before" ] || fail "a tag on line 3 bypassed the reopen refusal"
ok "tag below line one: refused"

# Legacy Resumes #N on line one (successors already open) is still accepted.
printf 'sana/ask-9\tOPEN\tFix thing (ASK-9)\n' > "$WORK/meta-9"
printf 'Resumes #1. rest of body\n' > "$WORK/body-9"
before="$(calls)"
PRNUM=9 run_reviewer "$WORK/p9.out" --post
[ "$(calls)" = "$((before + 1))" ] || fail "a legacy Resumes #1 successor was refused"
ok "legacy Resumes #N on line one: reviewed"

# The legacy glob must match the capped PR's number: "Resumes #11." does not excuse PR 1.
printf 'sana/ask-9\tOPEN\tFix thing (ASK-9)\n' > "$WORK/meta-11"
printf 'Resumes #11. rest of body\n' > "$WORK/body-11"
before="$(calls)"
PRNUM=11 run_reviewer "$WORK/p11.out" --post
[ "$(calls)" = "$before" ] || fail "Resumes #11 excused a reopen of capped PR #1"
ok "legacy Resumes #N must name the capped PR: #11 does not excuse #1"

# The 140-char commit status keeps the override instruction (p7 was a --post refusal).
desc="$(grep 'description=' "$WORK/gh-p7.txt" | head -1 | sed 's/.*description=//')"
[ -n "$desc" ] || fail "no pending status was posted on the refusal"
[ "${#desc}" -le 140 ] || fail "status description is ${#desc} chars, over 140"
case "$desc" in *"delete .round-cap"*) ;; *) fail "truncation dropped the override text: $desc" ;; esac
ok "status description is at most 140 chars and keeps the override"

# UNKNOWN IS NOT NO PROOF (PR #866 round 3). A failed body read must not refuse the
# ladder's own successor or write the cap marker; it warns and the PR is reviewed.
printf 'sana/ask-9\tOPEN\tFix thing (ASK-9)\n' > "$WORK/meta-10"
: > "$WORK/body-fails-10"
before="$(calls)"
PRNUM=10 run_reviewer "$WORK/p10.out" --post
[ "$(calls)" = "$((before + 1))" ] || fail "a failed body read refused the PR:
$(tail -20 "$WORK/p10.out")"
[ -z "$(find "$WORK/home" -name '.round-cap-*-pr-10')" ] || fail "a failed body read wrote a cap marker"
grep -q 'WARN: could not read the body of PR #10' "$WORK/p10.out" || fail "failed body read did not warn"
ok "failed body read is unknown: reviewed, no marker, warned"

# Producer pin: the tag the reviewer reads is the one cap-ladder.py writes, whatever
# the caller (climb or release) passes as body.
# KIPI_NOTIFY stubbed: cap-ladder.py reaches slack-notify.sh, and this only imports it.
KIPI_NOTIFY=/usr/bin/true python3 -I - "$SRC_DIR/cap-ladder.py" <<'PYEOF' || fail "cap-ladder.py open_from_branch does not put the tag on line one"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("cap_ladder_under_test", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
calls = []
def fake_run(cmd, *a, **k):
    calls.append(cmd)
    return (0, "1") if "compare" in " ".join(cmd) else (0, "https://x/pull/9")
m.run = fake_run
ok, url = m.open_from_branch("o/r", "b", "t", "ASK-1 re-enters after its hold")
body = calls[-1][calls[-1].index("--body") + 1]
assert body.splitlines()[0] == m.LADDER_SUCCESSOR_TAG, body
assert m.LADDER_SUCCESSOR_TAG == "Ladder-successor: opened by cap-ladder.py"
PYEOF
ok "cap-ladder.py writes the tag on line one"

echo "PASS ($PASS checks) test-review-reopen-refused.sh"
