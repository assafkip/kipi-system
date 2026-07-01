#!/bin/bash
# Tests for instance-automation-guard.py (blocks scripts into an instance's q-system/ subtree).
# Run: bash q-system/.q-system/scripts/test/test-instance-automation-guard.sh
set -uo pipefail
GUARD="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/instance-automation-guard.py"
T="$(mktemp -d)"

# Fake INSTANCE (no instance-registry.json) and SKELETON (has one).
INST="$T/instance"; mkdir -p "$INST/q-system/.q-system/scripts"
SKEL="$T/skeleton"; mkdir -p "$SKEL/q-system/.q-system/scripts"; : > "$SKEL/instance-registry.json"

run() {  # $1=project_dir  $2=file_path  -> prints exit code
  echo "{\"tool_input\":{\"file_path\":\"$2\"}}" | CLAUDE_PROJECT_DIR="$1" python3 "$GUARD" >/dev/null 2>&1
  echo $?
}

fail=0
ck() { echo "  $([ "$2" = "$3" ] && echo PASS || { echo FAIL; fail=1; }) $1 (got $2 want $3)"; }

# instance: script in q-system/ -> BLOCK (2)
f="$INST/q-system/.q-system/scripts/run.sh"; echo '#!/bin/bash' > "$f"
ck "instance script in q-system blocked" "$(run "$INST" "$f")" 2

# instance: python in q-system/ -> BLOCK
f="$INST/q-system/.q-system/scripts/x.py"; echo 'print(1)' > "$f"
ck "instance .py in q-system blocked" "$(run "$INST" "$f")" 2

# skeleton: same path -> ALLOW (0), skeleton scripts belong there
f="$SKEL/q-system/.q-system/scripts/run.sh"; echo '#!/bin/bash' > "$f"
ck "skeleton script allowed" "$(run "$SKEL" "$f")" 0

# instance: non-script (.md) in q-system/ -> ALLOW
f="$INST/q-system/lessons/a.md"; mkdir -p "$(dirname "$f")"; echo '# note' > "$f"
ck "instance markdown allowed" "$(run "$INST" "$f")" 0

# instance: script OUTSIDE q-system/ (repo-root automation) -> ALLOW
f="$INST/automation/run.sh"; mkdir -p "$(dirname "$f")"; echo '#!/bin/bash' > "$f"
ck "instance repo-root automation allowed" "$(run "$INST" "$f")" 0

# instance: script in q-system/ WITH bypass marker -> ALLOW
f="$INST/q-system/.q-system/scripts/keep.sh"; printf '#!/bin/bash\n# automation-guard-skip\n' > "$f"
ck "bypass marker allowed" "$(run "$INST" "$f")" 0

[ "$fail" = 0 ] && echo "ALL PASS" || { echo "SOME FAILED"; exit 1; }
