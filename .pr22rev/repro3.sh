#!/usr/bin/env bash
set -uo pipefail
WT="/Users/assafkipnis/projects/kipi-system/.pr22rev/wt"
W="/Users/assafkipnis/projects/kipi-system/.pr22rev/work3"
REAL_PY="$(command -v python3)"; REAL_GIT="$(command -v git)"
rm -rf "$W" 2>/dev/null; mkdir -p "$W/state/pr-reviews" "$W/bin" "$W/home"
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

git init -q --bare "$W/origin"; git -C "$W/origin" symbolic-ref HEAD refs/heads/main
git init -q "$W/skel"; G -C "$W/skel" commit -q --allow-empty -m c1
git -C "$W/skel" branch -M main; git -C "$W/skel" remote add origin "$W/origin"
G -C "$W/skel" push -q -u origin main

cat > "$W/bin/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -) cat >/dev/null; printf '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"}],"total_open":1}\n'; exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
cat > "$W/bin/gh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "pr list"*) echo 888 ;;
  "pr view 888 --json mergeable"*) echo MERGEABLE ;;
esac
exit 0
EOF
printf '#!/usr/bin/env bash\nexit 0\n' > "$W/bin/claude"
chmod +x "$W/bin/python3" "$W/bin/gh" "$W/bin/claude"
printf '{"verdict":"REQUEST CHANGES","pr":888}\n' > "$W/state/pr-reviews/pr-888.verdict.json"

echo "=== founder checkout .git/config BEFORE the worker runs:"
git -C "$W/skel" config --local --list | grep -E 'extensions|hooksPath' || echo "  (no extensions.*, no core.hooksPath)"

( cd "$W/skel" && PATH="$W/bin:$PATH" HOME="$W/home" KIPI_SKEL="$W/skel" KIPI_STATE_DIR="$W/state" \
    bash "$WT/q-system/.q-system/scripts/linear-worker.sh" --apply --issue ASK-AAA --limit 1 ) >"$W/run.out" 2>&1
TREE="$W/state/worktrees/ask-aaa"
[ -d "$TREE" ] || { echo "NO WORKTREE: $(tail -3 "$W/run.out")"; exit 1; }

echo
echo "=== founder checkout .git/config AFTER one worker run:"
git -C "$W/skel" config --local --list | grep -E 'extensions|hooksPath' || echo "  (clean)"
echo "=== which config file holds it:"
grep -n 'worktreeConfig' "$W/skel/.git/config" && echo "  ^ this is the SHARED config the founder's checkout reads"

echo
echo "############ non-ASCII scratch filename vs the guard"
HOOKS="$(git -C "$TREE" config core.hooksPath)"
mkdir -p "$TREE/q-system/output"
printf 'print("scratch")\n' > "$TREE/q-system/output/ask208-hélper.py"
printf 'print("scratch")\n' > "$TREE/q-system/output/ask208-plain.py"

echo "--- control: the plain ASCII name (what the guard was built for)"
G -C "$TREE" add -f q-system/output/ask208-plain.py
if G -C "$TREE" commit -q -m "wip plain (ASK-208)" >"$W/c1.out" 2>&1; then
  echo "   NOT REFUSED (unexpected)"
else
  echo "   refused: $(grep -m1 BLOCK "$W/c1.out")"
fi
G -C "$TREE" reset -q

echo "--- same file, one accented character in the name"
G -C "$TREE" add -f "q-system/output/ask208-hélper.py"
echo "   git stages it as: $(git -C "$TREE" diff --cached --name-only)"
if G -C "$TREE" commit -q -m "wip accented (ASK-208)" >"$W/c2.out" 2>&1; then
  echo "   COMMITTED. The guard did not refuse it."
  git -C "$TREE" show --stat --oneline HEAD | head -3
else
  echo "   refused: $(grep -m1 BLOCK "$W/c2.out")"
fi

echo
echo "--- and at push?"
BR="$(git -C "$TREE" rev-parse --abbrev-ref HEAD)"
if G -C "$TREE" push -q origin "$BR" >"$W/p2.out" 2>&1; then
  echo "   PUSHED. Neither gate saw it."
  echo "   on the remote: $(git -C "$W/origin" ls-tree -r --name-only "refs/heads/$BR" | tr '\n' ' ')"
else
  echo "   refused at push: $(grep -m1 BLOCK "$W/p2.out")"
fi
