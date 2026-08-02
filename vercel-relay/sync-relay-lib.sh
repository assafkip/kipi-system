#!/usr/bin/env bash
# Copy the tested modules into the Vercel bundle, and BLOCK on drift.
#
# WHY COPIES AND NOT AN IMPORT
# ----------------------------
# Vercel deploys a directory. It cannot reach back into q-system/.q-system/scripts/,
# so the bundle needs its own copy of the modules the functions call. A copy that
# nobody checks is a second implementation that silently diverges -- and the divergence
# would appear as "the Mac rejects every delegation", because the two ends would be
# verifying with different code. Same failure mode the fable mirror exists to prevent,
# so it gets the same treatment: one canonical source, a copy, and a --check that fails
# the build when they differ.
#
# Copies are VERBATIM, whole files. An extraction step (pull just verify_signature out
# of the receiver) was rejected: it would be a third representation of the code, and it
# would break the mutation harnesses that target exact line text in the originals.
#
# Usage:
#   sync-relay-lib.sh          copy canonical -> bundle
#   sync-relay-lib.sh --check  exit 1 if the bundle has drifted (CI / pre-deploy)
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$DIR/../q-system/.q-system/scripts"
LIB="$DIR/api/_lib"

# canonical filename -> bundle module name (hyphens are not importable)
MAP=(
  "linear-relay-core.py:linear_relay_core.py"
  "linear-relay-store.py:linear_relay_store.py"
  "linear-agent-receiver.py:linear_agent_verify.py"
)

mode="${1:-sync}"
mkdir -p "$LIB"
drift=0

for pair in "${MAP[@]}"; do
  src_name="${pair%%:*}"
  dst_name="${pair##*:}"
  src="$SRC/$src_name"
  dst="$LIB/$dst_name"

  if [ ! -f "$src" ]; then
    echo "[MISSING] canonical source $src"
    drift=$((drift+1))
    continue
  fi

  if [ "$mode" = "--check" ]; then
    if [ ! -f "$dst" ]; then
      echo "[DRIFT] $dst_name is missing from the bundle"
      drift=$((drift+1))
    elif ! cmp -s "$src" "$dst"; then
      echo "[DRIFT] $dst_name differs from canonical $src_name"
      drift=$((drift+1))
    else
      echo "[ok] $dst_name matches canonical"
    fi
  else
    cp "$src" "$dst"
    echo "[synced] $src_name -> api/_lib/$dst_name"
  fi
done

if [ "$mode" = "--check" ]; then
  if [ $drift -eq 0 ]; then
    echo "bundle is in sync with canonical sources"
  else
    echo "$drift file(s) drifted -- run sync-relay-lib.sh before deploying"
  fi
  exit $drift
fi
exit 0
