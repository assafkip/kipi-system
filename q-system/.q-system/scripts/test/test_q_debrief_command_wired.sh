#!/usr/bin/env bash
# ASK-1925 (spillover sp-4daf4890): /q-debrief is the only documented writer of
# memory/graph.jsonl (debrief-template.md steps 6 and 10) and had no command file
# anywhere in the skeleton. Its file was deleted 2026-03-23 (commit 69bf969d) from
# .claude/commands/, and kipi-update.sh does not sync .claude/commands -- it ships
# only .claude/agents, .claude/output-styles, .claude/rules and plugins/. So the
# deletion could never propagate: instances kept stale pre-2026-03-23 copies, new
# instances got nothing, and CLAUDE.md went on advertising the command.
#
# CLAUDE.md is the founder-facing command menu. A name on that menu with no file
# behind it in a path the updater ships is a promise the fleet cannot keep, and it
# fails silently -- a missing slash command is simply absent from the menu, it does
# not error.
#
# What this checks:
#   (a) every command named in CLAUDE.md's Commands list has a file at
#       plugins/<plugin>/commands/<name>.md -- the ONLY fleet-wide path a command
#       ships and loads through. Depth is asserted, not merely "somewhere under
#       plugins/": plugins/kipi-core/skills/research-mode/commands/q-research.md
#       exists on disk and does NOT load, because Claude Code discovers a plugin's
#       commands/ directory at the plugin root only. A find-anywhere check would
#       grade that dead file as wired.
#   (b) the parse floor: if the CLAUDE.md list format changes and zero commands are
#       extracted, that is a failure. A regex that stops matching otherwise turns
#       every check built on it into a silent no-op that reads as green.
#   (c) the grandfather list cannot rot: each name exempted below is asserted to be
#       STILL missing. The day one of them ships a file, this test goes red and the
#       exemption is deleted, so the list can never bless a command that now exists.
#
# GRANDFATHERING, and why it is not a loophole: measured 2026-09-20, 10 of the 13
# names on the CLAUDE.md menu have no command file. A gate red on its own population
# on day one gets switched off, and a gate that is off protects nothing (same call
# and same reason as quick-plan.md's pre-2026-08-21 plans). Each exemption below is
# named individually with what it actually is today. They are captured as spillover
# under this issue, not forgiven. q-debrief is deliberately NOT exempt: it is what
# this issue fixes, and it is what makes this check go red before the fix.
#
# Negative self-test at the end: a synthetic command name is injected into a copy of
# CLAUDE.md and the same function is re-run, proving the check can go red. A check
# that cannot fail is decoration.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
CLAUDE_MD="$ROOT/CLAUDE.md"

fail() { echo "FAIL: $1" >&2; exit 1; }

[ -f "$CLAUDE_MD" ] || fail "CLAUDE.md missing at $CLAUDE_MD"

# Commands known to have no file in a synced path as of 2026-09-20. Each is a real
# gap, captured as spillover under ASK-1925; none is a decision that it is fine.
#   q-morning    -- the launchd job com.kipi.morning-brief is the live path; the
#                   slash command that "runs it early" has no file.
#   q-calibrate  -- no file, no skill.
#   q-create     -- no file, no skill.
#   q-plan       -- no file, no skill.
#   q-engage     -- no file, no skill.
#   q-draft      -- no file, no skill.
#   q-wrap       -- no file, no skill.
#   q-handoff    -- no file, no skill.
#   q-research   -- file exists at plugins/kipi-core/skills/research-mode/commands/
#                   q-research.md, which is NOT a load path; the research-mode SKILL
#                   is what actually loads.
#   improve      -- listed with a leading slash but is the kipi-core `improve` skill,
#                   not a command. Either the listing or the shape is wrong.
GRANDFATHERED="q-morning q-calibrate q-create q-plan q-engage q-draft q-wrap q-handoff q-research improve"

# Derive the menu from CLAUDE.md rather than restating it here: the list is owned by
# CLAUDE.md, and a copy would agree on the day it was written and silently stop
# describing the menu the first time a command is added. Glob entries (/q-market-*)
# name a family, not a file, and are skipped.
extract_commands() {
  grep -oE '^- `/[a-z0-9-]+`' "$1" | sed -e 's/^- `\///' -e 's/`$//'
}

# A command is wired only at plugins/<plugin>/commands/<name>.md. Exactly that depth.
command_file_for() {
  local name="$1" f
  for f in "$ROOT"/plugins/*/commands/"$name".md; do
    [ -f "$f" ] && { printf '%s\n' "$f"; return 0; }
  done
  return 1
}

# Factored so the negative self-test runs the SAME function against a mutated copy.
# Prints every unwired, non-grandfathered command; returns 1 if there was any.
check_menu() {
  local md="$1" name missing=0
  local names
  names="$(extract_commands "$md")"

  [ -n "$names" ] || { echo "  parse floor: zero commands extracted from $md"; return 1; }

  while IFS= read -r name; do
    [ -n "$name" ] || continue
    case " $GRANDFATHERED " in *" $name "*) continue ;; esac
    if ! command_file_for "$name" >/dev/null; then
      echo "  /$name is on the CLAUDE.md menu with no file at plugins/*/commands/$name.md"
      missing=1
    fi
  done <<< "$names"
  return "$missing"
}

# --- (a)+(b) the real menu ---------------------------------------------------
if ! out="$(check_menu "$CLAUDE_MD")"; then
  echo "$out" >&2
  fail "CLAUDE.md names commands that ship no file in a path kipi-update.sh syncs"
fi

# --- (c) the grandfather list cannot rot -------------------------------------
for name in $GRANDFATHERED; do
  if f="$(command_file_for "$name")"; then
    fail "/$name is grandfathered but now HAS a file at ${f#"$ROOT"/} -- delete its exemption"
  fi
done

# --- negative self-test: prove the check can go red --------------------------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cp "$CLAUDE_MD" "$TMP/CLAUDE.md"
printf '%s\n' '- `/q-does-not-exist` - synthetic entry for the negative self-test' >> "$TMP/CLAUDE.md"
if check_menu "$TMP/CLAUDE.md" >/dev/null; then
  fail "negative self-test: an invented command name passed the check, so the check is decoration"
fi

# and the parse floor itself must be able to fire
: > "$TMP/empty.md"
if check_menu "$TMP/empty.md" >/dev/null; then
  fail "negative self-test: a CLAUDE.md with zero commands passed, so the parse floor is dead"
fi

echo "PASS: every command on the CLAUDE.md menu ships a file in a synced path"
