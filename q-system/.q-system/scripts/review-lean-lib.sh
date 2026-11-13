#!/usr/bin/env bash
# The claude reviewer's command line, in ONE place (ASK-4743).
#
#   review_claude_cmd <review-root> <model> <fleet-claude> <dest-file> <script-dir>
#
# prints the string pr-review-agent.sh hands to `bash -c`. The prompt is "$1".
#
# WHY IT EXISTS: measured 2026-11-12 on a consulting run, 35 reviews for 22 PRs were
# 44% of the run's tokens, and a review carried a ~118k-token start-up (CLAUDE.md,
# rules, MCP tool schemas, plugin hooks) re-read on every turn. Measured on this
# build (2.1.323), one-word prompt from a repo tree: normal 117.7k, lean 8.0k.
#
# DEFAULT OFF. KIPI_REVIEW_LEAN unset or anything but 1 prints the pre-ASK-4743
# command byte for byte (a test pins it): other sessions call this script from the
# shared checkout and a reviewer whose behaviour moved silently is the one defect
# that cannot be reasoned about.
#
# LEAN = no MCP, no settings from any source, no CLAUDE.md, no auto-memory, no slash
# commands, and only Read/Grep/Glob/Bash. NOT lean_call.py as is: that runs in an
# empty dir with no tools, and a reviewer must read the PR tree.
# HOOKS: `--setting-sources ''` drops EVERY hook (context injectors and guards
# alike); the CLI cannot keep one subset. So the guards are re-attached by name from
# review-lean-settings.json (destructive-op deny, archive deny, .claude write guard),
# read from the control checkout (KIPI_REVIEW_SCRIPTS), never from the PR tree.
# Safe side: a hook the file does not name is OFF in lean mode.
review_claude_cmd() {
  # The two names below are the caller's on purpose: test_model_routing.py's
  # bare_calls matches `$FLEET_CLAUDE -p` by spelling, and as `$fleet -p` this line
  # (the reviewer's only claude call) dropped out of its --model check (ASK-4796).
  local root="$1" CLAUDE_MODEL="$2" FLEET_CLAUDE="$3" dest="$4" sdir="$5"
  local base lean_env="" lean_flags=""
  if [ "${KIPI_REVIEW_LEAN:-0}" = "1" ]; then
    lean_env="KIPI_REVIEW_SCRIPTS='$sdir' CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 "
    lean_flags=" --setting-sources '' --settings '$sdir/../review-lean-settings.json' --strict-mcp-config --mcp-config '{\"mcpServers\":{}}' --tools Read,Grep,Glob,Bash --allowedTools Read,Grep,Glob,Bash --disable-slash-commands"
    echo "pr-review-agent: REVIEWER MODE LEAN (KIPI_REVIEW_LEAN=1): no MCP, no CLAUDE.md or rules, Read/Grep/Glob/Bash only, guard hooks only" >&2
  fi
  base="cd '$root' && KIPI_AGENT=pr-reviewer ${lean_env}$FLEET_CLAUDE -p --model '$CLAUDE_MODEL' \"\$1\" --disallowedTools 'Bash(git clone:*)' 'Bash(gh:*)' 'Bash(curl:*)'${lean_flags} </dev/null > '$dest' 2>&1"
  printf '%s' "$base"
}
