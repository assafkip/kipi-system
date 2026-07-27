#!/usr/bin/env bash
# REPRO: a conflict round is BURNED before the claim is taken.
#
# linear-worker.sh calls bump_conflict_round (line 325) BEFORE the worktree
# (line 340) and BEFORE the claim (line 372). Any skip after that point still
# spends the round. Two scheduled runs against a stale claim -- the exact scar
# converge.sh's own header documents ("a SIGKILL / laptop sleeping leaves the
# lock held with nothing to reclaim it") -- reach MAX_CONFLICT_ROUNDS=2 having
# dispatched ZERO rebase rounds, then page the founder saying two rounds ran.
#
# Same fixtures + stubs as the PR's own section E, plus one stale claim.
set -uo pipefail
REPO="/Users/assafkipnis/projects/kipi-system/.pr25rev/repo"
WORKER="$REPO/q-system/.q-system/scripts/linear-worker.sh"
CLAIMPY="$REPO/q-system/.q-system/scripts/linear-claim.py"
REAL_PY="$(command -v python3)"
REAL_GIT="$(command -v git)"

W2="$REPO/../burn-$$"; mkdir -p "$W2/home"
G() { git -c user.email=t@t.t -c user.name=t "$@"; }
git init -q --bare "$W2/origin"
git init -q "$W2/skel"
G -C "$W2/skel" commit -q --allow-empty -m c1
git -C "$W2/skel" branch -M main
git -C "$W2/skel" remote add origin "$W2/origin"
git -C "$W2/skel" push -q -u origin main

STUB="$W2/bin"; mkdir -p "$STUB"
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
echo "worked" >> "$W2/worked.txt"
exit 0
EOF
cat > "$W2/notify.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$W2/pages.txt"
EOF
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "pr list"*)                             echo 777 ;;
  "pr view 777 --json mergeStateStatus"*) echo DIRTY ;;
esac
exit 0
EOF
chmod +x "$STUB/python3" "$STUB/claude" "$STUB/gh" "$W2/notify.sh"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || { echo "git shadowed"; exit 1; }

S="$W2/state"; mkdir -p "$S/pr-reviews"
printf '{"verdict":"APPROVE WITH NITS","pr":777}\n' > "$S/pr-reviews/pr-777.verdict.json"

# THE STALE CLAIM. A prior run was killed and never released it (converge.sh's
# documented 2026-07-27 scar). Taken by a DIFFERENT session, so every later run
# gets exit 3 = collision.
export KIPI_LINEAR_CLAIMS="$W2/stale-claims.json"
"$REAL_PY" "$CLAIMPY" claim ASK-AAA --agent sana --session ghost-dead-session
echo "--- stale claim seeded: $(cat "$KIPI_LINEAR_CLAIMS")"

: > "$W2/worked.txt"; : > "$W2/pages.txt"
for run in 1 2 3; do
  ( cd "$W2/skel" && HOME="$W2/home" KIPI_SKEL="$W2/skel" KIPI_STATE_DIR="$S" \
      KIPI_NOTIFY="$W2/notify.sh" bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) \
    > "$W2/run$run.out" 2>&1
  echo "--- run $run:"; grep -iE "skip|dispatching|conflict" "$W2/run$run.out" | sed 's/^/    /'
done

echo "--- rebase rounds actually DISPATCHED to claude: $(grep -c worked "$W2/worked.txt" 2>/dev/null || echo 0)"
echo "--- conflict_rounds recorded in the ledger:"
"$REAL_PY" -c "import json;print('   ',json.load(open('$S/linear-worker-attempts.json')))"
echo "--- pages sent to the founder:"
sed 's/^/    /' "$W2/pages.txt"
echo "--- W2=$W2"
