#!/bin/bash
# The reviewer's engine runs in a scratch $TMPDIR this script owns and deletes,
# any worktree the engine cuts is removed with it, and the claude engine cannot
# `git clone`. Scar: 2026-10-01, the Opus fallback left a 1.4G worktree and a 1.8G
# full clone in /tmp across cole-gtm PR #16 rounds and filled the disk
# mid-review. Drives the REAL functions, sliced out of pr-review-agent.sh,
# against a stub claude on a sealed PATH.
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
git -C "$T/repo" -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m init
SHA="$(git -C "$T/repo" rev-parse HEAD)"
# A worktree that exists BEFORE the run (another reviewer's, attached): must survive.
git -C "$T/repo" worktree add -q -b other "$T/bystander" HEAD
# Scratch a SIGKILLed run left behind 13 hours ago: must be reaped.
BASE="$T/home/.config/kipi/review-scratch"
mkdir -p "$BASE/run.stale"
touch -t "$(date -v-13H +%Y%m%d%H%M)" "$BASE/run.stale"

cat > "$T/bin/claude" <<'EOF'
#!/bin/bash
printf '%s\n' "$@" > "$STUB_ARGV"
printf '%s\n' "$TMPDIR" > "$STUB_TMPDIR"
head -c 1024 /dev/zero > "$TMPDIR/repro-copy"
# The scar's shape: a mutable copy cut OUTSIDE $TMPDIR.
git -C "$STUB_REPO" worktree add -q --detach "$STUB_OUTSIDE" HEAD
# Round 2: a copy on a BRANCH (not detached at the head) is still the engine's.
git -C "$STUB_REPO" worktree add -q -b engine-branch "$STUB_OUTSIDE-branch" HEAD
# Round 3: a concurrent review's copy in ITS scratch dir, under the same base.
mkdir -p "$STUB_SCRATCH_BASE/run.concurrent"
git -C "$STUB_REPO" worktree add -q --detach "$STUB_SCRATCH_BASE/run.concurrent/copy" HEAD
# This run's own copy, the way the prompt says to cut it.
git -C "$STUB_REPO" worktree add -q --detach "$TMPDIR/copy" HEAD
# A concurrent reviewer's tree appearing mid-run: never the engine's to remove.
git -C "$STUB_REPO" worktree add -q --detach "$STUB_REVIEW_TREES/other__pr-9" HEAD
echo "FINDINGS:"; echo "END FINDINGS"
EOF
chmod +x "$T/bin/claude"
for tool in bash env git mkdir mktemp rm head printf cat awk cut grep find; do
  ln -s "$(command -v "$tool")" "$T/bin/$tool"
done

drive() {   # drive <slice-prelude>
  cat > "$T/drive.sh" <<EOF
release_wt_lock() { :; }
run_bounded() { shift; "\$@"; }
REVIEW_REPO="$T/repo"; REVIEW_ROOT="$T/repo"; HEAD_SHA="$SHA"
CLAUDE_MODEL=m; CODEX_MODEL=m; TIMEOUT_SECONDS=5; PROMPT="the-prompt"
$1
source "$T/slice.sh"
run_engine claude "$T/out.txt"
EOF
  HOME="$T/home" PATH="$T/bin" STUB_ARGV="$T/argv" STUB_TMPDIR="$T/tmpdir" \
    STUB_REPO="$T/repo" STUB_OUTSIDE="$T/outside-copy" \
    STUB_REVIEW_TREES="$T/home/.config/kipi/review-trees" STUB_SCRATCH_BASE="$BASE" "$T/bin/bash" "$T/drive.sh"
}
drive ""
echo "drive rc=$?"

scratch="$(cat "$T/tmpdir" 2>/dev/null)"
check "engine ran with a scratch TMPDIR under the scratch base" \
  '[[ "$scratch" == "$BASE/run."* ]]'
check "scratch dir is gone after the run" '[ -n "$scratch" ] && [ ! -e "$scratch" ]'
check "a worktree the engine cut outside TMPDIR is removed" \
  '[ ! -e "$T/outside-copy" ] && ! git -C "$T/repo" worktree list | grep -q outside-copy'
check "a branch worktree the engine cut is removed" \
  '[ ! -e "$T/outside-copy-branch" ]'
check "a concurrent run's scratch copy survives" \
  '[ -d "$BASE/run.concurrent/copy" ] && git -C "$T/repo" worktree list | grep -q run.concurrent'
check "this run's own TMPDIR copy is unregistered" \
  '! git -C "$T/repo" worktree list | grep -qF "$scratch/copy"'
check "a review tree that appears mid-run survives" \
  '[ -d "$T/home/.config/kipi/review-trees/other__pr-9" ]'
check "a worktree that predates the run survives" \
  '[ -d "$T/bystander" ] && git -C "$T/repo" worktree list | grep -q bystander'
check "stale scratch from a killed run is reaped" '[ ! -e "$BASE/run.stale" ]'
check "claude cannot git clone" 'grep -qx "Bash(git clone:\*)" "$T/argv"'
check "the prompt precedes the variadic flag" \
  '[ "$(grep -n -x "the-prompt" "$T/argv" | cut -d: -f1)" -lt "$(grep -n -x -- "--disallowedTools" "$T/argv" | cut -d: -f1)" ]'

# A scratch dir that cannot be made refuses with exit 4, never "codex is down".
: > "$T/argv"
drive "KIPI_REVIEW_SCRATCH_BASE=/dev/null/no-such-dir"
rc=$?
check "an unmakeable scratch dir refuses with exit 4" '[ "$rc" = 4 ]'
check "and no engine ran" '[ ! -s "$T/argv" ]'

command rm -rf -- "$T"
exit "$fail"
