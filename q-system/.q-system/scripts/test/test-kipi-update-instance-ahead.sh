#!/usr/bin/env bash
# The updater names every file it would overwrite whose instance copy the
# skeleton never shipped, before it writes anything, and refuses on demand.
#
# 2026-09-06, three times in one day: the fleet sync replaced consulting's
# voiceloop engine (extra modules), its voice-stop-gate.py (five extra defs) and
# its calibrated voice-lint BANNED_WORDS (two entries removed after measuring
# the founder's corpus), and each time the instance's own gate went red only
# after the rsync had landed. The dry run listed those files as ordinary
# changes. sp-1ad08728.
#
# "Ahead" is the shipped-blob question (fleet_authored_blob): bytes equal to
# ANY skeleton version of the path are never ahead. So a skeleton with history
# is part of the fixture: a file whose instance copy equals the skeleton's
# OLDER version must stay quiet, or the report is a diff wearing a better name.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

# ------------------------------------------------------------------ the fixture
# Skeleton with TWO commits, so "older shipped version" exists, and one clean
# instance carrying: an extra def in a synced .py (ahead), an edited list
# (ahead), a file at the skeleton's OLDER version (not ahead), an edited
# plugin file (ahead) and an edited rule (ahead).
build() {
  local work="$1" sk="$work/skel" inst="$work/inst"
  mkdir -p "$sk/q-system/.q-system/scripts" "$sk/q-system/.q-system/state" \
           "$sk/q-system/hooks" "$sk/plugins/demo" "$sk/.claude/rules"
  for f in kipi-update.sh kipi-update-preserve-scan.py kipi-update-deletion-guard.py \
           kipi-update-instance-ahead.py validate-separation.py; do
    cp "$ROOT/$f" "$sk/$f"
  done
  for f in propagation-leak-gate.py containment-targets.py fleet-replica-divergence.py; do
    if [ -f "$ROOT/q-system/.q-system/scripts/$f" ]; then
      cp "$ROOT/q-system/.q-system/scripts/$f" "$sk/q-system/.q-system/scripts/$f"
    fi
  done
  cp "$ROOT/q-system/hooks/auto-commit.py" "$sk/q-system/hooks/auto-commit.py"
  cat > "$sk/q-system/.q-system/state/propagation-leak-baseline.json" <<'JSON'
{
  "schema_version": 1,
  "blocking_classes": ["case_proof_gap", "client_identity", "dated_interaction",
                       "pricing", "relationship", "source_identity",
                       "sourced_interaction"],
  "classifier_sha256": null,
  "entries": []
}
JSON
  # v1 of everything the instance will diverge on.
  printf 'skeleton v1\n' > "$sk/q-system/tracked.md"
  printf 'def shipped():\n    return 1\n' > "$sk/q-system/.q-system/scripts/gate.py"
  printf 'alpha\nbeta\ngamma\n' > "$sk/q-system/.q-system/scripts/calibrated.txt"
  printf 'plugin v1\n' > "$sk/plugins/demo/content.txt"
  printf '# demo rule v1\n' > "$sk/.claude/rules/demo.md"
  ( cd "$sk" && G init -q -b main && G add -A -f && G commit -qm skel-v1 )
  # v2 = skeleton HEAD, the version the sync delivers.
  printf 'skeleton v2\n' > "$sk/q-system/tracked.md"
  printf 'def shipped():\n    return 2\n' > "$sk/q-system/.q-system/scripts/gate.py"
  printf 'alpha\nbeta\ngamma\ndelta\n' > "$sk/q-system/.q-system/scripts/calibrated.txt"
  printf 'plugin v2\n' > "$sk/plugins/demo/content.txt"
  printf '# demo rule v2\n' > "$sk/.claude/rules/demo.md"
  ( cd "$sk" && G add -A -f && G commit -qm skel-v2 )
  printf '{"instances":[{"name":"testinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$inst" > "$sk/instance-registry.json"

  mkdir -p "$inst/q-system/.q-system/scripts" "$inst/plugins/demo" "$inst/.claude/rules"
  # NOT ahead: the skeleton's older version, byte for byte.
  printf 'skeleton v1\n' > "$inst/q-system/tracked.md"
  # Ahead: skeleton v2 plus a def the skeleton never shipped.
  printf 'def shipped():\n    return 2\n\ndef founder_only():\n    return True\n' \
    > "$inst/q-system/.q-system/scripts/gate.py"
  # Ahead: the calibrated list, one entry removed.
  printf 'alpha\ngamma\ndelta\n' > "$inst/q-system/.q-system/scripts/calibrated.txt"
  # Ahead: a plugin file edited in the instance.
  printf 'plugin v2 with a local fix\n' > "$inst/plugins/demo/content.txt"
  # Ahead: a rule edited in the instance.
  printf '# demo rule v2, tuned here\n' > "$inst/.claude/rules/demo.md"
  ( cd "$inst" && G init -q -b main && G add -A -f && G commit -qm inst )
}

expect_report() {
  local out="$1"
  grep -q 'instance ahead: q-system/.q-system/scripts/gate.py (+defs: founder_only)' "$out" || \
    fail "the extra def is not named: $(grep 'instance ahead' "$out" || echo none)"
  grep -q 'instance ahead: q-system/.q-system/scripts/calibrated.txt (1 hunk)' "$out" || \
    fail "the edited list is not named with its hunk count: $(grep 'instance ahead' "$out" || echo none)"
  grep -q 'instance ahead: plugins/demo/content.txt (1 hunk)' "$out" || \
    fail "the edited plugin file is not named: $(grep 'instance ahead' "$out" || echo none)"
  grep -q 'instance ahead: .claude/rules/demo.md (1 hunk)' "$out" || \
    fail "the edited rule is not named: $(grep 'instance ahead' "$out" || echo none)"
  if grep -q 'instance ahead: q-system/tracked.md' "$out"; then
    fail "a file at the skeleton's OLDER version was reported ahead; the check is a diff, not the shipped-blob question"
  fi
  grep -q 'INSTANCE AHEAD OF SKELETON (4 file(s)' "$out" || \
    fail "the summary does not repeat the report with the right count: $(grep -A5 'Summary' "$out")"
  grep -q -- '- testinst: q-system/.q-system/scripts/gate.py (+defs: founder_only)' "$out" || \
    fail "the summary line does not name the instance and the file: $(grep -A8 'Summary' "$out")"
}

# ------------------------------------------------------------------ property 1
assert_the_dry_run_names_every_ahead_file_and_only_those() {
  local work sk; work="$(mktemp -d)"; sk="$work/skel"
  build "$work"
  bash "$sk/kipi-update.sh" --dry-run >"$work/out" 2>&1 || true
  expect_report "$work/out"
  echo "PASS: the dry run names the four ahead files with defs or hunks, stays quiet on the older shipped version, and repeats them in the summary"
}

# ------------------------------------------------------------------ property 2
assert_the_refuse_flag_abandons_before_any_commit_or_write() {
  local work sk inst; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  bash "$sk/kipi-update.sh" --refuse-instance-ahead >"$work/out" 2>&1 || true
  grep -q 'refusing (--refuse-instance-ahead)' "$work/out" || \
    fail "the flag did not refuse: $(tail -n 15 "$work/out")"
  grep -q 'Failed:  1' "$work/out" || fail "a refused instance was not counted as failed: $(tail -n 8 "$work/out")"
  [ "$(G -C "$inst" log -1 --format=%s)" = "inst" ] || fail "a refusal left a commit behind: $(G -C "$inst" log --format=%s)"
  G -C "$inst" diff --cached --quiet || fail "a refusal left something staged"
  G -C "$inst" diff --quiet || fail "a refusal left the working tree modified"
  grep -q 'founder_only' "$inst/q-system/.q-system/scripts/gate.py" || fail "a refusal overwrote the ahead file"
  expect_report "$work/out"
  echo "PASS: --refuse-instance-ahead abandons the instance before the pre-sync commit: nothing staged, nothing written, report still printed"
}

# ------------------------------------------------------------------ property 3
assert_without_the_flag_the_sync_lands_and_the_summary_still_says_so() {
  local work sk inst; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true
  grep -q 'Updated: 1' "$work/out" || fail "the default did not sync: $(tail -n 15 "$work/out")"
  expect_report "$work/out"
  # The documented effect of continuing: the skeleton's copy lands.
  if grep -q 'founder_only' "$inst/q-system/.q-system/scripts/gate.py"; then
    fail "the sync ran but the ahead file kept its instance content; the report described a run that did not happen"
  fi
  echo "PASS: without the flag the sync lands, the report still names every ahead file, and the summary repeats it"
}

# ------------------------------------------------------------------ property 4
# The mutant: make fleet_authored_blob answer "shipped" for everything. The
# report must go silent; if it does not, the scan is not asking the shipped-blob
# question and property 1 was passing for another reason.
assert_the_report_depends_on_the_shipped_blob_check() {
  local work sk; work="$(mktemp -d)"; sk="$work/skel"
  build "$work"
  python3 - "$sk/kipi-update.sh" <<'PY'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
needle = "while IFS='|' read -r name path prefix itype declared; do"
assert text.count(needle) == 1, "main loop header moved; update the mutant"
text = text.replace(needle, "fleet_authored_blob() { return 0; }\n" + needle)
open(path, "w", encoding="utf-8").write(text)
PY
  bash "$sk/kipi-update.sh" --dry-run >"$work/out" 2>&1 || true
  if grep -q 'instance ahead:' "$work/out"; then
    fail "with fleet_authored_blob forced to 'shipped', the report still named files; the scan is not using the shipped-blob check"
  fi
  echo "PASS: forcing every blob to read as shipped silences the report (the shipped-blob check is load-bearing)"
}

assert_the_dry_run_names_every_ahead_file_and_only_those
assert_the_refuse_flag_abandons_before_any_commit_or_write
assert_without_the_flag_the_sync_lands_and_the_summary_still_says_so
assert_the_report_depends_on_the_shipped_blob_check
