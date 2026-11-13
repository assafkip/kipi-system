#!/usr/bin/env bash
# Pre-push: the capability gate's structure checks on each PUSHED commit.
# Called from lefthook.yml `pre-push` (use_stdin: true, so git's ref lines reach
# this script). Test: q-system/.q-system/tests/test_prepush_capability_gate.py
#
# Why (ASK-4814, rca-pr794-round-cap-2026-11-12.md root cause #1): PR #794
# shipped startup_census.py with no caller and no declared_inert entry. CI said
# `inert-engine` 21 to 23 minutes after each of three pushes; the same finding
# takes about 17 seconds here. Pre-commit runs verify.sh, which has no gate call,
# and lefthook had no pre-push section, so nothing local ran it. The 2026-08-22
# RCA had named the same fix as a habit ("run the gate before every push"); a
# habit with no hook did not hold.
#
# --check-only: structure, wiring and data checks, no test run (CI runs those).
# --diff-base <merge-base>: a finding main already has is printed as a note and
# never blocks, so this refuses only what the branch itself adds.
#
# Each pushed commit is judged in a detached temp worktree at that sha, never in
# the working tree. The gate walks the files on disk, so judging the working
# tree let an untracked stray script in the main checkout refuse every push, and
# `git push origin <other-branch>` judged HEAD instead of the commit being sent.
#
# stdin is git's pre-push protocol: "<local ref> <local sha> <remote ref> <remote sha>".
# Exit 0 lets the push through, exit 1 refuses it.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"

# Skeleton only. kipi update ships this script to every instance; an instance
# has no instance-registry.json and its own capability posture.
[ -f "$root/instance-registry.json" ] || exit 0

zero="0000000000000000000000000000000000000000"
shas=()
if [ ! -t 0 ]; then
  while read -r _lref lsha rref _rsha; do
    # A delete pushes nothing to judge: its local sha is all zeros.
    [ -n "${lsha:-}" ] && [ "$lsha" != "$zero" ] || continue
    # Branches only. validate.yml runs on branch pushes and PRs, never on a
    # tag, and `git push --tags` would otherwise cost one 17 s gate run per tag.
    case "${rref:-}" in refs/heads/*) shas+=("$lsha") ;; esac
  done
fi
if [ "${#shas[@]}" -eq 0 ]; then
  echo "capability pre-push: no pushed commits on stdin, nothing to judge." >&2
  exit 0
fi

tmp=""
cleanup() {
  if [ -n "$tmp" ]; then
    git -C "$root" worktree remove --force "$tmp/tree" >/dev/null 2>&1 || true
    rmdir "$tmp" 2>/dev/null || true
  fi
}
trap cleanup EXIT

refused=0
seen=" "
for sha in "${shas[@]}"; do
  case "$seen" in *" $sha "*) continue ;; esac
  seen="$seen$sha "
  # No origin/main or no shared history means no base to scope to. Refusing
  # such a push would get this step switched off; CI still runs the full gate.
  if ! base="$(git -C "$root" merge-base "$sha" origin/main 2>/dev/null)"; then
    echo "capability pre-push: SKIPPED ${sha:0:12}, no merge-base with origin/main. CI still runs the gate." >&2
    continue
  fi
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/prepush-capability.XXXXXX")"
  git -C "$root" worktree add -q --detach "$tmp/tree" "$sha"
  echo "capability pre-push: ${sha:0:12} capability-gate.py --check-only --diff-base ${base:0:12}" >&2
  set +e
  out="$(python3 "$tmp/tree/q-system/.q-system/scripts/capability-gate.py" \
    --repo-root "$tmp/tree" --check-only --diff-base "$base" 2>&1)"
  rc=$?
  set -e
  cleanup
  tmp=""
  if [ "$rc" -eq 0 ]; then
    # A green run prints about 12 KB of notes (every declared_inert entry, every
    # base finding). Every agent push would carry that into its context, so a
    # pass shows the verdict line only; a refusal shows everything.
    printf '%s\n' "$out" | grep -E '^capability-gate: ' >&2 || true
  else
    printf '%s\n' "$out" >&2
    echo "capability pre-push: REFUSED ${sha:0:12} (gate exit $rc). Fix the RED lines above: wire the script, or add a declared_inert entry under q-system/.q-system/capability/declared_inert/." >&2
    refused=1
  fi
done
exit "$refused"
