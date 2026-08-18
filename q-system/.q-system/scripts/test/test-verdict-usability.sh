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
#
# THE COPY MUST SIT AT THE CALLER'S REAL DEPTH, IN A REAL REPO. This used to be a
# flat "$WORK/scripts", so the agent's own `SKEL=$SCRIPT_DIR/../../..` resolved to
# the parent of a bare mktemp dir -- not a repository, and two levels shallower
# than any real install. That went unnoticed while nothing asserted the depth. The
# review-root guard added in this same change asserts it, and this fixture was the
# first thing it caught: three cases went <<NORECORD>> because the agent refused
# before it could write a verdict, which reads as "the usable key is a constant"
# rather than "the harness is shaped wrong".
#
# Reproducing the caller's shape is the fix, NOT relaxing the guard. A fixture the
# guard would refuse in production is a fixture testing a layout that cannot ship,
# and the whole defect class here is a test whose environment does not match the
# real one.
REPO_FIXTURE="$WORK/repo"
mkdir -p "$REPO_FIXTURE/q-system/.q-system/scripts"
git -C "$REPO_FIXTURE" init -q 2>/dev/null || { echo "FATAL: could not git-init the fixture repo" >&2; exit 1; }
cp "$AGENT" "$REPO_FIXTURE/q-system/.q-system/scripts/pr-review-agent.sh"
cp "$LIB" "$REPO_FIXTURE/q-system/.q-system/scripts/pr-verdict-lib.sh"
# The reviewer sources this too (ASK-738); without it every case refuses before
# writing a record and the usable key reads as a constant rather than a bug here.
# From the SCRIPTS DIR, not from $(dirname "$LIB"): $LIB is already a copy in a
# temp dir, so deriving the sibling from it looks right and resolves to nothing.
cp "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/repo-slug-lib.sh" "$REPO_FIXTURE/q-system/.q-system/scripts/repo-slug-lib.sh"
AGENT="$REPO_FIXTURE/q-system/.q-system/scripts/pr-review-agent.sh"

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

# CLAUDE PHANTOM: the same class on the OTHER engine (ASK-357). `claude -p` does
# not echo the prompt, so a claude phantom does not look like the codex one -- it
# is the model's own plan, closed with the template block it was asked to end on
# and a request for permission to begin. Kept as its own fixture rather than
# reusing phantom.md: that payload is stamped `OpenAI Codex v0.146.0`, and a
# claude-engine case driven by a codex-stamped stream is a fixture that tests a
# shape its producer cannot emit.
#
# The EMPTY block is the load-bearing part. An unclosed block would be caught by
# has_complete_findings_block; this one is complete and empty, which derives
# APPROVE -- so only the decline-to-start half of review_is_usable can refuse it.
cat > "$WORK/phantom-claude.md" <<'EOS'
I'll review PR #4803. Here is my plan:

1. Read the diff and the two scripts it touches.
2. Reproduce each suspected defect in $TMPDIR.
3. Report findings with severities and paste the real output.

FINDINGS:
END FINDINGS

Reply `OK` and I'll execute exactly that plan.
EOS

run_agent() {   # run_agent <fixture> <pr-number> [extra agent args...]
  local fixture="$1" pr="$2" home="$WORK/home-$2"
  shift 2
  mkdir -p "$home"
  env HOME="$home" \
      PATH="$BIN:$PATH" \
      REVIEW_FIXTURE="$fixture" \
      KIPI_NOTIFY="/usr/bin/true" \
      bash "$AGENT" "$pr" --issue "ASK-TEST" "$@" >"$WORK/out-$pr.log" 2>&1
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

# --- case 3: the phantom and the objection are INDISTINGUISHABLE at the gate --
# THE REASON THE KEY HAS TO EXIST. This used to be pinned as "both records state
# REQUEST CHANGES", because the phantom's `stated` was lifted straight out of the
# echoed grading rule and was byte-identical to what a real objection writes.
#
# ASK-356 fixed that read: the grading rule is the prompt talking, not the
# reviewer, so the phantom now states nothing. The old assertion's PREMISE was
# itself the defect, and an assertion built on a defect dies when the defect is
# fixed. Rewriting it to the new stated values would just re-date it to today.
#
# WHAT DID NOT CHANGE is the only thing a downstream selector can actually see.
# Neither record carries an approving verdict, so post_reviewer_status maps BOTH
# to state=failure on the same context -- the phantom because it is unstated, the
# objection because it objected. A selector reading the verdict, or reading the
# commit status derived from it, still cannot tell "nobody reviewed this" from
# "someone objected": it sends the phantom to REWORK and hands the agent a review
# with nothing in it to fix. `usable` remains the ONLY key that separates them,
# which is why the producer has to persist it instead of leaving consumers to
# recompute it from a review file that rotates away.
#
# Asserted as three separate facts, not one conjunction, so a partial regression
# names itself instead of collapsing into one opaque FAIL.
approving() {   # approving <json-quoted verdict> -- true when it posts success
  case "$1" in '"APPROVE"'|'"APPROVE WITH NITS"') return 0 ;; *) return 1 ;; esac
}
V1="$(field "$REC1" verdict)"; V2="$(field "$REC2" verdict)"
approving "$V1" \
  && bad "the phantom recorded an APPROVING verdict $V1 -- a review that never ran would post state=success" \
  || ok "the phantom's verdict ($V1) does not release the PR"
approving "$V2" \
  && bad "the objection recorded an APPROVING verdict $V2 -- the reviewer objected" \
  || ok "the objection's verdict ($V2) does not release the PR either"
[ "$U1" != "$U2" ] \
  && ok "the two are separated ONLY by usable ($U1 vs $U2), never by the verdict" \
  || bad "usable1=$U1 usable2=$U2 -- the key does not discriminate, so nothing does"

# --- case 4: the claude-PRIMARY path gates on usability too (ASK-357) --------
# THE RECORD WAS ALREADY HONEST; THE GATE WAS NOT. `usable` is asked once, on the
# review file, for all three dispatch paths, so cases 1-3 above pass on the
# pre-fix agent too. What the pre-fix agent skipped is the CONSUMER of that
# answer: `REVIEW_UNUSABLE` was only ever set on the codex path and the Opus
# fallback, so on `--engine claude` a phantom fell through to the derivation, an
# empty FINDINGS block derived APPROVE, and the run posted state=success.
#
# PRIMARY, not advisory. With KIPI_REVIEW_PRIMARY_ENGINE=claude the run owns
# `kipi/reviewer-approved` -- the REQUIRED context -- which is what makes this a
# gate defect rather than a cosmetic one. Under the default (codex primary) the
# same phantom only fills the advisory `kipi/claude-approved` slot.
#
# Asserted as two facts, not one: `usable=false` pins that the record still tells
# the truth, and the non-approving verdict pins that the gate now listens to it.
# Only the second goes RED on the pre-fix agent, and collapsing them into one
# assertion would hide which half regressed.
REC4="$(export KIPI_REVIEW_PRIMARY_ENGINE=claude; run_agent "$WORK/phantom-claude.md" 4803 --engine claude)"
U4="$(field "$REC4" usable)"
V4="$(field "$REC4" verdict)"
if [ "$U4" = "false" ]; then
  ok "claude-primary: a phantom review records usable=false"
else
  bad "claude-primary: a phantom recorded usable=$U4 (want false)"
fi
approving "$V4" \
  && bad "claude-primary: the phantom recorded an APPROVING verdict $V4 -- a review that never ran would set the REQUIRED kipi/reviewer-approved context to success" \
  || ok "claude-primary: the phantom's verdict ($V4) does not release the PR"

echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
