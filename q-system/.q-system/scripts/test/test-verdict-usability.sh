#!/usr/bin/env bash
# Pairs with pr-review-agent.sh's verdict-record writer (sp-2a832233, ASK-352).
#
# THE DEFECT. The commit status is `failure` in two semantically opposite cases,
# and the verdict record could not tell them apart:
#
#   PR #82 -- a real review, one real minor, verdict REQUEST CHANGES.
#             Someone objected. The right action is REWORK.
#   PR #80 -- codex echoed the prompt's own FINDINGS template and never
#             reviewed anything, and the record ALSO says REQUEST CHANGES.
#             Nobody objected. The right action is RE-REVIEW.
#
# `verdict` alone does not discriminate: measured 2026-08-03 over all 79 verdict
# records, 13 were unusable and they carry every verdict value in the range --
# APPROVE (11 of them, all merged), REQUEST CHANGES (#80, #83), and empty (#89).
# The only reliable signal is review_is_usable() applied to the review FILE, and
# the record stored only a PATH to a file that rotates away.
#
# So the producer persists the answer. This test is the reproducer: it drives the
# real script with a stubbed engine and asserts the record carries `usable`.
#
# REF HATCH. Set REPRO_REF to a pre-fix commit and the script under test is
# loaded from there instead of the worktree, so this case can be watched FAILING
# against the code it was written for. A case added after its fix has never been
# proven to catch anything.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SCRIPT_REL="q-system/.q-system/scripts/pr-review-agent.sh"
LIB_REL="q-system/.q-system/scripts/pr-verdict-lib.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

# --- the script under test, from the worktree or from a pre-fix ref ----------
AGENT="$WORK/pr-review-agent.sh"
LIB="$WORK/pr-verdict-lib.sh"
if [ -n "${REPRO_REF:-}" ]; then
  git -C "$REPO_ROOT" show "$REPRO_REF:$SCRIPT_REL" > "$AGENT" 2>/dev/null \
    || { echo "FATAL: $SCRIPT_REL not at $REPRO_REF" >&2; exit 1; }
  git -C "$REPO_ROOT" show "$REPRO_REF:$LIB_REL" > "$LIB" 2>/dev/null \
    || { echo "FATAL: $LIB_REL not at $REPRO_REF" >&2; exit 1; }
  echo "== verdict usability (AGENT FROM REF $REPRO_REF) =="
else
  cp "$REPO_ROOT/$SCRIPT_REL" "$AGENT"
  cp "$REPO_ROOT/$LIB_REL" "$LIB"
  echo "== verdict usability =="
fi
chmod +x "$AGENT"
# The agent sources the lib from its own directory, so both copies must sit
# together. Verify-against-a-copy: the live checkout is never the thing driven.
mkdir -p "$WORK/scripts"
cp "$AGENT" "$WORK/scripts/pr-review-agent.sh"
cp "$LIB" "$WORK/scripts/pr-verdict-lib.sh"
AGENT="$WORK/scripts/pr-review-agent.sh"

# --- stubs: the engine and gh are the seams, and both are stubbed ------------
# NOT a sandboxed HOME alone. A quiet run because a dependency silently no-ops
# is a latent live-path leak, so every outbound call this script can make is
# given an explicit local stand-in and the review CONTENT is what varies.
BIN="$WORK/bin"; mkdir -p "$BIN"
cat > "$BIN/gh" <<'EOS'
#!/usr/bin/env bash
# Only ever asked for the head sha here; --post is never passed by this test, so
# no status is ever posted and nothing reaches GitHub.
echo "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
EOS
cat > "$BIN/codex" <<'EOS'
#!/usr/bin/env bash
cat "$REVIEW_FIXTURE"
EOS
cat > "$BIN/claude" <<'EOS'
#!/usr/bin/env bash
cat "$REVIEW_FIXTURE"
EOS
chmod +x "$BIN"/*

# --- the two fixtures, both taken from real captured payloads ----------------
# PHANTOM: the shape of the real captured payload for PR #80 (read 2026-08-03).
# `codex exec` echoes the whole prompt to stdout, so when the model answers with
# a PLAN instead of a review the stream contains the prompt's GRADING RULE and
# the prompt's own FINDINGS template, and nothing else.
#
# THE LOAD-BEARING DETAIL: `stated` for the real #80 record was REQUEST CHANGES,
# and it came from the grading-rule line below -- the PROMPT telling the model
# when to use that verdict. No reviewer ever said it. That is why `stated` is not
# a trustworthy "someone objected" signal and why usability has to be its own key.
# Paths are generic here on purpose; the captured payload carries the founder's
# home directory and loaded skill bodies, neither of which belongs in a fixture
# in a public repo (ASK-345).
cat > "$WORK/phantom.md" <<'EOS'
OpenAI Codex v0.146.0
--------
workdir: /tmp/review-trees/pr-80
--------
user
You are a SENIOR STAFF ENGINEER. Review pull request #80.

- **VERDICT:** decided by THIS RULE, not by feel:
    - any blocker or major finding      => REQUEST CHANGES (BLOCK only if merging
      would lose data)
    - only minor/nit findings           => APPROVE WITH NITS
    - no finding survived reproduction  => APPROVE

Last, a machine-readable findings block:

FINDINGS:
severity|one-sentence claim|file:line
END FINDINGS

codex
Here is my review plan.

Reply `OK` and I'll execute.

Waiting for `OK` before executing the review plan.
EOS

# REAL: a review that ran and objected, the #82 shape.
cat > "$WORK/real.md" <<'EOS'
## VERDICT
**REQUEST CHANGES**

The exclusion filter is enforced at one walker but not the other.

FINDINGS:
major|the second walker skips the exclusion set entirely|walker.py:88
minor|the docstring still names the old flag|walker.py:12
END FINDINGS
EOS

run_agent() {   # run_agent <fixture> <pr-number>
  local fixture="$1" pr="$2" home="$WORK/home-$2"
  mkdir -p "$home"
  env HOME="$home" \
      PATH="$BIN:$PATH" \
      REVIEW_FIXTURE="$fixture" \
      KIPI_NOTIFY="/usr/bin/true" \
      bash "$AGENT" "$pr" --issue "ASK-TEST" >"$WORK/out-$pr.log" 2>&1
  echo "$home/.config/kipi/pr-reviews/pr-$pr.verdict.json"
}

field() {   # field <record> <key>
  python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(json.dumps(d.get(sys.argv[2],'<<MISSING>>')))" \
    "$1" "$2" 2>/dev/null || echo '<<NORECORD>>'
}

# --- case 1: a phantom review is recorded as NOT usable ----------------------
# This is the case that fails against the pre-fix agent, and it is the whole
# point of the change. The record for PR #80 says REQUEST CHANGES on a review
# that never ran; without this key no selector can tell it from PR #82.
REC1="$(run_agent "$WORK/phantom.md" 4801)"
U1="$(field "$REC1" usable)"
if [ "$U1" = "false" ]; then
  ok "a phantom review (prompt template echo) records usable=false"
else
  bad "a phantom review recorded usable=$U1 (want false) -- the record cannot tell #80 from #82"
fi

# --- case 2: a real review is recorded as usable -----------------------------
# The negative half. A key that is always false is not a discriminator, it is a
# constant, and a selector built on a constant re-reviews every PR forever.
REC2="$(run_agent "$WORK/real.md" 4802)"
U2="$(field "$REC2" usable)"
if [ "$U2" = "true" ]; then
  ok "a real review with findings records usable=true"
else
  bad "a real review recorded usable=$U2 (want true) -- the key is a constant, not a discriminator"
fi

# --- case 3: `stated` claims an objection on a review that never ran ---------
# THE REASON THE KEY HAS TO EXIST, pinned as an assertion. The phantom's `stated`
# is REQUEST CHANGES -- lifted straight out of the echoed grading rule -- which is
# byte-identical to what a real objection writes. A selector reading `stated`, or
# reading the `failure` commit status it produces, sends this PR to REWORK and the
# agent is handed a review with nothing in it to fix. Only `usable` separates them.
S1="$(field "$REC1" stated)"; S2="$(field "$REC2" stated)"
if [ "$S1" = "$S2" ] && [ "$U1" != "$U2" ]; then
  ok "both records state $S1; only usable tells the phantom from the objection"
else
  bad "stated1=$S1 stated2=$S2 usable1=$U1 usable2=$U2 -- wanted equal stated and differing usable"
fi

echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
