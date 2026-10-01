#!/bin/bash
# The reviewer's engine runs in a scratch $TMPDIR this script owns and deletes,
# and the claude engine cannot `git clone`. Scar: 2026-10-01, the Opus fallback
# left a 1.4G worktree and a 1.8G full clone in /tmp across cole-gtm PR #16
# rounds and filled the disk mid-review. Drives the REAL functions, sliced out of
# pr-review-agent.sh, against a stub claude on a sealed PATH.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT="$HERE/../pr-review-agent.sh"
T="$(mktemp -d)"
fail=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; fail=1; fi; }

# The scratch block through the end of run_engine.
awk '/^REVIEW_SCRATCH=""$/{on=1} on{print} on && /^}$/ && seen_engine{exit} /^run_engine\(\)/{seen_engine=1}' \
  "$AGENT" > "$T/slice.sh"
check "slice holds the scratch block and run_engine" \
  'grep -q "^run_engine()" "$T/slice.sh" && grep -q "review_scratch_cleanup" "$T/slice.sh"'

mkdir -p "$T/bin" "$T/home" "$T/repo"
git -C "$T/repo" init -q
cat > "$T/bin/claude" <<'EOF'
#!/bin/bash
printf '%s\n' "$@" > "$STUB_ARGV"
printf '%s\n' "$TMPDIR" > "$STUB_TMPDIR"
head -c 1024 /dev/zero > "$TMPDIR/repro-copy"
echo "FINDINGS:"; echo "END FINDINGS"
EOF
chmod +x "$T/bin/claude"
for tool in bash env git mkdir mktemp rm head printf cat; do
  ln -s "$(command -v "$tool")" "$T/bin/$tool"
done

cat > "$T/drive.sh" <<EOF
release_wt_lock() { :; }
run_bounded() { shift; "\$@"; }
REVIEW_REPO="$T/repo"; REVIEW_ROOT="$T/repo"
CLAUDE_MODEL=m; CODEX_MODEL=m; TIMEOUT_SECONDS=5; PROMPT="the-prompt"
source "$T/slice.sh"
run_engine claude "$T/out.txt"
EOF
HOME="$T/home" PATH="$T/bin" STUB_ARGV="$T/argv" STUB_TMPDIR="$T/tmpdir" \
  "$T/bin/bash" "$T/drive.sh"
echo "drive rc=$?"

scratch="$(cat "$T/tmpdir" 2>/dev/null)"
check "engine ran with a scratch TMPDIR under the scratch base" \
  '[[ "$scratch" == "$T/home/.config/kipi/review-scratch/run."* ]]'
check "scratch dir is gone after the run" '[ -n "$scratch" ] && [ ! -e "$scratch" ]'
check "claude cannot git clone" 'grep -qx "Bash(git clone:\*)" "$T/argv"'
check "the prompt precedes the variadic flag" \
  '[ "$(grep -n -x "the-prompt" "$T/argv" | cut -d: -f1)" -lt "$(grep -n -x -- "--disallowedTools" "$T/argv" | cut -d: -f1)" ]'

command rm -rf -- "$T"
exit "$fail"
