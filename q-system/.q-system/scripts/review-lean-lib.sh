#!/usr/bin/env bash
# The lean half of the claude reviewer's command line, in ONE place (ASK-4743).
#
#   review_lean_args <script-dir>
#
# sets two globals that pr-review-agent.sh splices into its claude `bash -c` line:
#   REVIEW_LEAN_ENV    env assignments, ending in a space, put BEFORE KIPI_AGENT=
#   REVIEW_LEAN_FLAGS  CLI flags, starting with a space, put BEFORE the redirect
# Both are empty when lean is off, so the line is the pre-ASK-4743 one byte for byte.
#
# WHY THE COMMAND LINE STAYS IN pr-review-agent.sh (ASK-4796): PR #786 first moved
# the whole line into this lib as a printed string. Every consumer that finds the
# reviewer's model call by reading pr-review-agent.sh then lost it: the metering
# scanner (voiceloop call_sites.py) skips an assignment's value, so the reviewer left
# test_model_call_sites.py and test-subscription-only.sh while both stayed quiet, and
# three more tests went red (round 4 review, run 43348697308). Fixing consumers one by
# one is the defect class; keeping the line where they all read is the fix.
#
# WHY IT EXISTS: measured 2026-11-12 on a consulting run, 35 reviews for 22 PRs were
# 44% of the run's tokens, and a review carried a ~118k-token start-up (CLAUDE.md,
# rules, MCP tool schemas, plugin hooks) re-read on every turn. Measured on this
# build (2.1.323), one-word prompt from a repo tree: normal 117.7k, lean 8.0k.
#
# DEFAULT ON since the planted-defect control (2026-11-12, PRs #790/#791 at one
# head): lean found all 3 planted defects the normal reviewer found, including
# the rule-file one, at $1.48 against $6.66. KIPI_REVIEW_LEAN=0, exactly, leaves
# both globals empty, so the line is the pre-ASK-4743 one byte for byte (a test pins
# it). Only "0" opts out: the old switch read "anything but 1" as off, and a typo'd
# opt-out that silently keeps lean is safer than a typo'd value that silently
# restores a 124k start-up.
#
# LEAN = no MCP, no settings from any source, no CLAUDE.md, no auto-memory, no slash
# commands, and only Read/Grep/Glob/Bash. NOT lean_call.py as is: that runs in an
# empty dir with no tools, and a reviewer must read the PR tree.
# HOOKS: `--setting-sources ''` drops EVERY hook (context injectors and guards
# alike); the CLI cannot keep one subset. So the guards are re-attached by name from
# review-lean-settings.json (destructive-op deny, archive deny, .claude write guard),
# read from the control checkout (KIPI_REVIEW_SCRIPTS), never from the PR tree.
# Safe side: a hook the file does not name is OFF in lean mode. That includes the
# rule gate's Stop scan, on purpose (ASK-4769 option b): a read-only reviewer writes no
# rule file, and the scan's reach into every tree under ~/projects let one unrelated
# tree's rule debt turn a review verdict UNSTATED.
review_lean_args() {
  local sdir="$1"
  REVIEW_LEAN_ENV=""
  REVIEW_LEAN_FLAGS=""
  if [ "${KIPI_REVIEW_LEAN:-1}" != "0" ]; then
    REVIEW_LEAN_ENV="KIPI_REVIEW_SCRIPTS='$sdir' CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 "
    REVIEW_LEAN_FLAGS=" --setting-sources '' --settings '$sdir/../review-lean-settings.json' --strict-mcp-config --mcp-config '{\"mcpServers\":{}}' --tools Read,Grep,Glob,Bash --allowedTools Read,Grep,Glob,Bash --disable-slash-commands"
    echo "pr-review-agent: REVIEWER MODE LEAN (default; KIPI_REVIEW_LEAN=0 turns it off): no MCP, no CLAUDE.md or rules, Read/Grep/Glob/Bash only, guard hooks and the project deny list only" >&2
  fi
}
