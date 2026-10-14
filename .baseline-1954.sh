#!/usr/bin/env bash
# ASK-1954 negative control: are the two remaining failures PRE-EXISTING?
# Drives origin/main's copy of the hook, which carries none of this branch's
# edits. If they fail there too, they are not caused by this diff.
set -uo pipefail
cd "$(dirname "$0")"
OUT=/tmp/dod-main-1954.sh
git show origin/main:q-system/.q-system/hooks/destructive-op-deny.sh > "$OUT"
chmod 755 "$OUT"
export KIPI_DESTRUCTIVE_HOOK="$OUT"
python3 -m pytest test_destructive_op_deny_anchor.py -q \
  -k "vendored_copy or git_clean_dry_run"
