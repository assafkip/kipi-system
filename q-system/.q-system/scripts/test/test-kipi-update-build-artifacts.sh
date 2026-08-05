#!/usr/bin/env bash
# A build artifact must not ride the plugin sync into 23 instances.
#
# Measured 2026-07-25: plugins/kipi-core/kipi-mcp/.venv is 107MB of the
# skeleton's 112MB plugin tree. It is a uv-managed virtualenv -- uv itself
# writes a `.gitignore` containing `*` inside it -- pinned by pyvenv.cfg to one
# machine's Python (`/Users/<name>/.local/share/uv/python/cpython-3.12-macos-
# aarch64-none`), with 16 bin scripts hardcoding that home path and 9
# macOS-arm64 binaries. Nothing launches it: plugins/kipi-core/.mcp.json runs
# `uv --directory <plugin>/kipi-mcp run kipi-mcp`, and `uv run` builds the venv
# itself from the tracked uv.lock (verified: 52 packages in 37ms, from
# pyproject.toml + uv.lock + src alone, with no .venv present).
#
# So every update copied ~107MB x 23 instances of an artifact that cannot work
# anywhere but the skeleton's own machine. Spillover sp-d79a3d0b.
#
# The plugins rsync already carries --delete-excluded, so adding the exclude
# also REMOVES the stale copy already sitting in every instance.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SCRIPT="$ROOT/kipi-update.sh"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

WORK="$(mktemp -d)"; SK="$WORK/skel"; INST="$WORK/inst"

# skeleton: a plugin holding both real source and a uv-built virtualenv
mkdir -p "$SK/q-system" "$SK/plugins/demo/src" "$SK/plugins/demo/.venv/bin"
printf 'skeleton content\n' > "$SK/q-system/tracked.md"
printf 'real plugin source\n' > "$SK/plugins/demo/src/server.py"
printf 'home = /Users/someone-else/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin\n' \
  > "$SK/plugins/demo/.venv/pyvenv.cfg"
printf '*\n' > "$SK/plugins/demo/.venv/.gitignore"   # uv writes this itself
printf '#!/Users/someone-else/bin/python\n' > "$SK/plugins/demo/.venv/bin/activate"
cp "$SCRIPT" "$SK/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK/kipi-update-preserve-scan.py"
cp "$ROOT/kipi-update-deletion-guard.py" "$SK/kipi-update-deletion-guard.py"
# A valid skeleton ships the propagation leak gate: kipi-update.sh is
# fail-closed on it, so a fixture without it aborts before any sync.
mkdir -p "$SK/q-system/.q-system/scripts" "$SK/q-system/.q-system/state"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK/validate-separation.py"
# NOT the repo's committed baseline: that one is ARMED and its permits
# describe THIS repo's content, so loading it against a synthetic skeleton
# refuses ("a permit cannot exceed what was reviewed"). A fixture gets its
# own unarmed baseline.
cat > "$SK/q-system/.q-system/state/propagation-leak-baseline.json" <<'BASELINE_JSON'
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
( cd "$SK" && G init -q && G add -A -f && G commit -qm skel )
printf '{"instances":[{"name":"testinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$INST" > "$SK/instance-registry.json"

# instance: already carrying a stale virtualenv from a previous update
mkdir -p "$INST/q-system" "$INST/.claude" "$INST/plugins/demo/.venv/bin"
printf 'old\n' > "$INST/q-system/tracked.md"
printf 'stale venv from a previous update\n' > "$INST/plugins/demo/.venv/pyvenv.cfg"
# ...and build artifacts, which must NOT be read as colliding work in progress.
# config_source_manages matched plugins/*/* whenever the plugin DIRECTORY
# existed in the skeleton, and the collision scan enumerated gitignored files
# too, so one __pycache__ entry aborted the entire config block. Measured
# 2026-07-25 against the real registry: that failed on 23 of 23 instances,
# which meant .claude/, plugins/ and this very .venv deletion never ran.
mkdir -p "$INST/plugins/demo/src/__pycache__" "$INST/plugins/demo/.pytest_cache"
printf 'cached\n' > "$INST/plugins/demo/src/__pycache__/x.cpython-314.pyc"
printf 'cached\n' > "$INST/plugins/demo/.pytest_cache/CACHEDIR.TAG"
( cd "$INST" && G init -q && G add -A -f && G commit -qm inst )

bash "$SK/kipi-update.sh" >/dev/null 2>&1 || true

# 1. the artifact must not be copied in
[ ! -e "$INST/plugins/demo/.venv/bin/activate" ] || \
  fail "the skeleton's .venv was copied into the instance"

# 2. and the stale one already there must be removed (--delete-excluded)
[ ! -e "$INST/plugins/demo/.venv" ] || \
  fail "a stale .venv survived in the instance; --delete-excluded did not reach it"

# 3. the plugin itself must still sync, or the exclude is too wide
[ -f "$INST/plugins/demo/src/server.py" ] || \
  fail "real plugin source stopped syncing"
grep -q "real plugin source" "$INST/plugins/demo/src/server.py" || \
  fail "plugin source synced but with wrong content"

if bash "$SK/kipi-update.sh" 2>&1 | grep -q "untracked WIP collides with managed config"; then
  fail "a build artifact in the instance was treated as colliding WIP"
fi

echo "PASS: .venv is neither copied nor left behind; real plugin source still syncs"
echo "PASS: a build artifact in the instance does not abort the config sync"
echo "PASS: a gitignored build artifact in the instance does not abort the config sync"
