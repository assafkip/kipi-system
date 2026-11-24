#!/usr/bin/env bash
# A capped PR whose LAST round approved its CURRENT head gets that approval posted.
#
# THE SCAR (2026-11-24, consulting #644 and #645). Both were approved at round 3
# by a dry run (no --post), so kipi/reviewer-approved never reached GitHub and
# main's protection held them. Every later --post run hit the round cap, which
# refuses before any model call, and cap-ladder.py does not take an approved PR.
# Nothing moved them. The verdict existed; only its post was missing.
#
# WHAT RED LOOKS LIKE. Three dry approving rounds, then a --post run: before the
# fix it posts state=pending and never state=success. After the fix it posts
# success on the head sha, with 0 model calls and no cap marker.
#
# THE NEGATIVES carry the weight, because success is the one state that merges:
#   - record head_sha != the PR's current head: refused, pending, no success
#   - a REQUEST CHANGES record: refused, no success
#   - an unusable record: refused, no success
#   - no --post: nothing posted at all
#
# Isolation: HOME, KIPI_STATE_DIR, the repo, gh and claude are fixtures in a
# mktemp dir. No live PR is read and no model is spent.
set -uo pipefail
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
  *"pr view"*"headRefOid"*) printf '%s\t%s\n' "\$(cat "$WORK/pr-head" 2>/dev/null || echo "$SHA")" "a PR title" ;;
  *"pr diff"*)              echo "diff --git a/FILE.txt b/FILE.txt" ;;
  *"pr comment"*)           [ -s "$WORK/comment-fails" ] && exit 1; echo "https://github.com/example-owner/example-repo/pull/1#issuecomment-1" ;;
  *"commits/"*"/statuses"*) [ -s "$WORK/read-fails" ] && exit 1; cat "$WORK/cur-state" 2>/dev/null ;;
  *"statuses/"*)           [ -s "$WORK/post-fails" ] && exit 1; echo '{}' ;;
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
VERDICT: APPROVE WITH NITS
FINDINGS:
severity|file|line|what
minor|FILE.txt|1|a nit
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
run_reviewer() {  # run_reviewer <out-file> [extra args...]
  local out="$1"; shift
  ( cd "$WORK/skel" \
    && HOME="$WORK/home" KIPI_STATE_DIR="$WORK/state" KIPI_NOTIFY="$STUB/notify" \
       bash "$AGENT" 1 --engine claude "$@" ) >"$out" 2>&1
  echo $? > "$out.rc"
}

success_posts() { grep "statuses/" "$GH_LOG" | grep -v 'commits/' | grep -c 'state=success' || true; }
pending_posts() { grep "statuses/" "$GH_LOG" | grep -v 'commits/' | grep -c 'state=pending' || true; }

# Three dry approving rounds, as #644 got.
for n in 1 2 3; do run_reviewer "$WORK/r$n.out"; sleep 1; done
[ "$(calls)" = "3" ] || fail "the three dry rounds did not each call the model ($(calls) calls)"
[ "$(success_posts)" = "0" ] || fail "a dry round posted a status"
REC="$(find "$WORK" -name '*.verdict.json' | head -1)"
[ -n "$REC" ] || fail "no verdict record after three rounds"
python3 - "$REC" "$SHA" <<'PY' || fail "the round-3 record is not a usable approval on the head (control broken): $(cat "$REC")"
import json,sys
d=json.load(open(sys.argv[1]))
assert d["usable"] is True and d["verdict"].startswith("APPROVE") and d["head_sha"]==sys.argv[2], d
PY
cp "$REC" "$WORK/rec.good"
ok "control: three dry rounds left a usable APPROVE WITH NITS record on the head"

# NEGATIVE 1: the PR moved on since the approval. Must stay refused.
: > "$GH_LOG"; echo 1111111111111111111111111111111111111111 > "$WORK/pr-head"
before="$(calls)"; run_reviewer "$WORK/neg1.out" --post
[ "$(calls)" = "$before" ] || fail "a moved head called the model past the cap"
[ "$(success_posts)" = "0" ] || fail "an approval of an OLD head was posted onto the new head:
$(cat "$GH_LOG")"
[ "$(pending_posts)" -ge 1 ] || fail "a moved head did not take the normal cap path (pending):
$(cat "$GH_LOG")"
grep -q 'REFUSING' "$WORK/neg1.out" || fail "a moved head did not print the refusal"
grep -q 'head sha under review: 1111111111111111111111111111111111111111' "$WORK/neg1.out" \
  || fail "the stub did not move the head, so this negative is vacuous:
$(tail -20 "$WORK/neg1.out")"
rm -f "$WORK/pr-head"
for _m in $(find "$WORK/home" -name '.round-cap-*'); do rm -f "$_m"; done
ok "record head != PR head: refused, pending, no success"

# NEGATIVE 2: a REQUEST CHANGES record on the head.
python3 - "$REC" <<'PY'
import json,sys
d=json.load(open(sys.argv[1])); d["verdict"]=d["stated"]=d["derived"]="REQUEST CHANGES"
json.dump(d,open(sys.argv[1],"w"))
PY
: > "$GH_LOG"; run_reviewer "$WORK/neg2.out" --post
[ "$(success_posts)" = "0" ] || fail "a REQUEST CHANGES record posted success:
$(cat "$GH_LOG")"
grep -q 'REFUSING' "$WORK/neg2.out" || fail "a REQUEST CHANGES record was not refused"
cp "$WORK/rec.good" "$REC"
for _m in $(find "$WORK/home" -name '.round-cap-*'); do rm -f "$_m"; done
ok "REQUEST CHANGES record: refused, no success"

# NEGATIVE 3: an unusable record.
python3 - "$REC" <<'PY'
import json,sys
d=json.load(open(sys.argv[1])); d["usable"]=False
json.dump(d,open(sys.argv[1],"w"))
PY
: > "$GH_LOG"; run_reviewer "$WORK/neg3.out" --post
[ "$(success_posts)" = "0" ] || fail "an unusable record posted success"
cp "$WORK/rec.good" "$REC"
for _m in $(find "$WORK/home" -name '.round-cap-*'); do rm -f "$_m"; done
ok "unusable record: refused, no success"

# NEGATIVE 4: no --post posts nothing, but says what --post would do.
: > "$GH_LOG"; run_reviewer "$WORK/neg4.out"
[ "$(success_posts)" = "0" ] || fail "a dry run posted success"
ok "no --post: nothing posted"

# POSITIVE: the #644 shape. Usable approval, head matches, --post.
: > "$GH_LOG"; before="$(calls)"; run_reviewer "$WORK/pos.out" --post
[ "$(calls)" = "$before" ] || fail "posting the recorded verdict called the model"
[ "$(cat "$WORK/pos.out.rc")" = "0" ] || fail "posting the recorded verdict exited $(cat "$WORK/pos.out.rc")"
grep "statuses/$SHA" "$GH_LOG" | grep -v 'commits/' | grep 'state=success' | grep -q 'context=kipi/reviewer-approved' \
  || fail "the recorded approval was not posted as kipi/reviewer-approved=success on the head:
$(cat "$GH_LOG")
$(tail -20 "$WORK/pos.out")"
[ "$(pending_posts)" = "0" ] || fail "pending was posted alongside the recorded approval"
grep -q 'recorded verdict' "$WORK/pos.out" || fail "the run did not say it posted the recorded verdict:
$(tail -20 "$WORK/pos.out")"
[ -z "$(find "$WORK/home" -name '.round-cap-*')" ] || fail "an approved PR was marked capped for cap-ladder.py"
ok "usable approval on the head: success posted from the record, 0 model calls, no cap marker"

echo "PASS ($PASS checks) test-review-cap-posts-recorded-verdict.sh"
