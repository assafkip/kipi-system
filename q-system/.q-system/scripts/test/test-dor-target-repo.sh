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
#
# TWO HOOK MARKERS, EACH WITH ITS REASON (ASK-4899 round 5). Both hooks fired on
# this file and both were right to look:
#
# automation-guard-skip -- this file's HOME is kipi-system, where the guard
# self-detects the skeleton and no-ops. It only trips while a working copy sits
# under an instance's gitignored q-system/output/ during a rework pass. The
# marker acknowledges the scratch location; it does not claim the rule is wrong.
#
# fable-discipline-lint-skip -- the lint sees `bash -n "$WORKER"` and reads it as
# running the worker, which would reach slack-notify.sh and page a real phone
# (scar 2026-08-01). `bash -n` is a SYNTAX check: it parses and exits, and cannot
# execute a command, so it cannot reach any notifier. Nothing else here runs the
# worker; every other worker case is a grep or a verbatim `ready()` extraction
# with the notifier never in scope.
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
# (SCRIPT_DIR, REPO_PROJECT, local_repos) and not merely the call site.
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
    # THE REAL SHAPE, not a string of names (ASK-4899 round 5, finding 2).
    # local_repos is json.loads of `_facts_json local_repos`: a LIST OF DICTS
    # keyed by project / name / path, which the picker already proves by reading
    # r["project"] off the same variable. Feeding the extracted slice this shape
    # is what makes the finding-2 fix load-bearing here -- under the old
    # whitespace split the only clean name in KNOWN_REPOS was SKELETON_PROJECT,
    # so an INSTANCE name was never known and the cross-repo body sailed through.
    "local_repos": json.loads(os.environ["LOCAL_REPOS_JSON"]),
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
# The held record travels back too. A refusal that leaves no trace is finding 3,
# so the wiring case asserts the trace exists at the level that produces it, not
# only that the grep for DOR_HELD matched some text in the file.
verdicts["_held_ids"] = sorted(ns["DOR_HELD"])
print(json.dumps(verdicts))
PY

BODIES="$(python3 -c '
import json, sys
print(json.dumps({"cross": sys.argv[1], "same": sys.argv[2], "none": sys.argv[3]}))
' "$WORK/cross-repo.md" "$WORK/same-repo.md" "$WORK/no-signal.md")"

# The env the worker exports for the picker, set here so the extracted slice
# resolves the engine exactly the way production does.
# The registry shape the worker really hands the picker. `product` is the LAUNCH
# repo and is deliberately NOT keyed the same way in every row: one row carries
# it as `name` with a different `project`, which is the namespace half of
# finding 2. If KNOWN_REPOS only unioned one key, the mirror case below would
# flip.
LOCAL_REPOS_JSON='[{"project":"kipi-system","name":"kipi-system","path":"/x/kipi-system"},
                   {"project":"product","name":"ktlyst","path":"/x/ktlyst-saas/projects/product"},
                   {"project":"ASK Consulting","name":"consulting","path":"/x/consulting"},
                   {"project":"intel","name":"intel","path":"/x/intel"}]'

V="$(WORKER="$WORKER" SCRIPT_DIR="$REPO_SCRIPTS" \
     REPO_PROJECT=product SKELETON_PROJECT=kipi-system \
     LOCAL_REPOS_JSON="$LOCAL_REPOS_JSON" \
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
  # F3, WIRED. The reason has to survive the refusal, not just exist as a name
  # in the file. Exactly one of the three fixture issues is held, so this is
  # also a control: a fix that recorded every issue would show three ids here.
  HELD="$(printf '%s' "$V" | python3 -c 'import json,sys;print(",".join(json.load(sys.stdin)["_held_ids"]))')"
  if [ "$HELD" = "ASK-0" ]; then
    ok "F3 the held ticket and its reason survive into DOR_HELD (exactly one)"
  else
    bad "F3 the held ticket and its reason survive into DOR_HELD (exactly one)" "held=[$HELD] verdicts=$V"
  fi
fi

# F2, WIRED AND LOAD-BEARING. Same body, launched from the INSTANCE name the
# registry row carries as `name` while its `project` differs. Under the old
# whitespace split this repo was never in KNOWN_REPOS, so a DoR naming it was
# invisible; this case is the one that goes red if the union drops `name`.
cat > "$WORK/cross-to-instance.md" <<'MD'
## Definition of Ready

- **Outcome:** the stale instance copy stops being read as authoritative.
- **Files:** `q-system/.q-system/scripts/converge.sh` (in `ktlyst`)
- **Check:** the instance copy matches the skeleton.
MD
OUT="$(python3 "$ENGINE" --body-file "$WORK/cross-to-instance.md" --launch-repo kipi-system --known "kipi-system,ktlyst" 2>&1)"; RC=$?
if [ "$RC" = "1" ] && printf '%s' "$OUT" | grep -q 'ktlyst'; then
  ok "F2 a DoR naming an INSTANCE is refused from the skeleton"
else
  bad "F2 a DoR naming an INSTANCE is refused from the skeleton" "rc=$RC out=$OUT"
fi

printf '\n== review round 4 (claude-reviewer 2026-11-16 13:13 UTC) ==\n'

# F1 -- EVERY DoR PRODUCER IN THE FLEET EMITS A BULLETED HEADING.
# linear-dor-drafter.py:271-281 tells the model to emit `- **Files:**`,
# cap-ladder.py:958 emits `* **Files:**`, and only linear-job-migration.py:152
# emits the bare form. `^\s*` matches whitespace, never `- ` or `* `, so the
# check never fired on a drafter-written DoR -- i.e. on every promoted issue.
cat > "$WORK/bulleted-dash.md" <<'MD'
## Definition of Ready

- **Outcome:** the worker stops burning a dispatch on an unreachable target.
- **Files:** `q-system/.q-system/scripts/linear-worker.sh` (in `kipi-system`)
- **Check:** a test asserts the worker does not cut from the wrong repo.
- **Not doing:** nothing in `product`.
MD

cat > "$WORK/bulleted-star.md" <<'MD'
## Definition of Ready

* **Outcome:** stop the burn.
* **Files:** `q-system/.q-system/scripts/converge.sh` (in `kipi-system`)
* **Check:** bash -n passes.
MD

OUT="$(run_engine "$WORK/bulleted-dash.md" product)"; RC=$?
if [ "$RC" = "1" ] && printf '%s' "$OUT" | grep -q 'kipi-system'; then
  ok "F1 dash-bulleted Files heading is seen (drafter shape)"
else
  bad "F1 dash-bulleted Files heading is seen (drafter shape)" "rc=$RC out=$OUT"
fi

OUT="$(run_engine "$WORK/bulleted-star.md" product)"; RC=$?
if [ "$RC" = "1" ] && printf '%s' "$OUT" | grep -q 'kipi-system'; then
  ok "F1 star-bulleted Files heading is seen (cap-ladder shape)"
else
  bad "F1 star-bulleted Files heading is seen (cap-ladder shape)" "rc=$RC out=$OUT"
fi

# F1, THE HALF THE REVIEW DID NOT NAME. _SECTION_END is root-anchored the same
# way, so once the heading matches, a bulleted `- **Not doing:**` never closes
# the block: the Files section runs to end-of-body and boundary 2 collapses.
# Fixing only the heading turns a dead check into a FALSE-REFUSING one, which is
# worse than dead. This body scopes its files to `product` and merely MENTIONS
# kipi-system in a later bulleted section.
cat > "$WORK/bulleted-later-section.md" <<'MD'
## Definition of Ready

- **Outcome:** the landing page clears its own design gate.
- **Files:** `ktlyst_v2/packaging/landing_page.py` (in `product`)
- **Check:** pytest tests/v2/packaging/ passes.
- **Blast radius:** none. The `kipi-system` copy is untouched.
- **Not doing:** anything in `kipi-system`.
MD

OUT="$(run_engine "$WORK/bulleted-later-section.md" product)"; RC=$?
if [ "$RC" = "0" ] && [ -z "$OUT" ]; then
  ok "F1 a bulleted later section CLOSES the Files block (no false refusal)"
else
  bad "F1 a bulleted later section CLOSES the Files block (no false refusal)" "rc=$RC out=$OUT"
fi

# F4 -- the refusal message asserted "No scoped file exists in the tree", which
# this module never checks and its own boundary 4 disclaims. A message that
# claims a measurement nobody took is the defect; the verdict itself is right.
OUT="$(run_engine "$WORK/cross-repo.md" product)"; RC=$?
if printf '%s' "$OUT" | grep -q 'No scoped file exists'; then
  bad "F4 refusal claims only what it checked" "still asserts an unchecked fact: $OUT"
else
  ok "F4 refusal claims only what it checked"
fi
if printf '%s' "$OUT" | grep -qi 'names only'; then
  ok "F4 refusal describes the signal it actually read"
else
  bad "F4 refusal describes the signal it actually read" "out=$OUT"
fi

# F5 -- an unreadable --body-file tracebacked to a non-zero exit, which the
# caller cannot tell from a real cross-repo refusal, against a stated fail-open
# contract. A missing body must read as no signal: exit 0, nothing on stdout.
OUT="$(python3 "$ENGINE" --body-file "$WORK/does-not-exist.md" --launch-repo product --known "$KNOWN" 2>/dev/null)"; RC=$?
if [ "$RC" = "0" ] && [ -z "$OUT" ]; then
  ok "F5 unreadable --body-file fails OPEN (exit 0, silent stdout)"
else
  bad "F5 unreadable --body-file fails OPEN (exit 0, silent stdout)" "rc=$RC out=$OUT"
fi
ERRTXT="$(python3 "$ENGINE" --body-file "$WORK/does-not-exist.md" --launch-repo product --known "$KNOWN" 2>&1 >/dev/null)"
if printf '%s' "$ERRTXT" | grep -q 'Traceback'; then
  bad "F5 unreadable --body-file does not traceback" "stderr=$ERRTXT"
else
  ok "F5 unreadable --body-file does not traceback"
fi
if [ -n "$ERRTXT" ]; then
  ok "F5 the unreadable body is still named on stderr (not silent)"
else
  bad "F5 the unreadable body is still named on stderr (not silent)" "stderr was empty"
fi

printf '\n== worker-side findings (static, against the real file) ==\n'

# F2 -- LOCAL_REPOS is json.dumps of a LIST OF DICTS (proven by linear-worker.sh
# parsing it back as r["project"] in the same heredoc). Splitting that string on
# whitespace or commas can only yield tokens like `[{"project":`, so the only
# clean name KNOWN_REPOS ever held was SKELETON_PROJECT. A DoR naming any
# INSTANCE therefore found nothing and proceeded.
if grep -q 'os.environ.get("LOCAL_REPOS", "") or "").split()' "$WORKER"; then
  bad "F2 KNOWN_REPOS parses LOCAL_REPOS as JSON, not by splitting a string" \
      "the whitespace split is still there"
else
  ok "F2 KNOWN_REPOS parses LOCAL_REPOS as JSON, not by splitting a string"
fi

# F2, namespace half: rows are keyed by the Linear `project`, while LAUNCH_REPO
# is the registry `name` or the checkout basename. Comparing one namespace with
# the other misses a repo whose two names differ, so the union has to carry all
# three keys.
if grep -q 'for _k in ("project", "name", "slug")' "$WORKER"; then
  ok "F2 KNOWN_REPOS unions project + name + slug (one namespace)"
else
  bad "F2 KNOWN_REPOS unions project + name + slug (one namespace)" \
      "no union over the registry row keys"
fi

# F3 -- the refusal discarded its reason: no count, no log line, no label. A held
# ticket then read as owned while nothing reported it, and the operator saw the
# queue shrink with no explanation. The DROPPED counter two hundred lines below
# is the shape this had to match.
if grep -q 'DOR_HELD' "$WORKER"; then
  ok "F3 the picker records the held ticket and its reason"
else
  bad "F3 the picker records the held ticket and its reason" "no DOR_HELD record"
fi
if grep -q 'DOR_HELD_COUNT' "$WORKER"; then
  ok "F3 the held count reaches the shell so a run can report it"
else
  bad "F3 the held count reaches the shell so a run can report it" "no DOR_HELD_COUNT"
fi

# F6 -- REPO_PROJECT was exported twice, and WORKER_SCRIPT_DIR duplicated
# SCRIPT_DIR, which the same heredoc already reads from the env at the
# `pathlib.Path(os.environ["SCRIPT_DIR"])` line.
if [ "$(grep -c '^export REPO_PROJECT$' "$WORKER")" = "1" ]; then
  ok "F6 REPO_PROJECT is exported once"
else
  bad "F6 REPO_PROJECT is exported once" "count=$(grep -c '^export REPO_PROJECT$' "$WORKER")"
fi
# Asserted on real USES, not on any mention: the why-comment recording the
# removal names the dead variable on purpose, and a test that forbade naming it
# would delete the explanation along with the duplicate. The shapes below are
# every way the value could still be set or read.
if grep -qE '^[ \t]*(export[ \t]+)?WORKER_SCRIPT_DIR=|^[ \t]*export[ \t]+WORKER_SCRIPT_DIR|environ[^)]*WORKER_SCRIPT_DIR|\$\{?WORKER_SCRIPT_DIR' "$WORKER"; then
  bad "F6 the picker reads SCRIPT_DIR, not a duplicate of it" \
      "$(grep -nE '^[ \t]*(export[ \t]+)?WORKER_SCRIPT_DIR=|^[ \t]*export[ \t]+WORKER_SCRIPT_DIR|environ[^)]*WORKER_SCRIPT_DIR|\$\{?WORKER_SCRIPT_DIR' "$WORKER")"
else
  ok "F6 the picker reads SCRIPT_DIR, not a duplicate of it"
fi
# The replacement has to be live, not merely the duplicate gone.
if grep -q 'os.environ.get("SCRIPT_DIR", "")' "$WORKER"; then
  ok "F6 the picker resolves the engine from the exported SCRIPT_DIR"
else
  bad "F6 the picker resolves the engine from the exported SCRIPT_DIR" "no SCRIPT_DIR read in the picker"
fi

# F7 -- the block headed NO APOSTROPHES ANYWHERE contained an apostrophe. Latent
# rather than live (bash -n passed), and latent is exactly how the scar the
# comment records got written in the first place.
APOS="$(python3 - "$WORKER" <<'PY'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().split("\n")
start = next((i for i, l in enumerate(lines) if "NO APOSTROPHES ANYWHERE IN THIS BLOCK" in l), None)
if start is None:
    print("MARKER-GONE"); raise SystemExit
end = next((i for i in range(start, len(lines)) if lines[i].startswith("def ready(i):")), len(lines))
print("\n".join(f"{i+1}: {lines[i]}" for i in range(start, end) if "'" in lines[i]))
PY
)"
if [ -z "$APOS" ]; then
  ok "F7 the NO-APOSTROPHES block holds no apostrophe"
else
  bad "F7 the NO-APOSTROPHES block holds no apostrophe" "$APOS"
fi

# The scar the comment names is a PARSE break, so the parse is what gets pinned.
if bash -n "$WORKER" 2>/dev/null; then
  ok "the worker still parses (bash -n)"
else
  bad "the worker still parses (bash -n)" "bash -n failed"
fi

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" = "0" ]
