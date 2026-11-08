#!/usr/bin/env bash
# The worker leaves an expired park to E2, and only the parks E2 will close
# (ASK-3995, D24 of the stuck-work synthesis 2026-11-07).
#
# WHY THIS EXISTS. On 2026-11-08 the first dispatch of the day went to ASK-834, a
# No-priority ticket parked 25 days past its review date, while an Urgent ticket
# waited. A park is chief's countdown to a close: at the date, E2 (chief
# park_expired) closes it, reversibly. Working one spends a dispatch the board
# already ruled closed by age, and races E2 until the first push.
#
# THE OTHER EDGE IS THE ONE THAT HURTS. A refusal wider than E2's set strands a
# ticket: the worker will not pick it and E2 will not close it. So every arm of
# E2's predicate has a case here, and each one must stay PICKABLE: a date ahead,
# a date of today (E2 is strict), Todo, each NEVER_AUTO_CLOSE label, an open
# sana PR (E2's open-PR rail), and no date at all.
#
# THE SEAM is test-worker-priority-order.sh's: the REAL picker against a fixture
# Linear through KIPI_LINEAR_API_URL. The fixture STRIPS dueDate unless the query
# selects it, because real Linear returns only selected fields: a worker that read
# a field it never asked for would pass here and refuse nothing live.
#
# REF HATCH: KIPI_WORKER_UNDER_TEST points at another copy of linear-worker.sh,
# so the pre-fix worker can be watched to FAIL.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER="${KIPI_WORKER_UNDER_TEST:-$REPO_SCRIPTS/linear-worker.sh}"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; wait "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

cat > "$WORK/fixture-server.py" <<'PY'
import datetime, json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

# The LOCAL date, the clock E2 compares against (now.astimezone().date()).
TODAY = datetime.datetime.now().astimezone().date().isoformat()
PAST = "2020-01-01"
AHEAD = "2099-01-01"

def issue(ident, created, due, labels=(), state="backlog", priority=2):
    return {"id": ident, "identifier": ident, "title": "fixture " + ident,
            "description": "## Definition of Ready\nOutcome: x",
            "state": {"name": "Backlog" if state == "backlog" else "Todo", "type": state},
            "startedAt": None, "project": {"name": "kipi-system"},
            "labels": {"nodes": [{"name": n} for n in ("owner:sana",) + tuple(labels)]},
            "createdAt": created, "priority": priority, "dueDate": due}

# Same priority, so the order is oldest first and the picks read in id order.
BOARD = [
    issue("ASK-971", "2026-08-01T10:00:00.000Z", PAST, ("parked",)),               # E2 closes it
    issue("ASK-972", "2026-08-02T10:00:00.000Z", AHEAD, ("parked",)),              # date ahead
    issue("ASK-973", "2026-08-03T10:00:00.000Z", TODAY, ("parked",)),              # due today
    issue("ASK-974", "2026-08-04T10:00:00.000Z", PAST, ("parked",), "unstarted"),  # Todo
    issue("ASK-975", "2026-08-05T10:00:00.000Z", PAST, ("parked", "security")),
    issue("ASK-976", "2026-08-06T10:00:00.000Z", PAST, ("parked", "ready")),
    issue("ASK-977", "2026-08-07T10:00:00.000Z", PAST, ("parked", "frozen")),
    issue("ASK-978", "2026-08-08T10:00:00.000Z", PAST, ("parked", "data-loss")),
    issue("ASK-979", "2026-08-09T10:00:00.000Z", PAST, ("parked",)),               # open sana PR
    issue("ASK-980", "2026-08-10T10:00:00.000Z", None, ("parked",)),               # no date
    issue("ASK-981", "2026-08-11T10:00:00.000Z", PAST, ()),                        # dated, not parked
    issue("ASK-982", "2026-08-12T10:00:00.000Z", PAST, ("parked",)),               # E2 closes it
]
# ASK-4043 nit: a board whose ONLY pickable ticket is an expired Urgent park, for
# the plain --limit 1 scan the urgent slot runs (FIXTURE_BOARD=urgent-park).
if os.environ.get("FIXTURE_BOARD") == "urgent-park":
    BOARD = [issue("ASK-990", "2026-08-01T10:00:00.000Z", PAST, ("parked",), priority=1)]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        if "teams(" in body:
            data = {"teams": {"nodes": [{"id": "team-fixture"}]}}
        else:
            nodes = json.loads(json.dumps(BOARD))
            q = json.loads(body).get("query", "")
            for n in nodes:
                if "dueDate" not in q:
                    n.pop("dueDate", None)
            data = {"issues": {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}
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

# stderr to a file: a child holding the suite's stderr keeps a caller's pipe open.
python3 "$WORK/fixture-server.py" > "$WORK/port" 2> "$WORK/server.err" &
SRV_PID=$!
for _ in $(seq 1 100); do
  PORT="$(cat "$WORK/port" 2>/dev/null)"
  [ -n "${PORT:-}" ] && break
  sleep 0.1
done
[ -n "${PORT:-}" ] || { echo "fixture server did not start: $(cat "$WORK/server.err" 2>/dev/null)"; exit 1; }

# A GitHub-shaped origin, so the worker lists open PRs (the WIP block asks gh only
# when the repo has a slug). insteadOf sends the fetch to the local bare repo.
ROOT="$WORK/kipi-system"
git init --quiet --bare "$WORK/origin.git" && git -C "$WORK/origin.git" symbolic-ref HEAD refs/heads/main
git init --quiet "$ROOT"
git -C "$ROOT" config user.email t@t; git -C "$ROOT" config user.name t
: > "$ROOT/seed"; git -C "$ROOT" add seed; git -C "$ROOT" commit --quiet -m seed
git -C "$ROOT" remote add origin "$WORK/origin.git"
git -C "$ROOT" push --quiet -u origin HEAD:main 2>/dev/null
git -C "$ROOT" config url."$WORK/origin.git".insteadOf "https://github.com/x/kipi-system.git"
git -C "$ROOT" remote set-url origin "https://github.com/x/kipi-system.git"

# gh answers the open-PR list from a file. One open PR, on a lane-shaped head for
# ASK-979, the shape E2's open-PR rail protects.
STUBS="$WORK/bin"; mkdir -p "$STUBS"
printf '979\tsana/ask-979-fix\t2026-10-01T12:00:00Z\thttps://github.com/x/kipi-system/pull/979\n' > "$WORK/prs.tsv"
cat > "$STUBS/gh" <<'GH'
#!/usr/bin/env bash
case "$*" in
  *"pr list"*"--state open"*)
    [ "${FIXTURE_GH_FAIL:-0}" = "1" ] && { echo "gh: HTTP 502: Bad Gateway" >&2; exit 1; }
    cat "$FIXTURE_PRS" 2>/dev/null ;;
esac
exit 0
GH
chmod +x "$STUBS/gh"

# KIPI_NOTIFY=/usr/bin/true: a suite that can reach slack-notify.sh pages the founder.
run_worker() {  # run_worker <worker args...>
  env PATH="$STUBS:$PATH" FIXTURE_PRS="$WORK/prs.tsv" \
      KIPI_SKEL="$ROOT" KIPI_STATE_DIR="$WORK/state" \
      KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
      KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" KIPI_NOTIFY="/usr/bin/true" \
      bash "$WORKER" "$@" 2>&1
}
# A board-switching server run: FIXTURE_BOARD is read when the server starts, so
# this starts a second server for the one call and stops it after.
run_worker_board() {  # run_worker_board <worker args...>
  local port2 pid2 out
  FIXTURE_BOARD="${FIXTURE_BOARD:-}" python3 "$WORK/fixture-server.py" > "$WORK/port2" 2>> "$WORK/server.err" &
  pid2=$!
  for _ in $(seq 1 100); do port2="$(cat "$WORK/port2" 2>/dev/null)"; [ -n "${port2:-}" ] && break; sleep 0.1; done
  out="$(env PATH="$STUBS:$PATH" FIXTURE_PRS="$WORK/prs.tsv" \
      KIPI_SKEL="$ROOT" KIPI_STATE_DIR="$WORK/state" \
      KIPI_LINEAR_API_URL="http://127.0.0.1:$port2/graphql" \
      KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" KIPI_NOTIFY="/usr/bin/true" \
      bash "${WORKER}" "$@" 2>&1)"
  kill "$pid2" 2>/dev/null; wait "$pid2" 2>/dev/null
  : > "$WORK/port2"
  printf '%s\n' "$out"
}
picks() { printf '%s\n' "$1" | grep -o '\[dry\] would work ASK-[0-9]*' | sed 's/.*would work //' | tr '\n' ' '; }

echo "== expired parks (worker under test: $WORKER)"

OUT="$(run_worker --limit 99)"
GOT="$(picks "$OUT")"

# Self-test of the fixture: if gh was never asked, the open-PR case proves nothing.
if printf '%s\n' "$OUT" | grep -q 'has no GitHub slug'; then
  bad "fixture self-test: the repo reads as GitHub, so open PRs are listed" "$(printf '%s\n' "$OUT" | grep 'GitHub slug' | head -1)"
else
  ok "fixture self-test: the repo reads as GitHub, so open PRs are listed"
fi

# D32 audit: an expired park is worked LAST, never refused. E2 was measured
# closing 0 (starved behind its write cap), so a refused park went nowhere.
case "$GOT" in
  *"ASK-981 ASK-971 ASK-982 ") ok "an expired Backlog park is worked last, after every live ticket, never refused" ;;
  *) bad "an expired Backlog park is worked last, never refused" "picks: [$GOT]" ;;
esac

WANT="ASK-972 ASK-973 ASK-974 ASK-975 ASK-976 ASK-977 ASK-978 ASK-979 ASK-980 ASK-981 ASK-971 ASK-982 "
if [ "$GOT" = "$WANT" ]; then
  ok "everything E2 will not close stays pickable: date ahead, due today, Todo, security, ready, frozen, data-loss, open sana PR, no date, not parked"
else
  bad "everything E2 will not close stays pickable" "got  [$GOT]
     want [$WANT]
     $(printf '%s\n' "$OUT" | grep -E 'ready issue|Traceback|Error' | head -3)"
fi

# --limit 1 is what the dispatcher runs: the one pick is the oldest live ticket.
GOT1="$(picks "$(run_worker --limit 1)")"
[ "$GOT1" = "ASK-972 " ] \
  && ok "the dispatcher's one pick skips the expired park ahead of it" \
  || bad "the dispatcher's one pick skips the expired park" "got [$GOT1], want [ASK-972 ]"

if printf '%s\n' "$OUT" | grep -q 'worker: 2 issue(s) parked past the review date sort last.*ASK-971 ASK-982'; then
  ok "the run says how many expired parks sort last, and which"
else
  bad "the run names the expired parks that sort last" "$(printf '%s\n' "$OUT" | grep -i 'park' | head -2)"
fi

# AN EXPIRED PARK NEVER READS AS URGENT TO THE URGENT SLOT (PR #663 round 1,
# major). It sorts after all live work, so its dry pick must report priority 0,
# or a repo holding only expired parks would win the once-a-day slot.
OUTP="$(KIPI_PICK_PRIORITY=1 run_worker --limit 1 --issue ASK-971)"
printf '%s\n' "$OUTP" | grep -qE '\[dry\] pick priority ASK-971 0$' \
  && ok "an expired park reports priority 0 to the urgent-slot scan" \
  || bad "an expired park reports priority 0" "$(printf '%s\n' "$OUTP" | grep -E 'pick priority|would work' | head -2)"

# ASK-4043 item 2: THE PLAIN SCAN PATH, not --issue. The urgent-slot scan runs
# --limit 1 with KIPI_PICK_PRIORITY=1; on a board whose only pickable ticket is an
# expired Urgent park, that scan must report priority 0, or the repo would win the
# once-a-day slot with a park.
OUTU="$(FIXTURE_BOARD=urgent-park KIPI_PICK_PRIORITY=1 run_worker_board --limit 1)"
printf '%s\n' "$OUTU" | grep -qE '\[dry\] pick priority ASK-990 0$' \
  && ok "the urgent-slot scan (plain --limit 1) reads an expired Urgent park as priority 0" \
  || bad "the urgent-slot scan reads an expired Urgent park as 0" "$(printf '%s\n' "$OUTU" | grep -E 'pick priority|would work|ready issue' | head -3)"
# The copy keeps the repo shape, scripts/ beside terminal-states.json, since the
# worker reads its WIP exit table from $SCRIPT_DIR/../terminal-states.json (PR #673
# round 1, nit).
MUTW="$WORK/mut/scripts"; mkdir -p "$WORK/mut"; cp -R "$REPO_SCRIPTS" "$MUTW"
cp "$REPO_SCRIPTS/../terminal-states.json" "$WORK/mut/terminal-states.json"
sed 's/p = \[0 if i.get("expired_park") else i.get("priority")/p = [i.get("priority")/' "$WORKER" > "$MUTW/linear-worker.sh"
if cmp -s "$WORKER" "$MUTW/linear-worker.sh"; then
  bad "mutant urgent-park: anchor" "the pick-priority line moved"
else
  OUTUM="$(FIXTURE_BOARD=urgent-park KIPI_PICK_PRIORITY=1 WORKER="$MUTW/linear-worker.sh" run_worker_board --limit 1)"
  printf '%s\n' "$OUTUM" | grep -qE '\[dry\] pick priority ASK-990 1$' \
    && ok "mutant killed: without the park mapping the scan reports the park as Urgent (1), so the check can go red" \
    || bad "mutant urgent-park survived" "$(printf '%s\n' "$OUTUM" | grep -E 'pick priority|would work' | head -2)"
fi

# ASK-4043 item 1: THE COUNT IS TAKEN AFTER THE SET-ASIDE FILTER. A park the
# dispatcher set aside for the day (KIPI_PICK_EXCLUDE) will not be worked this run,
# so the line must not name it.
OUT_EX="$(KIPI_PICK_EXCLUDE="ASK-971" run_worker --limit 99)"
if printf '%s\n' "$OUT_EX" | grep -q 'worker: 1 issue(s) parked past the review date sort last.*ASK-982' \
   && ! printf '%s\n' "$OUT_EX" | grep 'parked past the review date' | grep -q 'ASK-971'; then
  ok "a park the dispatcher set aside is not counted among the parks that will be worked"
else
  bad "the expired-park count excludes set-aside issues" "$(printf '%s\n' "$OUT_EX" | grep -i 'parked past' | head -1)"
fi

# THE COUNT IS SAID ONLY WHEN THE OPEN-PR RAIL WAS ASKED (PR #649 round 1,
# minor). Under --issue and on a gh failure the WIP list is empty, so the count
# would name ASK-979, whose open PR keeps E2 off it.
EXPIRED_LINE='parked past the review date sort last'
OUT_FAIL="$(FIXTURE_GH_FAIL=1 run_worker --limit 99)"
if printf '%s\n' "$OUT_FAIL" | grep -q "$EXPIRED_LINE"; then
  bad "a run whose PR list failed does not claim E2 closes anything" "$(printf '%s\n' "$OUT_FAIL" | grep "$EXPIRED_LINE" | head -1)"
else
  ok "a run whose PR list failed does not claim E2 closes anything"
fi
OUT_ISSUE="$(run_worker --limit 1 --issue ASK-971)"
if printf '%s\n' "$OUT_ISSUE" | grep -q "$EXPIRED_LINE"; then
  bad "an --issue run does not claim E2 closes anything" "$(printf '%s\n' "$OUT_ISSUE" | grep "$EXPIRED_LINE" | head -1)"
else
  ok "an --issue run does not claim E2 closes anything"
fi
# Self-test: the failed-list run must have reached gh and failed, or the case
# above passes for the wrong reason.
printf '%s\n' "$OUT_FAIL" | grep -q 'HTTP 502\|could not list\|gh said\|WIP' \
  && ok "fixture self-test: the failed-list run saw gh fail" \
  || bad "fixture self-test: the failed-list run saw gh fail" "$(printf '%s\n' "$OUT_FAIL" | tail -3 | tr '\n' '|')"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" = "0" ]
