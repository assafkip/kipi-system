#!/usr/bin/env bash
# Pairs with q-system/.q-system/scripts/runtime-plugin-freshness.py.
#
# Hermetic: every case runs against a synthetic plugin root under mktemp, never
# against ~/.claude/plugins. The checker's whole job is to read machine state, so
# a test that read the real machine would pass or fail for reasons that have
# nothing to do with the code under test.
#
# The load-bearing case is NEGATIVE-1: it reproduces the 2026-08-05 defect shape
# exactly (marketplace refreshed to 0.16.5, registry still pinning 0.1.0) and
# asserts the checker goes RED. A version-parity check that cannot fail on that
# input is decoration.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
CHECK="$ROOT/q-system/.q-system/scripts/runtime-plugin-freshness.py"
fail() { echo "FAIL: $1" >&2; exit 1; }

[ -f "$CHECK" ] || fail "checker missing at $CHECK"

# Build a plugin root: marketplace ships $2 for plugin $1, registry pins $3.
mkroot() {
  local name="$1" mp_ver="$2" inst_ver="$3" d
  d="$(mktemp -d)"
  mkdir -p "$d/marketplaces/kipi/plugins/$name/.claude-plugin"
  printf '{"name":"%s","version":"%s"}\n' "$name" "$mp_ver" \
    > "$d/marketplaces/kipi/plugins/$name/.claude-plugin/plugin.json"
  printf '{"version":2,"plugins":{"%s@kipi":[{"scope":"user","version":"%s"}]}}\n' \
    "$name" "$inst_ver" > "$d/installed_plugins.json"
  echo "$d"
}

# Sets RC and OUT in the CALLER's shell. Deliberately not `OUT=$(run_check ...)`:
# command substitution runs a subshell, so an RC assigned in there is discarded
# and the next `[ "$RC" -eq 1 ]` reads a stale or unset value. Caught by this
# test's own first run (2026-08-05).
OUTFILE="$(mktemp)"
run_check() {
  set +e
  python3 "$CHECK" --plugin-root "$1" > "$OUTFILE" 2>&1
  RC=$?
  set -e
  OUT="$(cat "$OUTFILE")"
}

# --- POSITIVE: versions agree -> green -------------------------------------
D="$(mkroot prd-os 0.16.5 0.16.5)"
run_check "$D"
[ "$RC" -eq 0 ] || fail "matching versions must exit 0, got $RC: $OUT"
case "$OUT" in *PASS*) :;; *) fail "matching versions did not report PASS: $OUT";; esac

# --- NEGATIVE-1: the real 2026-08-05 shape ---------------------------------
# Marketplace refreshed to 0.16.5, registry still pinned at the April 0.1.0.
# This is the case a clone-HEAD-only check reported green on.
D="$(mkroot prd-os 0.16.5 0.1.0)"
run_check "$D"
[ "$RC" -eq 1 ] || fail "stale pin (0.1.0 vs 0.16.5) must exit 1, got $RC: $OUT"
case "$OUT" in *STALE*) :;; *) fail "stale pin did not print STALE: $OUT";; esac
case "$OUT" in *prd-os*) :;; *) fail "stale report does not name the plugin: $OUT";; esac
case "$OUT" in *"claude plugin update"*) :;; *) fail "stale report omits the second-layer fix command: $OUT";; esac

# --- NEGATIVE-2: mutant guard on the comparison itself ----------------------
# A checker that compared nothing (always green) survives NEGATIVE-1 only if
# NEGATIVE-1 is the sole stale case. Vary the direction: installed AHEAD of the
# marketplace is also a mismatch and must be caught, so the assertion cannot be
# a one-sided ">=" that a downgrade slips through.
D="$(mkroot prd-os 0.5.0 0.16.5)"
run_check "$D"
[ "$RC" -eq 1 ] || fail "installed-ahead mismatch must exit 1, got $RC: $OUT"

# --- SKIP path is explicit, not silent -------------------------------------
D="$(mktemp -d)"   # no registry, no marketplace
run_check "$D"
[ "$RC" -eq 0 ] || fail "absent registry must exit 0, got $RC: $OUT"
case "$OUT" in *SKIP*) :;; *) fail "absent registry went quiet instead of printing SKIP: $OUT";; esac

# --- malformed registry is exit 2, never a silent pass ----------------------
D="$(mkroot prd-os 0.16.5 0.16.5)"
printf 'not json\n' > "$D/installed_plugins.json"
run_check "$D"
[ "$RC" -eq 2 ] || fail "malformed registry must exit 2, got $RC: $OUT"

# --- clone behind origin/main is RED even when versions agree ---------------
# Layer 1 regression guard: version parity can hold while the clone itself is
# behind (a plugin whose version was not bumped in the new commits).
D="$(mkroot prd-os 0.16.5 0.16.5)"
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }
BARE="$(mktemp -d)/r.git"; git init -q --bare "$BARE"; git -C "$BARE" symbolic-ref HEAD refs/heads/main
SEED="$(mktemp -d)"
( cd "$SEED" && G init -q && printf 'a\n' > a.md && G add -A && G commit -qm base && G push -q "$BARE" HEAD:main )
MP="$D/marketplaces/kipi"
( cd "$MP" && G init -q && G remote add origin "$BARE" && G fetch -q origin && G checkout -q -B main origin/main )
# reinstate the fixture manifest the checkout replaced, then advance the remote
mkdir -p "$MP/plugins/prd-os/.claude-plugin"
printf '{"name":"prd-os","version":"0.16.5"}\n' > "$MP/plugins/prd-os/.claude-plugin/plugin.json"
( cd "$SEED" && printf 'b\n' > b.md && G add -A && G commit -qm ahead && G push -q "$BARE" HEAD:main )
( cd "$MP" && G fetch -q origin )   # remote ref now ahead; clone HEAD is not
run_check "$D"
[ "$RC" -eq 1 ] || fail "clone behind origin/main must exit 1 even with version parity, got $RC: $OUT"
case "$OUT" in *BEHIND*) :;; *) fail "behind-clone case did not print BEHIND: $OUT";; esac

echo "PASS: version parity RED on a stale pin (the 2026-08-05 shape) and on drift either direction; clone-behind RED under parity; SKIP printed not silent; malformed registry exit 2"
