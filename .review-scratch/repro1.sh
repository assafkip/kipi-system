#!/usr/bin/env bash
# REPRO 1 (PR #14): a worktree whose skeleton was moved/re-cloned makes the NEW
# claim (taken from INSIDE $TREE) exit 3 == collision, so linear-worker.sh
# reports "claimed by another session" -- a false diagnosis -- on every run,
# forever, with NO attempt counted and NO Slack page.
# The pre-PR worker (claim at the skeleton) counted the failure and paged.
set -uo pipefail

SCRIPTS="/Users/assafkipnis/projects/kipi-system/.review-scratch/repo/q-system/.q-system/scripts"
REAL_PY="$(command -v python3)"
W="$(mktemp -d)"
echo "workdir: $W"

git init -q --bare "$W/origin"
git init -q "$W/skel"
git -C "$W/skel" -c user.email=t@t.t -c user.name=t commit -q --allow-empty -m init
git -C "$W/skel" branch -M main
git -C "$W/skel" remote add origin "$W/origin"
git -C "$W/skel" push -q -u origin main

unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID 2>/dev/null || true

STUB="$W/bin"; mkdir -p "$STUB"
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '{"ready":[{"id":"%s","title":"t","project":"p"}],"total_open":1}\n' "\${2:-ASK-AAA}"
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
# The agent FAILS when its worktree is broken. That is the realistic case.
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
echo "reached-work-phase \$(pwd)" >> "$W/worked.txt"
exit 0
EOF
chmod +x "$STUB/python3" "$STUB/gh" "$STUB/claude"
export PATH="$STUB:$PATH"

# Capture Slack pages instead of sending them.
cat > "$SCRIPTS/slack-notify.sh" <<EOF
#!/usr/bin/env bash
echo "PAGE: \$*" >> "$W/pages.txt"
EOF
chmod +x "$SCRIPTS/slack-notify.sh"

use_worker() { cp "/Users/assafkipnis/projects/kipi-system/.review-scratch/worker-$1.sh" "$SCRIPTS/linear-worker.sh"; }

run() { # run <skel> <statedir>
  ( cd "$1" && KIPI_SKEL="$1" KIPI_STATE_DIR="$2" \
      bash "$SCRIPTS/linear-worker.sh" --apply --issue ASK-AAA --limit 1 ) 2>&1
}

echo
echo "=== step 1: healthy run with the NEW worker (creates the worktree) ==="
use_worker new
run "$W/skel" "$W/state" | grep -E "start |skip |fail |INFRA" | sed 's/^/  /'

echo
echo "=== step 2: the skeleton is re-cloned / renamed (ordinary maintenance) ==="
echo "    Worktrees live OUTSIDE the repo (\$STATE_DIR/worktrees), so they survive it."
cp -R "$W/state" "$W/state-old"          # identical copy for the pre-PR comparison
mv "$W/skel" "$W/skel2"
echo "    worktree dir survives:  $([ -d "$W/state/worktrees/ask-aaa" ] && echo yes || echo no)"
echo "    rev-parse inside it:    $( ( cd "$W/state/worktrees/ask-aaa" && git rev-parse --show-toplevel ) 2>&1 )"

echo
echo "=== step 3: NEW worker (this PR), three consecutive runs on the broken tree ==="
use_worker new
for i in 1 2 3; do
  run "$W/skel2" "$W/state" | grep -E "start |skip |fail |INFRA|stuck" | sed "s/^/  run$i: /"
done
echo "  attempts ledger: $(cat "$W/state/linear-worker-attempts.json" 2>/dev/null || echo '(never written -- nothing was counted)')"
echo "  work phase hits: $(grep -c . "$W/worked.txt" 2>/dev/null || echo 0)"
echo "  pages sent:      $(cat "$W/pages.txt" 2>/dev/null || echo '(none)')"

echo
echo "=== step 4: PRE-PR worker, same broken tree, three runs ==="
use_worker old
for i in 1 2 3; do
  run "$W/skel2" "$W/state-old" | grep -E "start |skip |fail |INFRA|stuck" | sed "s/^/  run$i: /"
done
echo "  attempts ledger: $(cat "$W/state-old/linear-worker-attempts.json" 2>/dev/null || echo '(never written)')"
echo "  pages sent:      $(cat "$W/pages.txt" 2>/dev/null || echo '(none)')"
