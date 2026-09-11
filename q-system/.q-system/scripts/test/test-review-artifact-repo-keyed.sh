#!/usr/bin/env bash
# Reproducer + acceptance for ASK-738 criterion 3: review artifacts are keyed by
# pr-<number> alone, so two repos with the same PR number consume each other's
# records.
#
# THE DEFECT: pr-review-agent.sh writes
#   $VERDICT_DIR/pr-<N>.verdict.json          (the record the gates read)
#   $ENGINE_DIR/pr-<N>-<timestamp>.md         (the review prose + round counter)
#   $HOME/.config/kipi/review-trees/pr-<N>    (the isolated tree)
# and converge.sh:41 / linear-worker.sh:96 read $STATE_DIR/pr-reviews/pr-<N>.verdict.json.
# Every one of those paths is keyed by PR NUMBER ONLY, in one shared state dir.
# PR #42 in kipi-system and PR #42 in a client repo are the same three paths.
#
# WHAT THAT COSTS: the second review overwrites the first, so the worker's
# severity-floor gate can read an APPROVE earned by a different repository's code
# and skip the rework round -- or arm auto-merge on the strength of it. The
# review-trees collision is worse still: one detached worktree path, re-checked
# out to a sha from whichever repo asked last.
#
# THIS TEST DRIVES THE REAL WRITER twice, once per repo, same PR number, and
# asks whether both records survive AND whether each one carries its own repo's
# commit. Asserting file COUNT alone would pass on a writer that kept two files
# with the wrong contents, so the sha is asserted per record.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SRC_DIR="$ROOT/q-system/.q-system/scripts"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

REAL_GIT="$(command -v git)" || fail "git not on PATH"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_TARGET_REPO KIPI_REVIEW_ENGINE 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home"

SLUG_A="assafkip/repo-alpha"
SLUG_B="assafkip/repo-beta"

mkrepo() {  # mkrepo <dir> <name> <marker>
  git init -q --bare "$WORK/origin-$2.git"
  git -C "$WORK/origin-$2.git" symbolic-ref HEAD refs/heads/main
  git init -q "$1"
  git -C "$1" config "url.$WORK/origin-.insteadOf" "https://github.com/assafkip/"
  echo "$3" > "$1/WHOSE_CODE.txt"
  G -C "$1" add -A; G -C "$1" commit -q -m "c1 $2"
  git -C "$1" branch -M main
  git -C "$1" remote add origin "https://github.com/assafkip/$2.git"
  git -C "$1" push -q -u origin main
}
mkdir -p "$WORK/skel/q-system/.q-system/scripts"
mkrepo "$WORK/skel"  repo-alpha ALPHA_CODE
mkrepo "$WORK/beta"  repo-beta  BETA_CODE
cp "$SRC_DIR/pr-review-agent.sh" "$SRC_DIR/pr-verdict-lib.sh" "$WORK/skel/q-system/.q-system/scripts/"
[ -f "$SRC_DIR/repo-slug-lib.sh" ] && cp "$SRC_DIR/repo-slug-lib.sh" "$WORK/skel/q-system/.q-system/scripts/"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "control code"
git -C "$WORK/skel" push -q origin main
AGENT="$WORK/skel/q-system/.q-system/scripts/pr-review-agent.sh"

cat > "$WORK/skel/instance-registry.json" <<JSON
{"instances":[
  {"name":"beta","path":"$WORK/beta","has_git":true,
   "dispatch":{"enabled":true,"expected_remote":"https://github.com/assafkip/repo-beta.git"}}
]}
JSON

SHA_A="$(git -C "$WORK/skel" rev-parse HEAD)"
SHA_B="$(git -C "$WORK/beta" rev-parse HEAD)"
[ "$SHA_A" != "$SHA_B" ] || fail "fixture: both repos share a sha, the collision is not observable"

GH_LOG="$WORK/gh.txt"; : > "$GH_LOG"
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
case "\$R" in
  "$SLUG_A") SHA="$SHA_A"; T="PR 42 alpha" ;;
  "$SLUG_B") SHA="$SHA_B"; T="PR 42 beta"  ;;
  *) exit 1 ;;
esac
case "\$*" in
  *"pr view"*"headRefOid"*) printf '%s\t%s\n' "\$SHA" "\$T" ;;
  *"pr diff"*)              echo "diff --git a/WHOSE_CODE.txt b/WHOSE_CODE.txt" ;;
  *"api"*)                  echo '{}' ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"
for e in codex claude; do
  printf '#!/usr/bin/env bash\necho "STUB %s"\nexit 0\n' "$e" > "$STUB/$e"; chmod +x "$STUB/$e"
done
export PATH="$STUB:$PATH"

run_review() {  # run_review <repo-path> <outfile>
  ( cd "$WORK/skel" \
    && HOME="$WORK/home" KIPI_STATE_DIR="$WORK/state" KIPI_NOTIFY="/usr/bin/true" \
       KIPI_TARGET_REPO="$1" \
       bash "$AGENT" 42 --issue ASK-AAA --engine codex ) >"$2" 2>&1
}

# ===========================================================================
# The two runs: SAME PR NUMBER, two different repositories.
# ===========================================================================
run_review "$WORK/skel" "$WORK/run-a.out"; RC_A=$?
run_review "$WORK/beta" "$WORK/run-b.out"; RC_B=$?
echo "  [ctx] run A: repo $WORK/skel (slug $SLUG_A, head ${SHA_A:0:8}) rc=$RC_A"
echo "  [ctx] run B: repo $WORK/beta (slug $SLUG_B, head ${SHA_B:0:8}) rc=$RC_B"

RECORDS="$(find "$WORK/home/.config/kipi/pr-reviews" -name '*.verdict.json' 2>/dev/null | sort)"
echo "  [ctx] verdict records on disk:"
printf '%s\n' "${RECORDS:-  <none>}" | sed 's/^/        /'

[ -n "$RECORDS" ] \
  || fail "neither run wrote a verdict record; the collision cannot be judged.
      run A tail: $(tail -5 "$WORK/run-a.out")
      run B tail: $(tail -5 "$WORK/run-b.out")"

# --- 1. both repos' records survive ----------------------------------------
COUNT="$(printf '%s\n' "$RECORDS" | grep -c .)"
[ "$COUNT" -ge 2 ] \
  || fail "ARTIFACT COLLISION: two reviews of PR #42 in two different repositories left $COUNT verdict record(s).
      The second overwrote the first. A gate reading this record cannot tell whose code earned the verdict.
      records: $(printf '%s' "$RECORDS" | tr '\n' ' ')"
ok "two repos' PR #42 records both survive ($COUNT records)"

# --- 2. each record carries ITS OWN repo's commit ---------------------------
# Count alone would pass on a writer that kept two files with swapped contents.
FOUND_A=0; FOUND_B=0
while IFS= read -r rec; do
  [ -n "$rec" ] || continue
  S="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("head_sha",""))' "$rec" 2>/dev/null)"
  [ "$S" = "$SHA_A" ] && FOUND_A=1
  [ "$S" = "$SHA_B" ] && FOUND_B=1
done <<< "$RECORDS"
[ "$FOUND_A" = "1" ] || fail "no verdict record carries repo-alpha's head $SHA_A"
[ "$FOUND_B" = "1" ] || fail "no verdict record carries repo-beta's head $SHA_B"
ok "each record carries its own repo's head sha"

# --- 3. the isolated review trees do not share one path ---------------------
TREES="$(find "$WORK/home/.config/kipi/review-trees" -maxdepth 2 -name '.git' 2>/dev/null | wc -l | tr -d ' ')"
TREE_A="$(grep -oE 'tree: [^ ]+' "$WORK/run-a.out" | head -1 | awk '{print $2}')"
TREE_B="$(grep -oE 'tree: [^ ]+' "$WORK/run-b.out" | head -1 | awk '{print $2}')"
if [ -n "$TREE_A" ] && [ -n "$TREE_B" ]; then
  [ "$TREE_A" != "$TREE_B" ] \
    || fail "TREE COLLISION: both repos' PR #42 reviews used the same worktree path $TREE_A.
      One detached tree re-checked out to whichever repo asked last is a review reading the wrong repository's files."
  ok "the two repos' review trees are distinct paths"
else
  echo "  note: one or both runs took the non-isolated fallback (A='${TREE_A:-none}' B='${TREE_B:-none}'); tree paths not asserted"
fi

echo "PASS ($PASS checks) test-review-artifact-repo-keyed.sh"
