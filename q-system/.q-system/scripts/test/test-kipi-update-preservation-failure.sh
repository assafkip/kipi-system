#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
UPDATER="$ROOT/kipi-update.sh"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

git_test() {
  git -c user.email=test@example.com -c user.name=test \
    -c commit.gpgsign=false "$@"
}

run_failure_case() {
  local helper_mode="$1"
  local work skeleton instance fake_bin rsync_log output rc
  work="$(mktemp -d)"
  skeleton="$work/skeleton"
  instance="$work/instance"
  fake_bin="$work/bin"
  rsync_log="$work/rsync.log"

  mkdir -p "$skeleton/q-system" "$instance/q-system" "$fake_bin"
  cp "$UPDATER" "$skeleton/kipi-update.sh"
  # A valid skeleton ships the propagation leak gate: kipi-update.sh is
  # fail-closed on it, so a fixture without it aborts before any sync.
  mkdir -p "$skeleton/q-system/.q-system/scripts" \
    "$skeleton/q-system/.q-system/state"
  cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
    "$skeleton/q-system/.q-system/scripts/propagation-leak-gate.py"
  cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
    "$skeleton/q-system/.q-system/scripts/containment-targets.py"
  cp "$ROOT/validate-separation.py" "$skeleton/validate-separation.py"
  # NOT the repo's committed baseline: that one is ARMED and its permits
  # describe THIS repo's content, so loading it against a synthetic skeleton
  # refuses ("a permit cannot exceed what was reviewed"). A fixture gets its
  # own unarmed baseline.
  cat > "$skeleton/q-system/.q-system/state/propagation-leak-baseline.json" <<'BASELINE_JSON'
{
  "schema_version": 1,
  "blocking_classes": [
    "case_proof_gap",
    "client_identity",
    "dated_interaction",
    "pricing",
    "relationship",
    "source_identity",
    "sourced_interaction"
  ],
  "classifier_sha256": null,
  "entries": []
}
BASELINE_JSON
  printf 'new skeleton content\n' > "$skeleton/q-system/tracked.md"

  if [ "$helper_mode" = "fails" ]; then
    cat > "$skeleton/kipi-update-preserve-scan.py" <<'PY'
#!/usr/bin/env python3
raise SystemExit(23)
PY
  elif [ "$helper_mode" = "incomplete" ]; then
    cat > "$skeleton/kipi-update-preserve-scan.py" <<'PY'
#!/usr/bin/env python3
import json
import sys

receipt_path = sys.argv[sys.argv.index("--receipt") + 1]
with open(receipt_path, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "candidate_count": 0,
            "complete": False,
            "schema_version": 1,
            "stdout_sha256": "0" * 64,
        },
        handle,
    )
raise SystemExit(0)
PY
  elif [ "$helper_mode" = "unterminated" ]; then
    cat > "$skeleton/kipi-update-preserve-scan.py" <<'PY'
#!/usr/bin/env python3
import hashlib
import json
import sys

output = b"q-system/instance-only.py"
receipt_path = sys.argv[sys.argv.index("--receipt") + 1]
sys.stdout.buffer.write(output)
with open(receipt_path, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "candidate_count": 1,
            "complete": True,
            "schema_version": 1,
            "stdout_sha256": hashlib.sha256(output).hexdigest(),
        },
        handle,
    )
raise SystemExit(0)
PY
  fi

  (
    cd "$skeleton"
    git_test init -q
    git_test add q-system
    git_test commit -qm skeleton
  )
  printf \
    '{"instances":[{"name":"fixture","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$instance" > "$skeleton/instance-registry.json"

  printf 'old instance content\n' > "$instance/q-system/tracked.md"
  (
    cd "$instance"
    git_test init -q
    git_test add q-system
    git_test commit -qm instance
  )

  # A dry itemized rsync (-n / -ain) reads and writes nothing; the updater's
  # instance-ahead preflight runs one before the preservation helper on
  # purpose, so only a WRITING invocation counts as "rsync invoked".
  cat > "$fake_bin/rsync" <<'SH'
#!/usr/bin/env bash
for arg in "$@"; do
  case "$arg" in
    -n|--dry-run|-*n*) [ "${arg#--}" = "$arg" ] && exit 0 ;;
  esac
done
printf 'rsync invoked\n' >> "$RSYNC_LOG"
exit 0
SH
  chmod +x "$fake_bin/rsync"

  set +e
  output="$(
    PATH="$fake_bin:$PATH" RSYNC_LOG="$rsync_log" \
      bash "$skeleton/kipi-update.sh" 2>&1
  )"
  rc=$?
  set -e

  [ "$rc" -ne 0 ] || fail "$helper_mode helper failure returned success"
  [ ! -e "$rsync_log" ] || fail "$helper_mode helper failure invoked rsync"
  grep -q "old instance content" "$instance/q-system/tracked.md" ||
    fail "$helper_mode helper failure changed the instance"
  echo "$output" | grep -q "preservation" ||
    fail "$helper_mode helper failure emitted no preservation error"
}

run_failure_case fails
run_failure_case missing
run_failure_case incomplete
run_failure_case unterminated

echo "PASS: invalid or incomplete preservation proof stops before rsync"
