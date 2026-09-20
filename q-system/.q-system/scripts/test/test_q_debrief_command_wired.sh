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
README_MD="$ROOT/README.md"

fail() { echo "FAIL: $1" >&2; exit 1; }

[ -f "$CLAUDE_MD" ] || fail "CLAUDE.md missing at $CLAUDE_MD"
[ -f "$README_MD" ] || fail "README.md missing at $README_MD"

# ASK-1927 emptied this list. Every name on either menu now ships a file at
# plugins/<plugin>/commands/<name>.md, so there is nothing left to exempt. The
# array stays (rather than being deleted) because the rot check below reads it:
# an empty list makes that loop a no-op, which is the correct shape for "no
# exemptions", and re-adding one re-arms the check without touching this test.
#
# `improve` was on this list and was never load-bearing: the extractor matches a
# name at the START of a list item, and /improve sits mid-line inside the
# /q-draft row of CLAUDE.md, so it was never extracted and its exemption never
# fired. It is the kipi-core `improve` SKILL, not a command; CLAUDE.md no longer
# writes it with a leading slash.
GRANDFATHERED=""

# Derive the menu from CLAUDE.md rather than restating it here: the list is owned by
# CLAUDE.md, and a copy would agree on the day it was written and silently stop
# describing the menu the first time a command is added. Glob entries (/q-market-*)
# name a family, not a file, and are skipped.
# Two menu SHAPES, because the two files write their menus differently and a
# parser that knows only one grades the other as empty -- which reads as green.
#   CLAUDE.md : - `/name` - description
#   README.md : | `/name` | description |   (ASK-1927; the public menu an outside
#                                            reader trusts, and it listed six
#                                            names with no file behind them)
# Glob entries (/q-market-*) name a family, not a file, and are skipped by the
# character class. A namespaced name (/kipi-core:say) is skipped for the same
# reason: the colon is outside the class, and those rows already name the plugin
# that owns the file.
extract_commands() {
  {
    grep -oE '^- `/[a-z0-9-]+`' "$1" || true
    grep -oE '^\| `/[a-z0-9-]+`' "$1" || true
  } | sed -e 's/^- `\///' -e 's/^| `\///' -e 's/`$//' | sort -u
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
for md in "$CLAUDE_MD" "$README_MD"; do
  if ! out="$(check_menu "$md")"; then
    echo "$out" >&2
    fail "${md#"$ROOT"/} names commands that ship no file in a path kipi-update.sh syncs"
  fi
done

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

# The README shape gets its own injection. Sharing one fixture would prove only
# that the list shape can go red, and the table shape -- the half added by
# ASK-1927 -- would be untested while reading as covered.
cp "$README_MD" "$TMP/README.md"
printf '%s\n' '| `/q-also-does-not-exist` | synthetic entry for the negative self-test |' >> "$TMP/README.md"
if check_menu "$TMP/README.md" >/dev/null; then
  fail "negative self-test: an invented command name passed in the README table shape"
fi

# and the parse floor itself must be able to fire
: > "$TMP/empty.md"
if check_menu "$TMP/empty.md" >/dev/null; then
  fail "negative self-test: a CLAUDE.md with zero commands passed, so the parse floor is dead"
fi

echo "PASS: every command on the CLAUDE.md and README.md menus ships a file in a synced path"
