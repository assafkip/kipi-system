#!/bin/bash
# ASK-839 review finding (PR #191, codex major): the alert writer's project
# resolution has a rung that no production caller ever reaches.
#
# THE DEFECT. alert-to-linear.py::project_candidates() rung 2 is the repo PATH
# through instance-registry.json, and its own docstring calls it "the only rung
# that survives a worktree or a renamed directory, which is why slack-notify.sh
# resolves the path rather than passing its own label". slack-notify.sh did not.
# It computed a LABEL (KIPI_INSTANCE_NAME, else the checkout basename) and
# exported nothing, so KIPI_ALERT_REPO_PATH was unset on every real alert and
# rung 2 was dead code in production.
#
# WHY THAT IS NOT COSMETIC. With rung 2 skipped, a checkout whose basename is
# not its board alias falls through rung 3 (basename vs registry `name`) and
# rung 4 (basename as a project) to rung 5 -- the checkout THIS SCRIPT lives in
# -- and the alert is filed against kipi-system's project instead of the repo
# that raised it. Measured against the live instance-registry.json 2026-08-15:
# 7 of 25 registered instances have basename != alias (`strategy`/
# `KTLYST_strategy`, `consulting`/`ASK Consulting`, `product`/`ktlyst`,
# `kipi-investigations`/`investigations`, ...). Every git worktree is the same
# shape, which is how the fleet's own agents run.
#
# WHY THE MAIN CHECKOUT AND NOT `--show-toplevel`. From a worktree,
# --show-toplevel returns the WORKTREE path, which equals no registry row, so
# rung 2 would match nothing and the misattribution would survive the fix while
# the test went green. --git-common-dir points at the main checkout's .git in
# both a worktree and an ordinary clone, which is the path the registry stores.
# Same rule linear-claim.py learned the hard way at ASK-188.
#
# NO REAL TICKET CAN BE FILED FROM HERE, two independent nets, because the scar
# in slack-notify.sh is a suite that paged the founder live:
#   1. a `python3` shim first on PATH records argv/env and never runs the writer
#   2. PYTEST_CURRENT_TEST is exported, which alert-to-linear.py refuses on
#      (exit 4) even if the shim were somehow bypassed
# The loopback guard is NOT usable here: it exits 4 before reaching the writer,
# which is the handoff this suite has to observe.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTIFY="$HERE/../slack-notify.sh"
WRITER="$HERE/../alert-to-linear.py"
[ -f "$NOTIFY" ] || { echo "FAIL: slack-notify.sh not found at $NOTIFY"; exit 1; }
[ -f "$WRITER" ] || { echo "FAIL: alert-to-linear.py not found at $WRITER"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP" 2>/dev/null' EXIT

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "FAIL: $1"; }
eq()  { # want, got, label
  if [ "$2" = "$1" ]; then ok "$3"; else bad "$3 -- wanted [$1], got [$2]"; fi
}

# --- the python3 shim: records the env the writer was handed, files nothing ---
mkdir -p "$TMP/bin"
cat > "$TMP/bin/python3" <<'SH'
#!/bin/bash
{
  printf 'REPO_PATH=%s\n' "${KIPI_ALERT_REPO_PATH-<UNSET>}"
  printf 'ARGV=%s\n' "$*"
} > "$KIPI_TEST_CAPTURE"
exit 0
SH
chmod +x "$TMP/bin/python3"

# --- a registry whose alias is deliberately NOT the directory basename --------
MAIN="$TMP/checkout-basename"
mkdir -p "$MAIN"
git -C "$MAIN" init -q 2>/dev/null
git -C "$MAIN" config user.email t@t.t
git -C "$MAIN" config user.name t
: > "$MAIN/f"
git -C "$MAIN" add f >/dev/null 2>&1
git -C "$MAIN" commit -qm init >/dev/null 2>&1

MAIN_REAL="$(cd "$MAIN" && pwd -P)"
cat > "$TMP/registry.json" <<JSON
{"instances": [
  {"name": "some-other-name", "path": "$MAIN_REAL", "linear_project": "Board Alias"}
]}
JSON

WT="$TMP/.wt-ask999"
git -C "$MAIN" worktree add -q -b probe "$WT" >/dev/null 2>&1
WT_REAL="$(cd "$WT" && pwd -P)"

run_notify() { # cwd -> writes capture file, echoes nothing
  local cwd="$1"
  : > "$TMP/capture"
  ( cd "$cwd" 2>/dev/null || exit 0
    PATH="$TMP/bin:$PATH" \
    KIPI_TEST_CAPTURE="$TMP/capture" \
    PYTEST_CURRENT_TEST="test-notify-supplies-repo-path" \
    KIPI_INSTANCE_REGISTRY="$TMP/registry.json" \
    bash "$NOTIFY" "a probe alert" ) >/dev/null 2>&1
}
captured() { sed -n 's/^REPO_PATH=//p' "$TMP/capture"; }

# 1. The plain checkout: the path reaches the writer at all.
run_notify "$MAIN"
eq "$MAIN_REAL" "$(captured)" "ordinary checkout: KIPI_ALERT_REPO_PATH is the checkout"

# 2. A WORKTREE resolves to the MAIN checkout, which is what the registry holds.
#    --show-toplevel would give $WT_REAL here and match no row.
run_notify "$WT"
eq "$MAIN_REAL" "$(captured)" "worktree: resolves to the main checkout, not the worktree"

# 3. A SUBDIRECTORY is still the repo root, not the cwd.
mkdir -p "$MAIN/deep/er"
run_notify "$MAIN/deep/er"
eq "$MAIN_REAL" "$(captured)" "subdirectory: resolves to the repo root"

# 4. NO REPO AT ALL invents nothing. 22 of the 81 unset alert tickets were
#    raised from a cwd of `/`; supplying that as a repo path would hand rung 2 a
#    guaranteed-miss and make the candidate list longer without making it truer.
NOREPO="$TMP/norepo"; mkdir -p "$NOREPO"
run_notify "$NOREPO"
got4="$(captured)"
if [ "$got4" = "<UNSET>" ] || [ -z "$got4" ]; then
  ok "outside a repo: no path invented"
else
  bad "outside a repo: no path invented -- got [$got4]"
fi

# 5. An EXPLICIT caller value is not overwritten. Rung 1 of the candidate list
#    is "an explicit statement by the caller"; a derived value that clobbers it
#    would silently outrank it.
: > "$TMP/capture"
( cd "$MAIN" && PATH="$TMP/bin:$PATH" KIPI_TEST_CAPTURE="$TMP/capture" \
  PYTEST_CURRENT_TEST="t" KIPI_INSTANCE_REGISTRY="$TMP/registry.json" \
  KIPI_ALERT_REPO_PATH="/explicitly/set/by/caller" \
  bash "$NOTIFY" "a probe alert" ) >/dev/null 2>&1
eq "/explicitly/set/by/caller" "$(captured)" "explicit KIPI_ALERT_REPO_PATH survives"

# 6. THE OUTCOME THE FINDING IS ABOUT. Hand project_candidates() exactly what
#    slack-notify.sh now hands the writer -- the path AND the "[basename] "
#    prefix it puts on the message -- and the board alias must come out FIRST.
#    Pre-fix this returned only the basename and the skeleton's own project.
run_notify "$WT"
RESOLVED="$(captured)"
cand="$(
  KIPI_INSTANCE_REGISTRY="$TMP/registry.json" \
  KIPI_ALERT_REPO_PATH="$RESOLVED" \
  KIPI_NOTIFY=/usr/bin/true \
  /usr/bin/env python3 - "$WRITER" <<'PY' 2>/dev/null
import importlib.util, sys
spec = importlib.util.spec_from_file_location("a2l", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
# the exact message shape slack-notify.sh builds: "[<basename>] <text>"
print("|".join(mod.project_candidates("[.wt-ask999] a probe alert")))
PY
)"
first="${cand%%|*}"
eq "Board Alias" "$first" "worktree alert resolves to the board alias, best evidence first"

echo "---"
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
