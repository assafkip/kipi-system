#!/bin/bash
set -euo pipefail

# kipi-new-instance.sh - Create a new kipi-system instance
# Usage: ./kipi-new-instance.sh <path> <name>

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGISTRY="$SCRIPT_DIR/instance-registry.json"

# Preflight: a fresh instance is the one nobody thinks to re-check, so a leak
# that cannot ride `kipi update` can still ride `kipi new` and sit there.
# Same fail-closed contract as kipi-update.sh: the gate must state its own
# verdict before its exit code is believed, since a zero-byte gate script is a
# valid program that exits 0 and would otherwise pass in silence.
LEAK_GATE="$SCRIPT_DIR/q-system/.q-system/scripts/propagation-leak-gate.py"
if [ ! -f "$LEAK_GATE" ]; then
  echo "ABORT: propagation leak gate missing at $LEAK_GATE"
  exit 1
fi
if LEAK_OUT="$(python3 "$LEAK_GATE" --check --repo-root "$SCRIPT_DIR" 2>&1)"; then
  LEAK_RC=0
else
  LEAK_RC=$?
fi
printf '%s\n' "$LEAK_OUT"
if ! printf '%s' "$LEAK_OUT" | grep -q "^propagation leak gate: "; then
  echo "ABORT: the propagation leak gate did not report a verdict"
  exit 1
fi
if [ "$LEAK_RC" -ne 0 ]; then
  echo "ABORT: a fact absent from the propagation baseline would seed into the"
  echo "new instance (named above). Fix it or re-baseline explicitly."
  exit 1
fi
# The gate scans the INDEX; the seed below uses `git archive HEAD`. Staging a
# fix without committing it means the gate certifies a tree that is not the one
# being copied, and HEAD wins.
if ! git -C "$SCRIPT_DIR" diff --cached --quiet HEAD -- q-system/ 2>/dev/null; then
  echo "ABORT: q-system/ is staged but not committed."
  echo "The gate scanned the index and the seed copies HEAD; they must agree."
  exit 1
fi
SKELETON_REMOTE="https://github.com/assafkip/kipi-system.git"
SKELETON_BRANCH="main"
PREFIX="q-system"

if [ $# -lt 2 ]; then
  echo "Usage: $0 <path> <name>"
  echo "  path: directory to create the instance in"
  echo "  name: short name for the instance (e.g., my-startup)"
  exit 1
fi

INST_PATH="$1"
INST_NAME="$2"

if [ -d "$INST_PATH/$PREFIX" ]; then
  echo "ERROR: $INST_PATH/$PREFIX already exists. Aborting."
  exit 1
fi

echo "=== Creating new kipi instance ==="
echo "  Path: $INST_PATH"
echo "  Name: $INST_NAME"
echo ""

# Create directory if needed
mkdir -p "$INST_PATH"
cd "$INST_PATH"

# Init git if needed
if [ ! -d .git ]; then
  git init
  echo "  Initialized git repo"
fi

# A PRIVATE remote is the DEFAULT. Local-only must be asked for, in writing.
#
# Scar 2026-07-29: this script created git repos and never a remote, so an
# instance's only copy was the laptop. The audit found 12 remote-less repos,
# oldest 219 commits, several of them client engagements, plus 475 client files
# in a directory that was not a repo at all. Inflow was automated, outflow was
# manual, so the default silently accumulated risk for months.
#
# Opting out is deliberate and self-documenting:
#   KIPI_LOCAL_ONLY=1 KIPI_LOCAL_ONLY_REASON="..." kipi new <path> <name>
# The reason is written to remote-coverage-allow.json AT CREATION TIME, so a
# local-only instance is a recorded decision on day one rather than an audit
# finding a year later. Some instances genuinely must stay local (family
# health data), which is exactly why the escape hatch exists and is loud.
KIPI_REMOTE_NAME="${KIPI_REMOTE:-$INST_NAME}"
COVERAGE_TOOL="$SCRIPT_DIR/remote-coverage-check.py"

if [ -n "${KIPI_LOCAL_ONLY:-}" ]; then
  if [ -z "${KIPI_LOCAL_ONLY_REASON:-}" ]; then
    echo "ERROR: KIPI_LOCAL_ONLY=1 requires KIPI_LOCAL_ONLY_REASON=\"why\"." >&2
    echo "       An undeclared local-only instance is the bug this prevents." >&2
    exit 1
  fi
  echo "  LOCAL-ONLY by request. Recording the decision..."
  python3 "$COVERAGE_TOOL" --declare "$INST_PATH" \
    --reason "$KIPI_LOCAL_ONLY_REASON" || {
      echo "ERROR: could not record the local-only decision; refusing to" >&2
      echo "       leave an undeclared remote-less instance behind." >&2
      exit 1; }
elif command -v gh >/dev/null 2>&1; then
  echo "  Creating PRIVATE remote assafkip/$KIPI_REMOTE_NAME ..."
  # --private is not a default to be overridden here: a fresh instance carries
  # the skeleton's enforcement layer plus whatever the operator seeds next, and
  # nobody has reviewed that content yet. Public is a later, explicit choice.
  if gh repo create "assafkip/$KIPI_REMOTE_NAME" --private --source="$INST_PATH" 2>&1; then
    echo "  Remote added: assafkip/$KIPI_REMOTE_NAME (private)"
  else
    echo "  WARNING: remote creation failed; instance is LOCAL-ONLY." >&2
    echo "           \`kipi check\` will stay RED until you push it or run:" >&2
    echo "           python3 $COVERAGE_TOOL --declare $INST_PATH --reason '...'" >&2
  fi
else
  echo "  WARNING: gh not installed; instance is LOCAL-ONLY." >&2
  echo "           \`kipi check\` will stay RED until resolved." >&2
fi

# Ensure at least one commit exists
if ! git rev-parse HEAD >/dev/null 2>&1; then
  git commit --allow-empty -m "Initial commit"
fi

# Seed $PREFIX/ with the skeleton's q-system/ CONTENT only (same layout kipi-update.sh
# maintains). The old `git subtree add` put the ENTIRE skeleton repo under $PREFIX/
# (root scripts, README, plugins/, plus a nested q-system/q-system/ shadow tree that
# included a snapshot of the skeleton's own memory/). Every instance created that way
# carried 30-350 stale junk files the updater could never delete. Scar: fleet cleanup
# 2026-07-01 removed the shadow trees from 18/19 instances.
# The seed must copy exactly what the gate scans, or the preflight above is a
# green light over content nobody looked at. The gate derives its scope from
# kipi-update.sh's five anchored rsync excludes, so this seed carries the same
# five. Measured before this exclusion existed: 168 of 604 seeded files were
# never scanned, including all 26 tracked canonical/ and my-project/ files --
# the client deliverables and pricing framework -- landing in every fresh
# instance under a clean verdict. Excluding them is also just correct seeding:
# a new instance should start with its OWN canonical, not the skeleton's.
echo "  Seeding $PREFIX/ from skeleton q-system/ (git archive)..."
mkdir -p "$PREFIX"
git -C "$SCRIPT_DIR" archive --format=tar HEAD -- q-system/ \
  | tar -x --strip-components=1 -C "$PREFIX" \
      --exclude='q-system/my-project/*' \
      --exclude='q-system/canonical/*' \
      --exclude='q-system/memory/*' \
      --exclude='q-system/output/*' \
      --exclude='q-system/.q-system/agent-pipeline/bus/*'
echo "  Skeleton q-system content seeded"

# Create instance CLAUDE.md
if [ ! -f CLAUDE.md ]; then
  cat > CLAUDE.md << 'CLAUDE_EOF'
# {{INSTANCE_NAME}}

## About
{{DESCRIPTION}}

## Entrepreneur OS
@q-system/CLAUDE.md

## Conventions
- Never produce fluff - every sentence must carry information or enable action
- Mark unvalidated claims with `{{UNVALIDATED}}` or `{{NEEDS_PROOF}}`
CLAUDE_EOF
  sed -i '' "s/{{INSTANCE_NAME}}/$INST_NAME/g" CLAUDE.md 2>/dev/null || true
  echo "  Created template CLAUDE.md"
fi

# Set up .claude/ directory (hooks, rules, agents, output style)
echo "  Setting up .claude/ configuration..."
mkdir -p .claude/agents .claude/output-styles .claude/rules
cp "$SCRIPT_DIR/settings-template.json" .claude/settings.json

# No hook-path rewriting: the archive seeding above puts skeleton q-system/ CONTENT
# at $PREFIX/, so template paths like q-system/.q-system/scripts/X.py are already
# correct. The old sed doubling to q-system/q-system/ matched the old subtree layout
# and produced dead hook paths after the first kipi update flattened it.

cp "$SCRIPT_DIR"/.claude/agents/*.md .claude/agents/ 2>/dev/null || true
cp "$SCRIPT_DIR"/.claude/output-styles/*.md .claude/output-styles/ 2>/dev/null || true
cp "$SCRIPT_DIR"/.claude/rules/*.md .claude/rules/ 2>/dev/null || true

# Copy root .mcp.json so research-mode (Perplexity) and other MCP servers
# are available at the instance root, where Claude Code looks for .mcp.json
if [ ! -f .mcp.json ] && [ -f "$SCRIPT_DIR/.mcp.json" ]; then
  cp "$SCRIPT_DIR/.mcp.json" .mcp.json
  echo "  Copied .mcp.json (set PERPLEXITY_API_KEY + other tokens in env)"
fi

# Set up plugins (copy contents, not directory, to avoid nesting).
# rsync, not cp -R: a symlinked skeleton plugin (memory-lifecycle -> standalone repo)
# would otherwise materialize WITH its .git, leaving the instance permanently dirty
# on plugins/<name> in git status. Mirrors kipi-update.sh.
if [ -d "$SCRIPT_DIR/plugins" ]; then
  mkdir -p plugins
  for plugin_dir in "$SCRIPT_DIR"/plugins/*/; do
    if [ -d "$plugin_dir" ]; then
      plugin_name="$(basename "$plugin_dir")"
      rsync -a --exclude="/.git/" --exclude="__pycache__/" --exclude="*.pyc" \
        "$plugin_dir" "plugins/$plugin_name/"
    fi
  done
fi

# Set up .gitignore (no .githooks - instances should not run skeleton validation)
cp "$SCRIPT_DIR/.gitignore" .gitignore 2>/dev/null || true

echo "  .claude/ configured with rules, agents, and plugins"

# Commit only instance files (never skeleton root files like validate-separation.py, instance-registry.json, kipi-*.sh)
git add "$PREFIX/" .claude/ plugins/ .gitignore CLAUDE.md .mcp.json 2>/dev/null || true
git commit -m "Seed kipi-system q-system content with .claude config"

# Register in instance-registry.json
echo "  Registering in instance-registry.json..."
python3 -c "
import json
reg = json.load(open('$REGISTRY'))
entry = {
    'name': '$INST_NAME',
    'path': '$(cd "$INST_PATH" && pwd)',
    'subtree_prefix': '$PREFIX',
    'instance_q_dir': None,
    'type': 'subtree',
    'has_git': True
}
# Check if already registered
names = [i['name'] for i in reg['instances']]
if '$INST_NAME' not in names:
    reg['instances'].append(entry)
    json.dump(reg, open('$REGISTRY', 'w'), indent=2)
    print('  Registered')
else:
    print('  Already registered')
"

# Queue a Linear project for the new instance (ASK-113, goal 3).
#
# This CANNOT call Linear directly: there is no Linear API key in ~/.config/kipi/
# and no LINEAR_* env var, so Linear is reachable only through the MCP server,
# which a shell script cannot use. So capture here, offline and unfailing, and let
# the agent-side /linear-drain create the project where credentials exist.
#
# `|| true` because a queue problem must never fail an instance creation that has
# already succeeded. The script itself warns loudly on stderr if it cannot write.
QUEUE_SCRIPT="$SCRIPT_DIR/q-system/.q-system/scripts/linear-queue.py"
if [ -f "$QUEUE_SCRIPT" ]; then
  KIPI_LINEAR_QUEUE="${KIPI_LINEAR_QUEUE:-$SCRIPT_DIR/.linear-queue.jsonl}" \
    python3 "$QUEUE_SCRIPT" add \
      --repo "$INST_NAME" \
      --kind project \
      --title "$INST_NAME" \
      --note "Auto-queued by kipi new. Instance at $(cd "$INST_PATH" && pwd)." \
      --source kipi-new >/dev/null 2>&1 || true
  echo "  Linear project queued (run /linear-drain in a Claude session to create it)"
fi

echo ""
echo "=== Done ==="
echo "Instance created at $INST_PATH"
echo "Next: edit CLAUDE.md to add your project details, then run the setup wizard."

# The remote was created BEFORE the seed commit existed, so push now that there
# is something to push. Without this the instance has an origin and no content,
# which the coverage gate counts as covered and a disk failure would disprove.
if [ -n "$(git -C "$INST_PATH" remote 2>/dev/null)" ]; then
  echo ""
  if git -C "$INST_PATH" push -u origin HEAD 2>&1 | tail -2; then
    echo "Pushed to assafkip/$KIPI_REMOTE_NAME (private)."
  else
    echo "WARNING: push failed. Content is committed locally but NOT off-disk." >&2
  fi
else
  # A remote-less instance must never end the run silently -- that silence is
  # the whole 2026-07-29 scar. Say it out loud and name both legitimate exits.
  echo ""
  echo "NOTE: this instance has NO git remote. Its only copy is this disk."
  echo "  push it:    gh repo create assafkip/<name> --private --source=$INST_PATH --push"
  echo "  or declare: python3 $SCRIPT_DIR/remote-coverage-check.py \\"
  echo "                --declare $INST_PATH --reason '<why, class not content>'"
  echo "  \`kipi check\` stays RED until you do one of those."
fi
