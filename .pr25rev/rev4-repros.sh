#!/usr/bin/env bash
# ROUND-4 REPRODUCERS against PR #25 HEAD (28ae526).
# Three independent scenarios, each printing its own PASS/FAIL line.
set -uo pipefail
TREEROOT="/Users/assafkipnis/.config/kipi/worktrees/ask-212"
WORKER="$TREEROOT/q-system/.q-system/scripts/linear-worker.sh"
REAL_PY="$(command -v python3)"
BASE="/Users/assafkipnis/projects/kipi-system/.pr25rev/rev4-$$"
mkdir -p "$BASE/home" "$BASE/bin"
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

STUB="$BASE/bin"
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"}],"total_open":1}\n'
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
if [ ! -s "$BASE/prompt.txt" ]; then cat > "$BASE/prompt.txt"; else cat >/dev/null; fi
printf 'ran\n' >> "$BASE/worked.txt"
exit 0
EOF
cat > "$BASE/notify.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$BASE/pages.txt"
EOF
chmod +x "$STUB/python3" "$STUB/claude" "$BASE/notify.sh"
export PATH="$STUB:$PATH"

gh_says() {
  cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
case "\$*" in
  "pr list"*)                            echo $1 ;;
  "pr view $1 --json mergeStateStatus"*) echo $2 ;;
esac
exit 0
EOF
  chmod +x "$STUB/gh"
}

make_repo() {   # make_repo <dir>
  local d="$1"; mkdir -p "$d"
  git init -q --bare "$d/origin"; git init -q "$d/skel"
  G -C "$d/skel" commit -q --allow-empty -m "base commit"
  git -C "$d/skel" branch -M main
  git -C "$d/skel" remote add origin "$d/origin"
  git -C "$d/skel" push -q -u origin main
  G -C "$d/skel" checkout -q -b sana/ask-aaa
  G -C "$d/skel" commit -q --allow-empty -m "the approved work (ASK-AAA)"
  git -C "$d/skel" push -q -u origin sana/ask-aaa
  G -C "$d/skel" checkout -q main
  git -C "$d/skel" update-ref -d refs/heads/sana/ask-aaa
  G -C "$d/skel" commit -q --allow-empty -m "main moved underneath the PR"
  git -C "$d/skel" push -q origin main
}

run() {  # run <skel> <state> <out>
  ( cd "$1" && HOME="$BASE/home" KIPI_SKEL="$1" KIPI_STATE_DIR="$2" \
      KIPI_NOTIFY="$BASE/notify.sh" bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >"$3" 2>&1
  return 0
}
ledger() { "$REAL_PY" -c "import json;d=json.load(open('$1'));print(json.dumps(d.get('ASK-AAA',{}),sort_keys=True))" 2>/dev/null || echo "{}"; }

echo "############ R1: the rebase-round prompt contradicts itself ############"
R1="$BASE/r1"; make_repo "$R1"
S1="$BASE/s1"; mkdir -p "$S1/pr-reviews"
printf '{"verdict":"APPROVE","pr":901}\n' > "$S1/pr-reviews/pr-901.verdict.json"
gh_says 901 DIRTY
: > "$BASE/prompt.txt"; : > "$BASE/worked.txt"; : > "$BASE/pages.txt"
run "$R1/skel" "$S1" "$BASE/r1.out"
echo "--- the two lines the dispatched agent reads, in prompt order:"
grep -nE "GitHub now reports its merge state|git rebase origin/main\$|already on branch .* off origin/main" "$BASE/prompt.txt" | sed 's/^/    /'
if grep -q "already on branch sana/ask-aaa off origin/main" "$BASE/prompt.txt"; then
  echo "R1 REPRODUCED: the rebase prompt asserts the tree is ALREADY off origin/main"
else
  echo "R1 not reproduced"
fi

echo
echo "############ R2: tree_paged is never cleared -> the 2nd stuck tree is silent ############"
R2="$BASE/r2"; make_repo "$R2"
S2="$BASE/s2"; mkdir -p "$S2/pr-reviews" "$S2/worktrees"
printf '{"verdict":"APPROVE","pr":902}\n' > "$S2/pr-reviews/pr-902.verdict.json"
gh_says 902 DIRTY
T2="$S2/worktrees/ask-aaa"
git -C "$R2/skel" worktree add -q -B sana/ask-aaa "$T2" origin/main 2>/dev/null
G -C "$T2" commit -q --allow-empty -m "local work that exists nowhere else"
: > "$BASE/worked.txt"; : > "$BASE/pages.txt"
run "$R2/skel" "$S2" "$BASE/r2a.out"
echo "--- episode 1 (tree unrepositionable):"
grep -i "skip ASK-AAA" "$BASE/r2a.out" | sed 's/^/    /'
echo "    pages=$(grep -c . "$BASE/pages.txt" 2>/dev/null)  ledger=$(ledger "$S2/linear-worker-attempts.json")"
# A human resolves it: put the tree back on the PR head.
git -C "$T2" checkout -q -B sana/ask-aaa origin/sana/ask-aaa
: > "$BASE/worked.txt"
run "$R2/skel" "$S2" "$BASE/r2b.out"
echo "--- after the human fixes the tree: dispatched=$([ -s "$BASE/worked.txt" ] && echo YES || echo NO)"
# It breaks again, exactly the same way.
G -C "$T2" commit -q --allow-empty -m "second episode of local work"
git -C "$T2" reset -q --hard HEAD~2 2>/dev/null
G -C "$T2" commit -q --allow-empty -m "second episode of local work"
: > "$BASE/worked.txt"; PAGES_BEFORE="$(grep -c . "$BASE/pages.txt" 2>/dev/null)"
run "$R2/skel" "$S2" "$BASE/r2c.out"
PAGES_AFTER="$(grep -c . "$BASE/pages.txt" 2>/dev/null)"
echo "--- episode 2 (tree unrepositionable again):"
grep -i "skip ASK-AAA" "$BASE/r2c.out" | sed 's/^/    /'
echo "    pages before=$PAGES_BEFORE  after=$PAGES_AFTER"
if grep -q "cannot be moved onto them" "$BASE/r2c.out" && [ "$PAGES_BEFORE" = "$PAGES_AFTER" ]; then
  echo "R2 REPRODUCED: 2nd stuck-tree episode refused the round and paged NOBODY"
else
  echo "R2 not reproduced"
fi

echo
echo "############ R3: BLOCKED (this repo's live state) never ends a conflict streak ############"
echo "--- live producer check, assafkip/kipi-system right now:"
gh pr list --state open --json number,mergeStateStatus,mergeable 2>/dev/null | sed 's/^/    /'
R3="$BASE/r3"; make_repo "$R3"
S3="$BASE/s3"; mkdir -p "$S3/pr-reviews"
printf '{"verdict":"APPROVE","pr":903}\n' > "$S3/pr-reviews/pr-903.verdict.json"
# Episode 1: one conflict round already ran and the rebase WORKED.
printf '{"ASK-AAA":{"conflict_rounds":1}}\n' > "$S3/linear-worker-attempts.json"
# The PR now merges (mergeable) but a required check is red -> GitHub says BLOCKED.
gh_says 903 BLOCKED
: > "$BASE/worked.txt"; : > "$BASE/pages.txt"
run "$R3/skel" "$S3" "$BASE/r3a.out"
echo "--- healthy-again run (mergeable, required check red => BLOCKED):"
grep -i "skip ASK-AAA" "$BASE/r3a.out" | sed 's/^/    /'
echo "    ledger=$(ledger "$S3/linear-worker-attempts.json")"
# A brand-new, unrelated conflict episode starts.
gh_says 903 DIRTY
: > "$BASE/worked.txt"
run "$R3/skel" "$S3" "$BASE/r3b.out"
grep -iE "dispatching rebase round|skip ASK-AAA" "$BASE/r3b.out" | sed 's/^/    /'
: > "$BASE/worked.txt"
run "$R3/skel" "$S3" "$BASE/r3c.out"
grep -iE "dispatching rebase round|skip ASK-AAA" "$BASE/r3c.out" | sed 's/^/    /'
if grep -q "conflict_rounds\": 1" <(ledger "$S3/linear-worker-attempts.json" | tr ',' '\n') 2>/dev/null; then :; fi
if grep -q "a human resolves this one" "$BASE/r3c.out"; then
  echo "R3 REPRODUCED: the NEW conflict episode got 1 rebase round, not 2 -- the streak never reset"
else
  echo "R3 not reproduced"
fi
echo
echo "BASE=$BASE"
