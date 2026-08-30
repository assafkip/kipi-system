#!/usr/bin/env bash
# Pairs with the review-root guard in q-system/.q-system/scripts/pr-review-agent.sh.
#
# Scar (2026-08-04): a copy of the review agent at .pr28rev/scripts/ resolved its
# review root to the checkout's PARENT directory -- not a git repo -- so there was no
# diff, the model formed a verdict from the prompt alone, and that empty review
# was posted as a passing status. `../../..` assumed a depth nothing asserted.
#
# Hermetic: every case builds its own repo under mktemp and copies the real
# script to a chosen depth. Nothing here touches a live repo or the network; the
# guard sits above argument parsing, so the script is invoked with no args and
# refuses before it can reach `gh`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
AGENT="$ROOT/q-system/.q-system/scripts/pr-review-agent.sh"
fail() { echo "FAIL: $1" >&2; exit 1; }

[ -f "$AGENT" ] || fail "review agent missing at $AGENT"

G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }
OUTFILE="$(mktemp)"

# Places the real script at $2 (relative to repo $1), runs it, sets RC/OUT.
# Not `OUT=$(run_at ...)`: command substitution is a subshell and RC would be
# discarded, which silently turned an earlier suite green.
run_at() {
  local repo="$1" rel="$2" dir
  dir="$repo/$rel"
  mkdir -p "$dir"
  cp "$AGENT" "$dir/pr-review-agent.sh"
  chmod +x "$dir/pr-review-agent.sh"
  set +e
  bash "$dir/pr-review-agent.sh" > "$OUTFILE" 2>&1
  RC=$?
  set -e
  OUT="$(cat "$OUTFILE")"
}

mkrepo() { local d; d="$(mktemp -d)"; ( cd "$d" && G init -q && printf 'x\n' > f.md && G add -A && G commit -qm base ); echo "$d"; }

# --- POSITIVE: canonical depth inside a real repo -> guard must NOT fire ------
REPO="$(mkrepo)"
run_at "$REPO" "q-system/.q-system/scripts"
case "$OUT" in
  *REFUSING*) fail "guard fired on the CANONICAL depth-3 layout: $OUT";;
esac

# --- NEGATIVE-1: the literal 2026-08-04 shape --------------------------------
# .pr28rev/scripts/ is 2 levels deep, so ../../.. overshoots one level and lands
# on the PARENT of the repo. This is the case that reviewed a non-repo.
REPO="$(mkrepo)"
run_at "$REPO" ".pr28rev/scripts"
[ "$RC" -eq 2 ] || fail "depth-2 scratch copy must exit 2, got $RC: $OUT"
case "$OUT" in *REFUSING*) :;; *) fail "depth-2 copy did not refuse: $OUT";; esac
PARENT="$(cd "$REPO/.." && pwd)"
case "$OUT" in *"$PARENT"*) :;; *) fail "refusal did not report the overshot root $PARENT: $OUT";; esac

# --- NEGATIVE-2: correct depth, but nothing above it is a repo ---------------
BARE="$(mktemp -d)"
run_at "$BARE" "q-system/.q-system/scripts"
[ "$RC" -eq 2 ] || fail "non-repo root must exit 2, got $RC: $OUT"
case "$OUT" in *"not a git repository"*) :;; *) fail "non-repo refusal lacks the reason: $OUT";; esac

# --- NEGATIVE-3: inside a repo, but NOT at its root --------------------------
# Mutation guard for the toplevel comparison specifically. A weaker guard that
# only asks whether `git rev-parse` SUCCEEDS passes this case, because a
# subdirectory of a repo is still "in a repo" -- and the agent would then review
# a subtree while believing it held the whole repo. Only the ==-toplevel form
# catches it, so this case is what keeps that comparison honest.
REPO="$(mkrepo)"
run_at "$REPO" "sub/dir/q-system/.q-system/scripts"
[ "$RC" -eq 2 ] || fail "root inside-but-not-top of a repo must exit 2, got $RC: $OUT"
case "$OUT" in *REFUSING*) :;; *) fail "subtree root did not refuse: $OUT";; esac

# --- the guard runs BEFORE argument parsing / any network --------------------
# If it drifted below arg parsing, a no-arg invocation would die on usage first
# and the refusal text would never appear -- which is exactly how a guard stops
# protecting anything without anyone noticing.
REPO="$(mkrepo)"
run_at "$REPO" ".pr28rev/scripts"
case "$OUT" in
  *REFUSING*) :;;
  *) fail "guard no longer precedes arg parsing (no refusal on a no-arg run): $OUT";;
esac

echo "PASS: refuses a depth-2 scratch copy (the 2026-08-04 shape), a non-repo root, and a non-toplevel root; stays silent on the canonical layout; fires before arg parsing"
