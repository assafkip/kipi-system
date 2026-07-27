#!/usr/bin/env bash
# Reproducer + acceptance criterion for "a git fetch failure goes dark"
# (ASK-208, PR #22 review round 3, finding 1 -- major).
#
# THE DEFECT: the fetch guard added for sp-28ced3d6 stops the whole run on a
# fetch failure with `say` + `exit 0`. $NOTIFY was in scope and never called, and
# MAX_ATTEMPTS was never bumped, so nothing paged and nothing ever became stuck.
# An expired git credential or an unreachable origin at 3am produced a worker
# that was byte-for-byte indistinguishable from a healthy no-work run: rc=0, no
# Slack, one line in a log nobody reads. `converge.sh` caught it downstream (no
# PR -> exit 7 + Slack) but the batch path (`kipi work --apply --limit N`, which
# is what launchd runs) did not, and this script syncs to every instance.
#
# The header of linear-worker.sh cites self-healing-retry.md rule 5, which says
# an environmental failure is surfaced IMMEDIATELY. A log line is not surfacing.
#
# WHY THIS DRIVES THE REAL SCRIPTS: the claim is about an exit code and a side
# effect (the page), so both are read back for real -- the worker runs against a
# genuinely unreachable origin, and $NOTIFY is redirected to a recorder rather
# than stubbed out, so "did it page?" is answered by a file with the message in
# it and not by a grep of the source.
#
# The healthy contrast is asserted in the same run (case 4). A non-zero exit is
# only worth anything if the healthy path still exits 0 -- otherwise the fix
# trades a silent failure for a permanent false alarm, which is the same defect
# wearing the other hat.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SCRIPTS="$ROOT/q-system/.q-system/scripts"
WORKER="$SCRIPTS/linear-worker.sh"
CONVERGE="$SCRIPTS/converge.sh"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$WORKER" ]   || fail "linear-worker.sh does not exist at $WORKER"
[ -f "$CONVERGE" ] || fail "converge.sh does not exist at $CONVERGE"
REAL_PY="$(command -v python3)" || fail "python3 not on PATH"
REAL_GIT="$(command -v git)"    || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID 2>/dev/null || true
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

# --- a skeleton whose origin cannot be reached ------------------------------
git init -q "$WORK/skel"
G -C "$WORK/skel" commit -q --allow-empty -m c1
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "$WORK/nowhere.git"   # never created
git -C "$WORK/skel" fetch --quiet origin 2>/dev/null \
  && fail "fixture: the unreachable origin fetched anyway"

STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home"
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"}],"total_open":1}\n'
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/gh"
# Reaching the agent at all would mean the run did work on a stale base.
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
echo "dispatched" >> "$WORK/worked.txt"
exit 0
EOF
# THE PROBE for "did anyone get paged". Not a no-op stub: the message has to be
# readable, because a page that says nothing is the failure in a different coat.
cat > "$WORK/notify-recorder.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$WORK/pages.txt"
EOF
chmod +x "$STUB/python3" "$STUB/gh" "$STUB/claude" "$WORK/notify-recorder.sh"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub; a real fetch failure is the subject"

: > "$WORK/pages.txt"; : > "$WORK/worked.txt"

( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state" \
     KIPI_NOTIFY="$WORK/notify-recorder.sh" \
     bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >"$WORK/run.out" 2>&1
RC=$?

# --- 1. the run is distinguishable from a healthy no-work run ---------------
if [ "$RC" = "0" ]; then
  fail "SILENT SUCCESS: the worker exited 0 after a fetch failure that stopped
      the entire run. A caller -- launchd, a wrapper, converge -- cannot tell
      this apart from a healthy run with nothing ready. It said:
      $(grep -i infra "$WORK/run.out" | head -1)"
fi
ok "a fetch failure exits non-zero (rc=$RC), so a caller can tell"

# --- 2. somebody was actually paged -----------------------------------------
if [ ! -s "$WORK/pages.txt" ]; then
  fail "NOBODY WAS PAGED: the fetch failed, the run did no work, and \$NOTIFY was
      never called. self-healing-retry.md rule 5 says an environmental failure is
      surfaced immediately; the only trace was a line in the log."
fi
ok "the fetch failure pages the founder through \$NOTIFY"

grep -qi "fetch" "$WORK/pages.txt" \
  || fail "the page does not name the cause. It said: $(head -1 "$WORK/pages.txt")"
ok "the page names the cause (git fetch), not just 'something failed'"

# --- 3. it still stopped before doing anything on a stale base --------------
[ ! -s "$WORK/worked.txt" ] \
  || fail "the agent was dispatched anyway; the whole point of stopping is that a
      stale base produces plausible work aimed at the wrong target"
[ ! -d "$WORK/state/worktrees/ask-aaa" ] \
  || fail "a worktree was cut despite the fetch failure"
ok "no worktree was cut and no agent was dispatched"

# --- 4. the HEALTHY path is unchanged: rc 0, and nobody is paged ------------
# Without this the fix could 'pass' by always failing and always paging, which
# trains the reader to ignore the channel -- the cry-wolf failure this fleet
# keeps killing.
git init -q --bare "$WORK/origin"
git -C "$WORK/origin" symbolic-ref HEAD refs/heads/main
git -C "$WORK/skel" remote set-url origin "$WORK/origin"
git -C "$WORK/skel" push -q -u origin main
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null; printf '{"ready":[],"total_open":0}\n'; exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
chmod +x "$STUB/python3"
: > "$WORK/pages.txt"

( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state-ok" \
     KIPI_NOTIFY="$WORK/notify-recorder.sh" \
     bash "$WORKER" --apply --limit 1 ) >"$WORK/run-ok.out" 2>&1
RC_OK=$?

[ "$RC_OK" = "0" ] \
  || fail "a healthy run with nothing ready must still exit 0, got rc=$RC_OK: $(tail -3 "$WORK/run-ok.out")"
ok "a healthy run with nothing ready still exits 0"

[ ! -s "$WORK/pages.txt" ] \
  || fail "a healthy no-work run paged the founder: $(head -1 "$WORK/pages.txt")"
ok "a healthy no-work run pages nobody"

# --- 5. converge names the real cause and does not double-page --------------
# The layer above. converge already stopped on 'no PR -> exit 7 + Slack', so
# without a mapping the founder gets two pings for one cause and the second one
# blames Sana for not opening a PR when the run never started. One event, one
# page, and the message says what actually happened.
FAKE="$WORK/fake-worker.sh"
cat > "$FAKE" <<'EOF'
#!/usr/bin/env bash
exit 9
EOF
chmod +x "$FAKE"
: > "$WORK/pages.txt"

( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_STATE_DIR="$WORK/state-conv" \
     KIPI_NOTIFY="$WORK/notify-recorder.sh" \
     KIPI_CONVERGE_WORKER="bash $FAKE" \
     bash "$CONVERGE" --issue ASK-AAA --max-rounds 4 ) >"$WORK/conv.out" 2>&1
RC_CONV=$?

[ "$RC_CONV" = "7" ] \
  || fail "converge must stop on the worker's infra exit with exit 7 (error threshold), got rc=$RC_CONV: $(tail -3 "$WORK/conv.out")"
ok "converge stops with exit 7 when the worker reports an infra failure"

grep -qiE "infra|environment" "$WORK/conv.out" \
  || fail "converge blamed the wrong thing. It said: $(grep -i stop "$WORK/conv.out" | head -1)"
ok "converge names the infra failure instead of blaming Sana for not opening a PR"

PAGES="$(wc -l < "$WORK/pages.txt" | tr -d ' ')"
[ "${PAGES:-0}" = "0" ] \
  || fail "converge paged again for a failure the worker already paged for
      ($PAGES page(s)): $(head -2 "$WORK/pages.txt")"
ok "converge does not double-page: the worker owns the page for its own infra failure"

bash -n "$WORKER"   || fail "linear-worker.sh does not parse"
bash -n "$CONVERGE" || fail "converge.sh does not parse"
ok "both scripts parse (bash -n)"

echo "PASS: worker infra exit ($PASS checks)"
