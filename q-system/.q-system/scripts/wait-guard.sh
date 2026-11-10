#!/usr/bin/env bash
# wait-guard.sh <blocker> [waiter-ticket]: call this BEFORE you start waiting (ASK-4306).
#
# Rule-ID: RULE-2026-11-09-B
# A watcher script, a cron backstop or a lane that is about to sleep on a ticket or a
# PR runs this first. Exit 0 means a consumer will act on the blocker inside 24 hours
# and prints it. Any other exit means DO NOT WAIT: 1 = nothing picks it up, 2 = the
# check could not look (fail closed, a wait nobody verified is not a wait), 64 = bad
# argument. The reason is printed on stderr.
#
# WHY A WRAPPER: wait-has-consumer.py was only reachable through lane-mark.py hold, and
# nothing called that (PR #712 review, rounds 1 to 3). The watchers that actually wait
# are shell, so the first caller is shell: `wait-guard.sh ASK-4195 || exit 1`.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "usage: wait-guard.sh <ASK-id | owner/repo#N> [waiter ASK-id]" >&2
  exit 64
fi
out="$(python3 "$HERE/wait-has-consumer.py" "$1" ${2:+--waiter "$2"} 2>&1)"
rc=$?
if [ "$rc" -eq 0 ]; then
  echo "wait-guard: OK to wait on $1: $out"
  exit 0
fi
echo "wait-guard: DO NOT WAIT on $1 (exit $rc): $out" >&2
exit "$rc"
