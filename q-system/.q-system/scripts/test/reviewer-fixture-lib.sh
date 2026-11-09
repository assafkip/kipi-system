#!/usr/bin/env bash
# ONE place that knows what pr-review-agent.sh needs beside it in a fixture tree.
#
# Not a test: the name deliberately does not match capability-gate.py's
# TEST_PATTERNS (`test-*.sh`), so it is a sourced helper rather than a discovered
# test that would have to be declared as one.
#
# SCAR (ASK-3831, PR #701 review round 6, found by CI and not by a reviewer).
# Eight harnesses each hand-maintained their own copy of the reviewer's
# dependency list. The agent gained ONE hard dependency (reviewer-resolve.sh,
# whose absence is a named refusal since round 4) and `validate` went red on
# eight of them at once, in three different shapes: a refusal on the positive
# case, "did not reach the stub (0 calls)", and a <<NORECORD>> record that reads
# as "the key is a constant" rather than "the harness is shaped wrong".
#
# It was the THIRD time the same list drifted, and each previous time was paid
# for in a scar comment instead of a fix: test-verdict-usability.sh carries one
# for repo-slug-lib.sh (ASK-738) and another for reviewer-token-lib.sh. This is
# the same four-implementations defect ASK-3831 exists to remove, one layer out
# in the test harnesses.
#
# THE LIST IS DERIVED FROM THE AGENT, NOT RESTATED HERE. A ninth copy of the
# names -- even a single central one -- drifts the next time a `.` line is added.
# The agent's own source lines are the declaration.

# Prints one lib basename per line that <file> sources from its own directory.
# Matches both forms the reviewer tree uses: `. "$SCRIPT_DIR/x.sh"` and
# `. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/x.sh"`.
_rfl_sourced_names() {
  local f="$1"
  [ -f "$f" ] || return 0
  grep -oE '^[[:space:]]*(\.|source)[[:space:]]+"[^"]*/[A-Za-z0-9._-]+\.sh"' "$f" 2>/dev/null \
    | grep -oE '[A-Za-z0-9._-]+\.sh' \
    | sort -u
}

# Prints every lib the agent at $1 needs, transitively, resolved against the
# scripts dir $2. Two passes, not a general walk: the reviewer tree is two deep
# (pr-verdict-lib.sh sources repo-slug-lib.sh) and a fixed-point loop here would
# be more machinery than the shape earns. A third level would be missed, so if
# one is ever added, this becomes a loop.
reviewer_fixture_libs() {
  local agent="$1" src="$2"
  local direct name all=""
  direct="$(_rfl_sourced_names "$agent")"
  all="$direct"
  for name in $direct; do
    all="$all
$(_rfl_sourced_names "$src/$name")"
  done
  printf '%s\n' "$all" | sed '/^[[:space:]]*$/d' | sort -u
}

# stage_reviewer_libs <agent-to-parse> <dest-scripts-dir> [src-scripts-dir]
#
# Copies every lib the agent sources into <dest-scripts-dir>. Does NOT copy the
# agent itself: call sites place that themselves, several of them from a
# REPRO_REF commit, and staging it here would overwrite the version under test.
#
# A lib the agent names but that is absent from the source dir is REPORTED, not
# silently skipped. An old REPRO_REF agent naming a since-deleted lib is the
# legitimate case; a typo in the scripts dir is the other one, and a fixture that
# refuses with "0 calls" is exactly how this class hides.
stage_reviewer_libs() {
  local agent="$1" dest="$2" src="${3:-}"
  if [ -z "$src" ]; then
    src="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi
  [ -f "$agent" ] || { echo "stage_reviewer_libs: no agent at $agent" >&2; return 1; }
  mkdir -p "$dest"
  local name staged=0
  for name in $(reviewer_fixture_libs "$agent" "$src"); do
    if [ -f "$src/$name" ]; then
      cp "$src/$name" "$dest/$name" || { echo "stage_reviewer_libs: cannot copy $name" >&2; return 1; }
      staged=$((staged+1))
    else
      echo "stage_reviewer_libs: $agent sources $name, which is not in $src -- not staged" >&2
    fi
  done
  [ "$staged" -gt 0 ] || { echo "stage_reviewer_libs: staged NOTHING from $agent; the source-line parse matched no library, which makes every fixture below vacuous" >&2; return 1; }
  return 0
}
