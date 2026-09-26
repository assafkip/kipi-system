#!/usr/bin/env bash
# Reproducer + regression suite for linear-route-reachability-check.py (ASK-1951).
#
# WHAT IT PROVES, AND WHY IT IS SHAPED THIS WAY
# ---------------------------------------------
# It drives the REAL check script against a fixture Linear board, through the
# transport seam linear-sync.py already exposes (KIPI_LINEAR_API_URL), and
# against fixture instance-registry.json files written per case. No predicate is
# re-implemented here; every assertion reads the script's own exit code and its
# own printed report.
#
# THE NEGATIVE CONTROL IS CASE 2, AND IT IS THE POINT. The ticket's own words:
# "temporarily point one known-good issue at a project name that is not in the
# registry and confirm the check goes red. A check that cannot fail is not a
# check." Case 1 and case 2 differ by ONE field -- the project name on one issue
# -- so a green case 1 beside a red case 2 is evidence the check reads the thing
# it claims to read, not that it happens to exit 0.
#
# CASE 7 IS THE DIVERGENCE GUARD. The check mirrors `ready_ignoring_project` from
# inside a bash heredoc in linear-worker.sh, which cannot be imported. A mirror
# agrees on the day it is written; that is what makes it dangerous. So this suite
# runs the REAL worker and the REAL check over ONE board and asserts their two
# counts stay in the relation the shared predicate implies. Add a held label to
# one side only and case 7 goes red instead of quiet.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECK="$REPO_SCRIPTS/linear-route-reachability-check.py"
WORKER="$REPO_SCRIPTS/linear-worker.sh"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

# --- fixture Linear ---------------------------------------------------------
# Answers the two queries the check makes, distinguished by body content the way
# the real endpoint would route them. The board mirrors the live one's SHAPE: one
# issue per exclusion the check applies, plus the reachable/unreachable pair the
# negative control turns on.
cat > "$WORK/fixture-server.py" <<'PY'
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

def issue(ident, project, labels, dor=True, state="backlog", alert=False):
    body = "## Definition of Ready\nOutcome: x" if dor else "no readiness heading"
    if alert:
        body += "\n\n<!-- kipi-alert-fingerprint: deadbeefdeadbeef -->"
    return {
        "id": ident, "identifier": ident, "title": "fixture " + ident,
        "description": body,
        "state": {"name": state, "type": state},
        "project": ({"name": project} if project else None),
        "labels": {"nodes": [{"name": n} for n in labels]},
    }

# FIXTURE_TARGET names the project the one movable issue sits on. Cases 1 and 2
# differ only in this value, which is what makes case 2 a control rather than a
# second scenario.
TARGET = os.environ.get("FIXTURE_TARGET", "kipi-system")
ACK = os.environ.get("FIXTURE_ACK", "") == "1"

def board():
    ack_labels = ["owner:sana"] + (["route:unreachable"] if ACK else [])
    return [
        # the movable one: reachable or not depending on TARGET
        issue("ASK-900", TARGET, ack_labels),
        # always reachable: a project the fixture registry always backs
        issue("ASK-901", "kipi-system", ["owner:sana"]),
        # every exclusion the shape predicate applies, each on an UNREGISTERED
        # project so that a predicate leak shows up as an unreachable row
        issue("ASK-902", "ghost-project", ["owner:assaf"]),              # founder
        issue("ASK-903", "ghost-project", []),                            # no owner
        issue("ASK-904", "ghost-project", ["owner:sana", "needs-scope"]),
        issue("ASK-905", "ghost-project", ["owner:sana", "blocked:capability"]),
        issue("ASK-906", "ghost-project", ["owner:sana"], dor=False),
        issue("ASK-907", "ghost-project", ["owner:sana"], state="completed"),
        issue("ASK-908", "ghost-project", ["owner:sana"], alert=True),
        # no project at all: ASK-1887 owns that bucket, this check must not
        # count it as unreachable
        issue("ASK-909", None, ["owner:sana"]),
    ]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        if "teams(" in body:
            data = {"teams": {"nodes": [{"id": "team-fixture"}]}}
        else:
            data = {"issues": {"nodes": board(),
                               "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        out = json.dumps({"data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

srv = HTTPServer(("127.0.0.1", 0), H)
print(srv.server_port, flush=True)
srv.serve_forever()
PY

start_server() {  # start_server [env assignments...]
  kill "${SRV_PID:-}" 2>/dev/null
  : > "$WORK/port"
  env "$@" python3 "$WORK/fixture-server.py" > "$WORK/port" 2> "$WORK/server.err" &
  SRV_PID=$!
  local _
  for _ in $(seq 1 100); do
    PORT="$(cat "$WORK/port" 2>/dev/null)"
    [ -n "${PORT:-}" ] && break
    sleep 0.1
  done
  [ -n "${PORT:-}" ] || { echo "fixture server did not start: $(cat "$WORK/server.err")"; exit 1; }
}

# --- fixture registries -----------------------------------------------------
# A row only counts when its DIRECTORY EXISTS, so each registry below is written
# beside real directories. `mkdir -p` first, then the JSON naming them.
mkdir -p "$WORK/repos/kipi-system" "$WORK/repos/backed"

# The skeleton row carries kipi-system. It is a SIBLING of `instances`, not a
# member, and the pre-fix derivation iterated `instances` only -- so this file is
# also the regression fixture for that omission (case 4).
cat > "$WORK/reg-normal.json" <<JSON
{
  "skeleton": {"path": "$WORK/repos/kipi-system", "linear_project": "kipi-system"},
  "instances": [
    {"name": "backed-row", "linear_project": "backed", "path": "$WORK/repos/backed"}
  ]
}
JSON

# Same rows, but the skeleton's project is the ONLY one that can back the
# movable issue. Used by case 4 on its own so a pass cannot come from `instances`.
cat > "$WORK/reg-skeleton-only.json" <<JSON
{
  "skeleton": {"path": "$WORK/repos/kipi-system", "linear_project": "kipi-system"},
  "instances": []
}
JSON

printf 'not json at all' > "$WORK/reg-broken.json"

# KIPI_NOTIFY is isolation, not a nicety. No case below passes --notify, so the
# notifier is unreachable today -- and that is exactly the guarantee that rots the
# first time someone adds a --notify case. Stubbed at the ONE call site every case
# goes through, so the guarantee does not depend on remembering. Scar 2026-08-01:
# a suite reporting 14/14 green reached the real notifier and paged the founder
# twice.
run_check_rc() {  # prints into OUT, sets RC
  local reg="$1"; shift
  OUT="$(env KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
             KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
             KIPI_NOTIFY="/usr/bin/true" \
             python3 "$CHECK" --registry "$reg" "$@" 2>&1)"
  RC=$?
}

echo "== linear-route-reachability-check.py"

# --- case 1: the movable issue on a BACKED project -> green ------------------
start_server FIXTURE_TARGET=backed
run_check_rc "$WORK/reg-normal.json"
if [ "$RC" -eq 0 ]; then
  ok "backed project: exit 0"
else
  bad "backed project: exit 0" "rc=$RC out=$(printf '%s' "$OUT" | tr '\n' '|')"
fi
case "$OUT" in
  *"0 unacknowledged unreachable"*) ok "backed project: nothing unreachable" ;;
  *) bad "backed project: nothing unreachable" "$(printf '%s' "$OUT" | tr '\n' '|')" ;;
esac
# The exclusions are the same board rows in every case. Shaped is 3, not 2:
# ASK-900 and ASK-901 carry a project, and ASK-909 carries NONE. The shape
# predicate is deliberately silent about the project -- an unset project is a
# routing fact, reported on its own line and owned by ASK-1887, not a reason to
# call an issue unshaped. If any of the seven excluded rows leaked in, this count
# would exceed 3.
case "$OUT" in
  *"3 dispatchable-shaped issue(s)"*) ok "exclusions hold: shaped == 3" ;;
  *) bad "exclusions hold: shaped == 3" "$(printf '%s' "$OUT" | tr '\n' '|')" ;;
esac

# --- case 2: NEGATIVE CONTROL -- one field changed, the check must go red ----
# Identical board, identical registry. Only ASK-900's project name differs, and
# it names a project no registry row declares.
start_server FIXTURE_TARGET=lane-h-digest-repeats
run_check_rc "$WORK/reg-normal.json"
if [ "$RC" -eq 2 ]; then
  ok "NEGATIVE CONTROL: unregistered project exits 2"
else
  bad "NEGATIVE CONTROL: unregistered project exits 2" \
      "rc=$RC out=$(printf '%s' "$OUT" | tr '\n' '|')"
fi
case "$OUT" in
  *"lane-h-digest-repeats (1): ASK-900"*) ok "names the issue and its project" ;;
  *) bad "names the issue and its project" "$(printf '%s' "$OUT" | tr '\n' '|')" ;;
esac
case "$OUT" in
  *"no instance-registry.json row names this project"*) ok "prints the actionable reason" ;;
  *) bad "prints the actionable reason" "$(printf '%s' "$OUT" | tr '\n' '|')" ;;
esac

# --- case 3: the acknowledgement label moves it out of the ALARM, not the report
start_server FIXTURE_TARGET=lane-h-digest-repeats FIXTURE_ACK=1
run_check_rc "$WORK/reg-normal.json"
if [ "$RC" -eq 0 ]; then
  ok "route:unreachable clears the alarm"
else
  bad "route:unreachable clears the alarm" "rc=$RC out=$(printf '%s' "$OUT" | tr '\n' '|')"
fi
# A label that DELETED the finding would be a bypass. The acknowledged bucket is
# printed on every run precisely so a queue silenced by labelling still reads as
# a queue.
case "$OUT" in
  *"ACKNOWLEDGED (route:unreachable)"*"ASK-900"*) ok "acknowledged rows stay printed" ;;
  *) bad "acknowledged rows stay printed" "$(printf '%s' "$OUT" | tr '\n' '|')" ;;
esac

# --- case 4: the SKELETON row backs a checkout (ASK-1951 second-order) -------
# The pre-fix derivation iterated reg["instances"] only, so the skeleton's own
# project resolved to nothing and 124 live kipi-system issues read as
# unreachable. Registry here has an EMPTY instances list, so a pass can only
# come from reading the skeleton row.
start_server FIXTURE_TARGET=kipi-system
run_check_rc "$WORK/reg-skeleton-only.json"
if [ "$RC" -eq 0 ]; then
  ok "skeleton row backs its project (instances empty)"
else
  bad "skeleton row backs its project (instances empty)" \
      "rc=$RC out=$(printf '%s' "$OUT" | tr '\n' '|')"
fi

# --- case 5: an unreadable registry is UNKNOWN, never a board-wide alarm -----
start_server FIXTURE_TARGET=lane-h-digest-repeats
run_check_rc "$WORK/reg-broken.json"
if [ "$RC" -eq 0 ]; then
  ok "unreadable registry: exit 0, not a false alarm on everything"
else
  bad "unreadable registry: exit 0" "rc=$RC out=$(printf '%s' "$OUT" | tr '\n' '|')"
fi
case "$OUT" in
  *"UNKNOWN"*"this is not a pass"*) ok "unreadable registry says UNKNOWN out loud" ;;
  *) bad "unreadable registry says UNKNOWN out loud" "$(printf '%s' "$OUT" | tr '\n' '|')" ;;
esac

# --- case 6: the project-unset population belongs to ASK-1887, not here ------
start_server FIXTURE_TARGET=backed
run_check_rc "$WORK/reg-normal.json" --json
UNSET="$(printf '%s' "$OUT" | python3 -c 'import json,sys;print(",".join(json.load(sys.stdin)["unset_project"]))' 2>/dev/null)"
case "$UNSET" in
  "ASK-909") ok "unset project reported separately, not as unreachable" ;;
  *) bad "unset project reported separately" "unset_project=[$UNSET]" ;;
esac

# --- case 7: DIVERGENCE GUARD -- the worker and the check share one shape ----
# The check mirrors ready_ignoring_project from a bash heredoc it cannot import.
# Both sides run over ONE board here, with FIXTURE_TARGET=kipi-system so that
# both project-carrying shaped issues (ASK-900, ASK-901) are in the worker's own
# repo. The relation the shared predicate implies is therefore:
#
#     worker ready  ==  check shaped  -  check unset_project
#
# The subtraction is not slack in the assertion; it is the ONE documented
# difference between the two sides. `in_this_repo` treats an unset project as NOT
# this repo on purpose ("target unknown" and "target is here" are different
# claims, and conflating them put 18 foreign issues in the queue), while the
# check counts an unset issue as shaped and reports it separately. Every other
# clause -- both owner labels, both held labels, the state types, the alert
# marker, the DoR string -- is shared, and dropping or adding one on either side
# breaks this equality.
setup_skel() {
  local root="$WORK/repos/kipi-system"
  git init --quiet --bare "$WORK/origin.git"
  git init --quiet "$root" 2>/dev/null
  git -C "$root" config user.email t@t; git -C "$root" config user.name t
  : > "$root/seed"; git -C "$root" add seed
  git -C "$root" commit --quiet -m seed 2>/dev/null
  git -C "$root" remote add origin "$WORK/origin.git" 2>/dev/null
  git -C "$root" push --quiet -u origin HEAD:main 2>/dev/null
  cp "$WORK/reg-normal.json" "$root/instance-registry.json"
}
setup_skel
start_server FIXTURE_TARGET=kipi-system
W_OUT="$(env KIPI_SKEL="$WORK/repos/kipi-system" \
             KIPI_STATE_DIR="$WORK/state" \
             KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
             KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
             KIPI_NOTIFY="/usr/bin/true" \
             bash "$WORKER" --limit 99 2>&1)"
W_READY="$(printf '%s\n' "$W_OUT" | sed -n 's/.*worker: \([0-9]*\) ready issue(s).*/\1/p' | head -1)"
run_check_rc "$WORK/repos/kipi-system/instance-registry.json" --json
C_ROUTED="$(printf '%s' "$OUT" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["shaped"] - len(d["unset_project"]))' 2>/dev/null)"
if [ -z "$W_READY" ]; then
  bad "divergence guard: worker printed a ready count" \
      "no ready line: $(printf '%s' "$W_OUT" | tr '\n' '|' | cut -c1-400)"
elif [ -z "$C_ROUTED" ]; then
  bad "divergence guard: check printed a shaped count" \
      "no json: $(printf '%s' "$OUT" | tr '\n' '|' | cut -c1-400)"
elif [ "$W_READY" = "$C_ROUTED" ]; then
  ok "divergence guard: worker ready ($W_READY) == check shaped-with-project ($C_ROUTED)"
else
  bad "divergence guard: worker and check disagree on the shape predicate" \
      "worker ready=$W_READY check shaped-with-project=$C_ROUTED"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
