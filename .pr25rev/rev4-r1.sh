#!/usr/bin/env bash
# R1 (retry): capture the prompt the rebase agent is actually handed.
# linear-worker.sh invokes `claude -p "$PROMPT"` -- the prompt is ARGV, not stdin.
set -uo pipefail
TREEROOT="/Users/assafkipnis/.config/kipi/worktrees/ask-212"
WORKER="$TREEROOT/q-system/.q-system/scripts/linear-worker.sh"
REAL_PY="$(command -v python3)"
BASE="/Users/assafkipnis/projects/kipi-system/.pr25rev/r1-$$"
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
if [ ! -s "$BASE/prompt.txt" ]; then printf '%s\n' "\$@" > "$BASE/prompt.txt"; fi
exit 0
EOF
cat > "$BASE/notify.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "pr list"*)                            echo 901 ;;
  "pr view 901 --json mergeStateStatus"*) echo DIRTY ;;
esac
exit 0
EOF
chmod +x "$STUB/python3" "$STUB/claude" "$STUB/gh" "$BASE/notify.sh"
export PATH="$STUB:$PATH"

d="$BASE/r1"; mkdir -p "$d"
git init -q --bare "$d/origin"; git init -q "$d/skel"
G -C "$d/skel" commit -q --allow-empty -m "base commit"
git -C "$d/skel" branch -M main
git -C "$d/skel" remote add origin "$d/origin"; git -C "$d/skel" push -q -u origin main
G -C "$d/skel" checkout -q -b sana/ask-aaa
G -C "$d/skel" commit -q --allow-empty -m "the approved work (ASK-AAA)"
git -C "$d/skel" push -q -u origin sana/ask-aaa
G -C "$d/skel" checkout -q main
git -C "$d/skel" update-ref -d refs/heads/sana/ask-aaa
G -C "$d/skel" commit -q --allow-empty -m "main moved underneath the PR"
git -C "$d/skel" push -q origin main

S="$BASE/state"; mkdir -p "$S/pr-reviews"
printf '{"verdict":"APPROVE","pr":901}\n' > "$S/pr-reviews/pr-901.verdict.json"
: > "$BASE/prompt.txt"
( cd "$d/skel" && HOME="$BASE/home" KIPI_SKEL="$d/skel" KIPI_STATE_DIR="$S" \
    KIPI_NOTIFY="$BASE/notify.sh" bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >"$BASE/run.out" 2>&1
grep -i "dispatching rebase" "$BASE/run.out" | sed 's/^/    /'
echo "--- what the rebase agent was told, in prompt order:"
grep -nE "GitHub now reports its merge state|git rebase origin/main|already on branch" "$BASE/prompt.txt" | sed 's/^/    /'
echo "--- verdict:"
if grep -q "off origin/main" "$BASE/prompt.txt"; then
  echo "R1 REPRODUCED"
else
  echo "R1 NOT reproduced"
fi
echo "BASE=$BASE"
