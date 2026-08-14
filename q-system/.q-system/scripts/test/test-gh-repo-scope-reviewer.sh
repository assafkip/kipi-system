#!/usr/bin/env bash
# Reproducer + acceptance for call site 3 of ASK-738, the one that can approve
# the WRONG CODE: pr-review-agent.sh reviews the repo the SCRIPT lives in, not
# the repo the WORK is in.
#
# THE DEFECT: pr-review-agent.sh:66-67 derives
#   SKEL="$(cd "$SCRIPT_DIR/../../.." && pwd)"
# from BASH_SOURCE, so the review root follows the CODE. Every `gh` call is
# additionally unqualified, so the PR metadata comes from whatever repo the cwd
# points at. Dispatch a review of PR #42 in a target repo and both halves answer
# about the home repo instead. If #42 EXISTS at home -- and on a busy repo it
# does -- the reviewer reads home's tree, pins home's head sha, and posts a
# verdict and a `kipi/reviewer-approved` commit status. The wrong repo's code is
# reviewed and gets the verdict, with provenance that looks authoritative.
#
# THIS TEST MAKES THAT COLLISION CONCRETE rather than asserting an argv shape:
# PR #42 exists in BOTH repos at DIFFERENT head shas. The question the assertion
# asks is "whose commit did the reviewer pin?", which has exactly one right
# answer and is not satisfiable by accident.
#
# WHY A COPIED SKELETON. SKEL comes from the script's own location, so the only
# way to observe the derivation is to run a copy that lives in a fixture repo.
# The copy is byte-identical (cp of the shipping file), so this is the real
# script, not a rewrite of it.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SRC_DIR="$ROOT/q-system/.q-system/scripts"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$SRC_DIR/pr-review-agent.sh" ] || fail "pr-review-agent.sh missing at $SRC_DIR"
REAL_GIT="$(command -v git)" || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_TARGET_REPO KIPI_REVIEW_ENGINE 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home"

HOME_SLUG="assafkip/homerepo"
TARGET_SLUG="assafkip/targetrepo"

# --- two repos, each with a DISTINCT commit that could be "PR #42" ----------
mkrepo() {  # mkrepo <dir> <name> <marker-file>
  git init -q --bare "$WORK/origin-$2.git"
  git -C "$WORK/origin-$2.git" symbolic-ref HEAD refs/heads/main
  git init -q "$1"
  git -C "$1" config "url.$WORK/origin-.insteadOf" "https://github.com/assafkip/"
  echo "$3" > "$1/WHOSE_CODE.txt"
  G -C "$1" add -A; G -C "$1" commit -q -m "c1 in $2"
  git -C "$1" branch -M main
  git -C "$1" remote add origin "https://github.com/assafkip/$2.git"
  git -C "$1" push -q -u origin main
}
# The skeleton must carry the control code 3 levels down, or the script's own
# repo-root guard refuses before anything under test runs.
mkdir -p "$WORK/skel/q-system/.q-system/scripts"
mkrepo "$WORK/skel"   homerepo   HOME_REPO_CODE
mkrepo "$WORK/target" targetrepo TARGET_REPO_CODE
cp "$SRC_DIR/pr-review-agent.sh" "$SRC_DIR/pr-verdict-lib.sh" "$WORK/skel/q-system/.q-system/scripts/"
# The new shared derivation, if it exists yet, must travel with the copy.
[ -f "$SRC_DIR/repo-slug-lib.sh" ] && cp "$SRC_DIR/repo-slug-lib.sh" "$WORK/skel/q-system/.q-system/scripts/"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "control code"
git -C "$WORK/skel" push -q origin main
AGENT="$WORK/skel/q-system/.q-system/scripts/pr-review-agent.sh"

cat > "$WORK/skel/instance-registry.json" <<JSON
{"instances":[
  {"name":"targetproj","path":"$WORK/target","has_git":true,
   "dispatch":{"enabled":true,"expected_remote":"https://github.com/assafkip/targetrepo.git"}}
]}
JSON

SHA_HOME="$(git -C "$WORK/skel" rev-parse HEAD)"
SHA_TARGET="$(git -C "$WORK/target" rev-parse HEAD)"
[ "$SHA_HOME" != "$SHA_TARGET" ] || fail "fixture: both repos landed on the same sha, the collision is not observable"

# --- fake gh: cwd-bound like the real one, answers PER RESOLVED REPO --------
GH_LOG="$WORK/gh-resolved.txt"; : > "$GH_LOG"
cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
R=""; prev=""
for a in "\$@"; do
  case "\$prev" in -R|--repo) R="\$a" ;; esac
  prev="\$a"
done
if [ -z "\$R" ]; then
  url="\$("$REAL_GIT" config --get remote.origin.url 2>/dev/null)"
  R="\${url#https://github.com/}"; R="\${R%.git}"
  [ "\$R" = "\$url" ] && R="UNRESOLVED"
fi
printf '%s\t%s\n' "\$R" "\$*" >> "$GH_LOG"
# PR #42 EXISTS IN BOTH REPOS, at different heads. This is the collision.
case "\$R" in
  "$HOME_SLUG")   SHA="$SHA_HOME";   T="PR 42 in the HOME repo" ;;
  "$TARGET_SLUG") SHA="$SHA_TARGET"; T="PR 42 in the TARGET repo (ASK-AAA)" ;;
  *)              exit 1 ;;
esac
case "\$*" in
  *"pr view"*"headRefOid"*) printf '%s\t%s\n' "\$SHA" "\$T" ;;
  *"pr diff"*)              echo "diff --git a/WHOSE_CODE.txt b/WHOSE_CODE.txt" ;;
  *"api"*)                  echo '{}' ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"

# No model may run. Both engines are stubbed; a real one would be spend + network.
for e in codex claude; do
  printf '#!/usr/bin/env bash\necho "STUB %s ran"\nexit 0\n' "$e" > "$STUB/$e"
  chmod +x "$STUB/$e"
done
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

# ===========================================================================
# CASE 0 -- NEGATIVE SELF-TEST: the fake really does bind to cwd, and really
# does hand back a DIFFERENT sha per repo.
# ===========================================================================
P_HOME="$( cd "$WORK/skel"   && gh pr view 42 --json headRefOid,title -q '.headRefOid' 2>/dev/null | cut -f1 )"
P_TGT="$(  cd "$WORK/target" && gh pr view 42 --json headRefOid,title -q '.headRefOid' 2>/dev/null | cut -f1 )"
[ "$P_HOME" = "$SHA_HOME" ] \
  || fail "negative self-test: gh from the home checkout returned '${P_HOME:-<nothing>}', expected $SHA_HOME"
[ "$P_TGT" = "$SHA_TARGET" ] \
  || fail "negative self-test: gh from the target checkout returned '${P_TGT:-<nothing>}', expected $SHA_TARGET"
ok "negative self-test: PR #42 resolves to two different heads in the two repos"
: > "$GH_LOG"

# ===========================================================================
# CASE 1 -- review PR #42 of the TARGET, dispatched from the HOME cwd
# ===========================================================================
( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_STATE_DIR="$WORK/state" KIPI_NOTIFY="/usr/bin/true" \
     KIPI_TARGET_REPO="$WORK/target" \
     bash "$AGENT" 42 --issue ASK-AAA --engine codex ) >"$WORK/run.out" 2>&1
RC=$?

echo "  [ctx] cwd during the run: $WORK/skel (slug $HOME_SLUG, head ${SHA_HOME:0:8})"
echo "  [ctx] repo under review:  $WORK/target (slug $TARGET_SLUG, head ${SHA_TARGET:0:8})"
echo "  [ctx] reviewer rc: $RC"

VIEW_SLUGS="$(awk -F'\t' '$2 ~ /pr view/ {print $1}' "$GH_LOG" | sort -u)"
[ -n "$VIEW_SLUGS" ] \
  || fail "the reviewer made NO 'gh pr view' call (rc=$RC). It never reached the metadata read. Output:
$(tail -20 "$WORK/run.out")"

if printf '%s\n' "$VIEW_SLUGS" | grep -qx "$HOME_SLUG"; then
  fail "WRONG-REPO REVIEW at pr-review-agent.sh -- the PR metadata read resolved to the HOME repo ($HOME_SLUG) while the work is in $TARGET_SLUG.
      PR #42 exists in BOTH. The reviewer is about to read home's code and stamp a verdict on it as if it were the target's PR.
      gh calls:
$(sed 's/^/        /' "$GH_LOG")"
fi
[ "$VIEW_SLUGS" = "$TARGET_SLUG" ] \
  || fail "the PR metadata read resolved to '$VIEW_SLUGS', expected exactly $TARGET_SLUG"
ok "the PR metadata read is scoped to the repo under review ($TARGET_SLUG)"

# --- 2. THE SHA THE VERDICT WILL CARRY --------------------------------------
# The slug assertion above proves which repo was ASKED. This proves which repo's
# COMMIT the run adopted -- the thing the verdict record and the commit status
# are stamped with.
PINNED="$(grep -o 'head sha under review: [0-9a-f]*' "$WORK/run.out" | awk '{print $5}' | head -1)"
[ -n "$PINNED" ] || fail "the run never printed a head sha under review:
$(tail -20 "$WORK/run.out")"
if [ "$PINNED" = "$SHA_HOME" ]; then
  fail "FALSE PROVENANCE: the reviewer pinned the HOME repo's commit ($SHA_HOME) for a review of $TARGET_SLUG PR #42 (whose head is $SHA_TARGET).
      A verdict written against this sha names a commit in a repository nobody asked about."
fi
[ "$PINNED" = "$SHA_TARGET" ] \
  || fail "the reviewer pinned '$PINNED', which is neither repo's head (home $SHA_HOME, target $SHA_TARGET)"
ok "the verdict is pinned to the TARGET repo's commit (${SHA_TARGET:0:8})"

# --- 3. the tree it read from belongs to the target -------------------------
# The review root follows the WORK, not the script. WHOSE_CODE.txt differs
# between the repos, so the tree's own content answers this.
TREE="$(grep -oE 'tree: [^ ]+' "$WORK/run.out" | head -1 | awk '{print $2}')"
if [ -n "$TREE" ] && [ -f "$TREE/WHOSE_CODE.txt" ]; then
  WHOSE="$(cat "$TREE/WHOSE_CODE.txt")"
  [ "$WHOSE" = "TARGET_REPO_CODE" ] \
    || fail "the reviewer read files from a tree containing '$WHOSE'; a review of $TARGET_SLUG must read TARGET_REPO_CODE. tree=$TREE"
  ok "the review tree holds the TARGET repo's code ($TREE)"
else
  # Not a silent pass: say which branch ran, so a green line always names what
  # it actually checked.
  echo "  note: no isolated tree line in the output (reviewer took the fallback path); tree content not asserted this run"
fi

# --- 4. nothing in the run fell back to cwd ---------------------------------
LEAKED="$(awk -F'\t' -v h="$HOME_SLUG" '$1 == h' "$GH_LOG")"
[ -z "$LEAKED" ] \
  || fail "some gh call in the reviewer still resolves to the HOME repo:
$(printf '%s\n' "$LEAKED" | sed 's/^/        /')"
ok "no gh call in the reviewer fell back to cwd"

# ===========================================================================
# CASE 2 -- THE --repo FLAG, not the env var (PR #146 review, codex minor)
# ===========================================================================
# Case 1 drives KIPI_TARGET_REPO. Both forms feed one expression, so a bug that
# breaks only the FLAG is invisible to it -- and there was one: the resolution
# block sat ABOVE the argument loop, so it read TARGET_REPO_ARG before the loop
# parsed it and before the initialiser reset it to empty. `--repo` fell through
# to $SKEL silently. A flag with no test that exercises the flag is untested.
#
# The env var is explicitly UNSET here. Left set, this case would pass on the
# broken order for exactly the reason case 1 did.
: > "$GH_LOG"
( cd "$WORK/skel" \
  && env -u KIPI_TARGET_REPO \
     HOME="$WORK/home2" KIPI_STATE_DIR="$WORK/state2" KIPI_NOTIFY="/usr/bin/true" \
     bash "$AGENT" 42 --issue ASK-AAA --engine codex --repo "$WORK/target" \
) >"$WORK/run-flag.out" 2>&1
RC2=$?
echo "  [ctx] --repo flag run (KIPI_TARGET_REPO unset), rc=$RC2"

FLAG_SLUGS="$(awk -F'\t' '$2 ~ /pr view/ {print $1}' "$GH_LOG" | sort -u)"
[ -n "$FLAG_SLUGS" ] \
  || fail "the --repo run made no 'gh pr view' call (rc=$RC2):
$(tail -20 "$WORK/run-flag.out")"
if printf '%s\n' "$FLAG_SLUGS" | grep -qx "$HOME_SLUG"; then
  fail "DEAD FLAG: --repo $WORK/target was accepted and IGNORED -- the run resolved to the HOME repo ($HOME_SLUG).
      The resolution reads TARGET_REPO_ARG before the argument loop assigns it.
      gh calls:
$(sed 's/^/        /' "$GH_LOG")"
fi
[ "$FLAG_SLUGS" = "$TARGET_SLUG" ] \
  || fail "the --repo run resolved to '$FLAG_SLUGS', expected $TARGET_SLUG"
ok "the --repo FLAG scopes the review to the target ($TARGET_SLUG)"

PINNED2="$(grep -o 'head sha under review: [0-9a-f]*' "$WORK/run-flag.out" | awk '{print $5}' | head -1)"
[ "$PINNED2" = "$SHA_TARGET" ] \
  || fail "the --repo run pinned '$PINNED2', expected the target's head $SHA_TARGET"
ok "the --repo run pins the TARGET repo's commit"

echo "PASS ($PASS checks) test-gh-repo-scope-reviewer.sh"
