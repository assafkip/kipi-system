#!/usr/bin/env bash
# ASK-4899: an issue whose DoR scopes its files to another repo must be refused
# BEFORE a worktree is cut, and every other issue must still be picked up.
#
# Pairs with q-system/.q-system/scripts/dor_target_repo.py (the engine) and with
# the `ready()` filter in linear-worker.sh (the wiring).
#
# WHY THE WIRING CASE RUNS ready() VERBATIM
# -----------------------------------------
# Cases 1-3 test the engine, which is pure. Case 4 has to prove the WORKER
# actually consults it -- an engine nobody calls is the load-path scar
# (wiring-check.md), and a test that only exercised the module would pass on a
# worker that ignores it. So case 4 extracts ready() out of linear-worker.sh and
# executes it against fixture issues, the same technique
# test_linear_alert_triage.py already uses on the same function. It reads the
# real file, so deleting the call site turns case 4 red.
#
# NO LIVE LINEAR AND NO LIVE GIT. Every case is driven by a fixture issue body.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
ENGINE="$REPO_SCRIPTS/dor_target_repo.py"
WORKER="${KIPI_WORKER_UNDER_TEST:-$REPO_SCRIPTS/linear-worker.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

KNOWN="kipi-system,product,consulting,intel"

# --- fixture bodies ---------------------------------------------------------
# ASK-4899's own shape: a DoR whose every Files entry names kipi-system, filed
# in the `product` project because that is where the finding was OBSERVED.
cat > "$WORK/cross-repo.md" <<'MD'
## Definition of Ready

**Outcome:** the worker stops burning a dispatch on an unreachable target.

**Files:**

* `q-system/.q-system/scripts/linear-worker.sh` (in `kipi-system`) -- the repo
  resolution at line ~57 and the `worktree add` at line ~776.
* `tests/` in `kipi-system` -- a new suite pinning the routing decision.

**Check (reproducer first):**

- [ ] A test asserts the worker does not cut from the wrong repo.
MD

# The launch-repo case. Same shape, files named in the repo we are running in.
cat > "$WORK/same-repo.md" <<'MD'
## Definition of Ready

**Outcome:** the landing page stops failing its own design gate.

**Files:**

* `ktlyst_v2/packaging/landing_page.py` (in `product`) -- the renderer.

**Check:** pytest tests/v2/packaging/ passes.
MD

# No parseable Files section at all. The commonest shape in the queue.
cat > "$WORK/no-signal.md" <<'MD'
## Definition of Ready

**Outcome:** the advisors CLI exits 0 on a clean run.

**Check:** `ktlyst advisors output/run-x` exits 0.
MD

# A sibling repo named in PROSE but not in the Files section. Must NOT refuse:
# boundary 2 of the engine's docstring.
cat > "$WORK/prose-mention.md" <<'MD'
## Definition of Ready

**Outcome:** stop reading the stale copy. The `kipi-system` copy is
authoritative and the instance copy drifted.

**Files:**

* `ktlyst_v2/cli.py` (in `product`) -- the entrypoint.
MD

run_engine() {  # run_engine <body-file> <launch-repo>
  python3 "$ENGINE" --body-file "$1" --launch-repo "$2" --known "$KNOWN" 2>&1
  return $?
}

printf '\n== engine ==\n'

# CASE 1 -- THE REPRODUCER. RED before the engine exists.
OUT="$(run_engine "$WORK/cross-repo.md" product)"; RC=$?
if [ "$RC" = "1" ] && printf '%s' "$OUT" | grep -q 'kipi-system' \
   && printf '%s' "$OUT" | grep -q 'product'; then
  ok "cross-repo DoR refused, naming both repos"
else
  bad "cross-repo DoR refused, naming both repos" "rc=$RC out=$OUT"
fi

# CASE 2 -- NEGATIVE SELF-TEST 1, non-negotiable. A fix that refuses everything
# is not a fix.
OUT="$(run_engine "$WORK/same-repo.md" product)"; RC=$?
if [ "$RC" = "0" ] && [ -z "$OUT" ]; then
  ok "same-repo DoR proceeds (negative self-test 1)"
else
  bad "same-repo DoR proceeds (negative self-test 1)" "rc=$RC out=$OUT"
fi

# CASE 3 -- NEGATIVE SELF-TEST 2. Absence of a signal is not a mismatch.
OUT="$(run_engine "$WORK/no-signal.md" product)"; RC=$?
if [ "$RC" = "0" ] && [ -z "$OUT" ]; then
  ok "no Files section proceeds (negative self-test 2)"
else
  bad "no Files section proceeds (negative self-test 2)" "rc=$RC out=$OUT"
fi

# CASE 4 -- a repo named only in prose is not a scope declaration.
OUT="$(run_engine "$WORK/prose-mention.md" product)"; RC=$?
if [ "$RC" = "0" ] && [ -z "$OUT" ]; then
  ok "repo named in prose only proceeds"
else
  bad "repo named in prose only proceeds" "rc=$RC out=$OUT"
fi

# CASE 5 -- the mirror of case 1: run the SAME body from kipi-system and it must
# proceed. This is what proves the verdict tracks the launch repo rather than
# simply disliking that body.
OUT="$(run_engine "$WORK/cross-repo.md" kipi-system)"; RC=$?
if [ "$RC" = "0" ] && [ -z "$OUT" ]; then
  ok "cross-repo DoR proceeds when launched from the repo it names"
else
  bad "cross-repo DoR proceeds when launched from the repo it names" "rc=$RC out=$OUT"
fi

printf '\n== wiring: the worker consults the engine ==\n'

# The worker must NAME the engine. Cheap, and it is the first thing to break if
# the call site is deleted.
if grep -q 'dor_target_repo' "$WORKER"; then
  ok "linear-worker.sh names dor_target_repo"
else
  bad "linear-worker.sh names dor_target_repo" "no reference in $WORKER"
fi

# ready() EXECUTED VERBATIM out of the worker, against the three fixture issues.
# Extracting the function rather than asserting on grep output is what makes
# this a behaviour test: a call site that is present but inverted fails here.
cat > "$WORK/ready_harness.py" <<'PY'
import json, os, re, sys

worker = open(os.environ["WORKER"], encoding="utf-8").read()

# Extract the REAL block: the LAUNCH_REPO/KNOWN_REPOS constants, the
# dor_targets_another_repo helper, and ready() itself -- from the first constant
# through the end of ready(). Taking all three together means the live import of
# dor_target_repo.py runs for real, so this case also covers the env plumbing
# (WORKER_SCRIPT_DIR, REPO_PROJECT, LOCAL_REPOS) and not merely the call site.
start = worker.find('LAUNCH_REPO = os.environ.get("REPO_PROJECT"')
if start < 0:
    print("EXTRACT-FAIL: no LAUNCH_REPO constant in the worker")
    sys.exit(3)
m = re.search(r"^def ready\(i\):.*?(?=^def )", worker[start:], re.MULTILINE | re.DOTALL)
if not m:
    print("EXTRACT-FAIL: no top-level def ready(i) after the constants")
    sys.exit(3)
src = worker[start : start + m.end()]

# The collaborators ready() calls that are not under test here. Each is stubbed
# to the permissive answer, so the ONLY thing that can drop a fixture issue is
# the DoR-repo check this suite is about. os and sys are injected because the
# extracted slice sits mid-file, below the imports of the picker.
ns = {
    "os": os,
    "sys": sys,
    "is_fleet_alert": lambda i: False,
    "in_this_repo": lambda i: True,
    "started_open": lambda i, d: False,
    "QUEUE_STATES": ("backlog", "unstarted"),
}
try:
    exec(compile(src, "worker:ready", "exec"), ns)
except Exception as exc:                      # noqa: BLE001 -- reported, not swallowed
    print(f"EXEC-FAIL: {type(exc).__name__}: {exc}")
    sys.exit(3)

def issue(body):
    return {"identifier": "ASK-0", "labels": {"nodes": [{"name": "owner:sana"}]},
            "state": {"name": "Backlog", "type": "backlog"}, "description": body}

verdicts = {}
for name, path in json.loads(os.environ["BODIES"]).items():
    verdicts[name] = bool(ns["ready"](issue(open(path, encoding="utf-8").read())))
print(json.dumps(verdicts))
PY

BODIES="$(python3 -c '
import json, sys
print(json.dumps({"cross": sys.argv[1], "same": sys.argv[2], "none": sys.argv[3]}))
' "$WORK/cross-repo.md" "$WORK/same-repo.md" "$WORK/no-signal.md")"

# The env the worker exports for the picker, set here so the extracted slice
# resolves the engine exactly the way production does.
V="$(WORKER="$WORKER" WORKER_SCRIPT_DIR="$REPO_SCRIPTS" \
     REPO_PROJECT=product SKELETON_PROJECT=kipi-system \
     LOCAL_REPOS="$(printf '%s' "$KNOWN" | tr ',' ' ')" \
     BODIES="$BODIES" python3 "$WORK/ready_harness.py" 2>&1)"; RC=$?

if [ "$RC" != "0" ]; then
  bad "ready() runs against fixtures" "rc=$RC $V"
else
  ok "ready() runs against fixtures"
  get() { printf '%s' "$V" | python3 -c "import json,sys;print(json.load(sys.stdin)['$1'])"; }
  if [ "$(get cross)" = "False" ]; then
    ok "ready() holds the cross-repo issue out of the queue"
  else
    bad "ready() holds the cross-repo issue out of the queue" "verdicts=$V"
  fi
  if [ "$(get same)" = "True" ]; then
    ok "ready() still picks the same-repo issue (negative self-test 1, wired)"
  else
    bad "ready() still picks the same-repo issue (negative self-test 1, wired)" "verdicts=$V"
  fi
  if [ "$(get none)" = "True" ]; then
    ok "ready() still picks the no-signal issue (negative self-test 2, wired)"
  else
    bad "ready() still picks the no-signal issue (negative self-test 2, wired)" "verdicts=$V"
  fi
fi

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" = "0" ]
