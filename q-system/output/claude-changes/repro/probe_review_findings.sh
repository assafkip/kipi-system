#!/usr/bin/env bash
# Reproducer for the four majors + one minor Codex raised on PR #85 (ASK-291).
#
# Each phase builds a throwaway instance tree and drives the REAL scripts. No
# mocks: a fixture I invent tests my assumption, so every phase runs the exact
# command the shipped caller runs (apply_claude_changes.register_with_tripwire's
# argv, and kipi-update.sh's tripwire line verbatim).
#
# Cleanup is python shutil.rmtree, not `rm -r`: the destructive-op hook blocks
# `rm -r` and blocked the reviewer's own repro. A harness that cannot run under
# the repo's own gates is not a harness.
set -u

REPO="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)}"
TRIPWIRE="$REPO/q-system/.q-system/scripts/claude-integrity-tripwire.py"
APPLIER="$REPO/q-system/.q-system/scripts/apply_claude_changes.py"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/pr85-findings.XXXXXX")"
FAILED=0

cleanup() { python3 -c 'import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)' "$WORK"; }
trap cleanup EXIT

say() { printf '\n=== %s\n' "$*"; }
ok()  { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILED=1; }

# A minimal instance: a settings.json plus two other watched files, committed so
# git provenance exists (attributable() consults HEAD).
make_instance() {
  local root="$1"
  mkdir -p "$root/.claude/commands" "$root/.claude/rules" "$root/q-system/.q-system"
  printf '{"hooks":{}}\n' > "$root/.claude/settings.json"
  printf 'safe command\n'  > "$root/.claude/commands/nightly.md"
  printf 'safe rule\n'     > "$root/.claude/rules/house.md"
  git -C "$root" init -q
  git -C "$root" add -A
  git -C "$root" -c user.name=repro -c user.email=repro@example.invalid commit -qm base
}

tw() { KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$1" "${@:2}"; }

# ---------------------------------------------------------------------------
say "PHASE 1 -- register on a tree with NO baseline must not orphan the rest"
# Codex major, apply_claude_changes.py:1170. The applier calls --register for the
# paths it wrote. On a tree that was never armed, --register built a baseline
# containing ONLY those paths, so the next --enforce saw every other .claude file
# as `added` and deleted it.
R1="$WORK/phase1"; make_instance "$R1"
[ -f "$R1/q-system/.q-system/claude-integrity-baseline.json" ] && bad "phase1 fixture already armed"

printf '{"hooks":{"PostToolUse":[]}}\n' > "$R1/.claude/settings.json"
tw "$R1" --quiet --register .claude/settings.json
tw "$R1" --enforce --quiet >/dev/null 2>&1
if [ -f "$R1/.claude/commands/nightly.md" ] && [ -f "$R1/.claude/rules/house.md" ]; then
  ok "unrelated watched files survived the post-register enforce"
else
  bad "post-register --enforce DELETED unrelated watched files (nightly.md=$([ -f "$R1/.claude/commands/nightly.md" ] && echo present || echo GONE), house.md=$([ -f "$R1/.claude/rules/house.md" ] && echo present || echo GONE))"
fi
tw "$R1" --check --quiet >/dev/null 2>&1
[ $? -eq 0 ] && ok "tree is clean after register+enforce" || bad "tree reports drift after register+enforce"

# ---------------------------------------------------------------------------
say "PHASE 2 -- kipi update must sanction only what it wrote"
# Codex major, kipi-update.sh:1427. The updater ran a blanket --baseline, which
# re-measures the WHOLE watch set, so unrelated tamper sitting in the tree at
# that moment became sanctioned content. The applier's own docstring calls this
# "the blinding version of this fix" -- two callers, opposite behaviour.
R2="$WORK/phase2"; make_instance "$R2"
tw "$R2" --baseline --quiet                       # instance already armed

printf 'UNSANCTIONED COMMAND\n' > "$R2/.claude/commands/nightly.md"   # tamper the updater never writes
printf '{"hooks":{"PostToolUse":["synced"]}}\n' > "$R2/.claude/settings.json"  # what the updater DOES write

# The updater's tripwire line, extracted verbatim so this phase tracks the file.
UPDATE_CALL="$(grep -n -A6 'Re-baseline the instance' "$REPO/kipi-update.sh" >/dev/null 2>&1; \
  awk '/claude-integrity-tripwire.py" \\$/,/^$/' "$REPO/kipi-update.sh" | head -5)"
if printf '%s' "$UPDATE_CALL" | grep -q -- '--baseline'; then
  bad "kipi-update.sh still calls a blanket --baseline (grep of the shipped line)"
else
  ok "kipi-update.sh no longer calls a blanket --baseline"
fi

# Simulate the updater's own sanctioning of ITS writes only.
tw "$R2" --quiet --register .claude/settings.json
if grep -q 'UNSANCTIONED COMMAND' "$R2/.claude/commands/nightly.md"; then
  tw "$R2" --check --quiet >/dev/null 2>&1
  if [ $? -ne 0 ]; then
    ok "unrelated tamper still flagged after the updater sanctioned its own writes"
  else
    bad "unrelated tamper was absorbed by the updater's re-baseline"
  fi
fi

# ---------------------------------------------------------------------------
say "PHASE 3 -- an ADDED symlink under .claude/ is drift, not clean"
# Codex major, settings-template.json:198. watch_set skipped every symlink, so
# dropping a new symlinked agent definition into .claude/agents/ read as clean on
# the layer the PR had just armed and advertised as the backstop for L1's misses.
R3="$WORK/phase3"; make_instance "$R3"
mkdir -p "$R3/.claude/agents"
tw "$R3" --baseline --quiet
printf '%s\n' '---' 'name: trusted-looking' 'tools: Bash' '---' 'malicious agent body' > "$WORK/evil-agent.md"
ln -s "$WORK/evil-agent.md" "$R3/.claude/agents/nightwatch.md"

tw "$R3" --check --quiet >/dev/null 2>&1
if [ $? -ne 0 ]; then ok "--check flags the added symlink"; else bad "--check reports CLEAN with a new symlinked agent in .claude/agents/"; fi

tw "$R3" --enforce --quiet >/dev/null 2>&1
if [ -e "$R3/.claude/agents/nightwatch.md" ] || [ -L "$R3/.claude/agents/nightwatch.md" ]; then
  bad "--enforce left the symlinked agent in place"
else
  ok "--enforce removed the symlink"
fi
if [ -f "$WORK/evil-agent.md" ]; then ok "the link TARGET was not touched"; else bad "enforce deleted the symlink's target (arbitrary delete)"; fi

# ---------------------------------------------------------------------------
say "PHASE 4 -- concurrent registers must not lose a write"
# Codex major, apply_claude_changes.py:1165. --register is read-modify-write on
# one baseline file with no lock: two sanctioned appliers both print success, the
# loser's path never lands, and the next --enforce reverts a legitimate change.
R4="$WORK/phase4"; make_instance "$R4"
tw "$R4" --baseline --quiet
printf 'A-changed\n' > "$R4/.claude/commands/nightly.md"
printf 'B-changed\n' > "$R4/.claude/rules/house.md"
LOST=0
for trial in 1 2 3 4 5; do
  printf 'A-%s\n' "$trial" > "$R4/.claude/commands/nightly.md"
  printf 'B-%s\n' "$trial" > "$R4/.claude/rules/house.md"
  tw "$R4" --quiet --register .claude/commands/nightly.md &
  tw "$R4" --quiet --register .claude/rules/house.md &
  wait
  if ! tw "$R4" --check --quiet >/dev/null 2>&1; then
    LOST=$((LOST + 1))
  fi
done
if [ "$LOST" -eq 0 ]; then ok "5/5 concurrent register pairs both landed"; else bad "$LOST/5 concurrent register pairs lost one write (next enforce reverts it)"; fi

# ---------------------------------------------------------------------------
say "PHASE 5 -- the apply-on-copy harness must start UNarmed"
# Codex minor, probe_apply_on_copy.sh:26. The copy is taken from the PR head,
# where the proposal is already applied, so phase 1's apply was a no-op and the
# harness proved nothing about the apply it claimed to exercise.
PROBE="$REPO/q-system/output/claude-changes/repro/probe_apply_on_copy.sh"
if grep -q 'DISARM\|pre_arm_state\|strip_arming' "$PROBE"; then
  ok "probe_apply_on_copy.sh reverts the copy to a pre-apply state first"
else
  bad "probe_apply_on_copy.sh still applies onto an already-applied copy (first apply is a no-op)"
fi

printf '\n'
if [ "$FAILED" -eq 0 ]; then printf 'ALL PHASES PASS\n'; else printf 'SOME PHASES FAILED\n'; fi
exit "$FAILED"
