#!/bin/bash
# Kipi System Separation - Validation Harness
# Usage: ./validate-separation.sh <phase> [--verbose]
# Runs all checks up to and including the specified phase.
# Exit code 0 = all checks pass. Non-zero = failure.

set -o pipefail

PHASE="${1:-0}"
VERBOSE="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGISTRY="$SCRIPT_DIR/instance-registry.json"

PASS=0
FAIL=0
WARN=0
ERRORS=""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

check() {
  local description="$1"
  local result="$2"  # 0=pass, 1=fail
  if [ "$result" -eq 0 ]; then
    echo -e "  ${GREEN}PASS${NC} $description"
    PASS=$((PASS + 1))
  else
    echo -e "  ${RED}FAIL${NC} $description"
    FAIL=$((FAIL + 1))
    ERRORS="$ERRORS\n  - $description"
  fi
}

warn() {
  local description="$1"
  echo -e "  ${YELLOW}WARN${NC} $description"
  WARN=$((WARN + 1))
}

phase_header() {
  echo ""
  echo -e "${BLUE}=== Phase $1: $2 ===${NC}"
}

# ---------- PHASE 0: Pre-execution ----------
if [ "$PHASE" -ge 0 ]; then
  phase_header 0 "Pre-execution checks"

  # Registry exists
  if [ -f "$REGISTRY" ]; then check "instance-registry.json exists" 0; else check "instance-registry.json exists" 1; fi

  # Skeleton directory exists
  if [ -d "$SCRIPT_DIR/q-system" ]; then check "q-system/ directory exists in skeleton" 0; else check "q-system/ directory exists in skeleton" 1; fi

  # All instance paths exist
  for path in $(python3 -c "import json; d=json.load(open('$REGISTRY')); [print(i['path']) for i in d['instances']]" 2>/dev/null); do
    if [ -d "$path" ]; then check "Instance path exists: $(basename $path)" 0; else check "Instance path exists: $(basename $path)" 1; fi
  done
fi

# ---------- PHASE 1: Skeleton updated ----------
if [ "$PHASE" -ge 1 ]; then
  phase_header 1 "Skeleton integrity"

  AGENTS_DIR="$SCRIPT_DIR/q-system/.q-system/agent-pipeline/agents"
  SCRIPTS_DIR="$SCRIPT_DIR/q-system/.q-system"

  # --- GATE 1.1: Agent files ---
  echo ""
  echo "  --- Gate 1.1: Agent files ---"

  # Agent count
  AGENT_COUNT=$(find "$AGENTS_DIR" -name "*.md" -not -name "_*" -not -name "step-*" 2>/dev/null | wc -l | tr -d ' ')
  [ "$AGENT_COUNT" -ge 35 ]
  check "Agent count >= 35 (found: $AGENT_COUNT)" $?

  # Frontmatter on all agents
  MISSING_FRONTMATTER=0
  for f in "$AGENTS_DIR"/[0-9]*.md; do
    if [ -f "$f" ] && ! head -1 "$f" | grep -q "^---$"; then
      MISSING_FRONTMATTER=$((MISSING_FRONTMATTER + 1))
      [ -n "$VERBOSE" ] && warn "Missing frontmatter: $(basename $f)"
    fi
  done
  [ "$MISSING_FRONTMATTER" -eq 0 ]
  check "All numbered agents have YAML frontmatter ($MISSING_FRONTMATTER missing)" $?

  # Reads/Writes sections
  MISSING_RW=0
  for f in "$AGENTS_DIR"/[0-9]*.md; do
    if [ -f "$f" ]; then
      if ! grep -q "## Reads" "$f" && ! grep -q "## Read" "$f"; then
        MISSING_RW=$((MISSING_RW + 1))
        [ -n "$VERBOSE" ] && warn "Missing Reads section: $(basename $f)"
      fi
    fi
  done
  [ "$MISSING_RW" -eq 0 ]
  check "All numbered agents have Reads section ($MISSING_RW missing)" $?

  # No KTLYST-specific terms in agents
  KTLYST_HITS=$(grep -ril "KTLYST\|ktlyst\|q-ktlyst\|re-breach\|re\.breach\|threat.intel.*team\|CNS.*nervous" "$AGENTS_DIR"/ 2>/dev/null | wc -l | tr -d ' ')
  [ "$KTLYST_HITS" -eq 0 ]
  check "No KTLYST-specific terms in agent files ($KTLYST_HITS files)" $?

  # No hardcoded paths
  HARDCODED=$(grep -ril "/Users/assafkip\|q-ktlyst/" "$AGENTS_DIR"/ 2>/dev/null | wc -l | tr -d ' ')
  [ "$HARDCODED" -eq 0 ]
  check "No hardcoded paths in agent files ($HARDCODED files)" $?

  # Key config files exist
  [ -f "$AGENTS_DIR/step-orchestrator.md" ]
  check "step-orchestrator.md exists" $?

  [ -f "$AGENTS_DIR/_cadence-config.yaml" ] || [ -f "$AGENTS_DIR/_cadence-config.md" ]
  check "_cadence-config exists (.yaml or .md)" $?

  [ -f "$AGENTS_DIR/_auto-fail-checklist.md" ]
  check "_auto-fail-checklist.md exists" $?

  # --- GATE 1.2: Scripts ---
  echo ""
  echo "  --- Gate 1.2: Scripts ---"

  for script in "audit-morning.py" "verify-schedule.py" "token-guard.py"; do
    [ -f "$SCRIPTS_DIR/$script" ]
    check "$script exists" $?
  done

  # Check for ported scripts (may be in scripts/ subdir)
  SCAN_DRAFT=$(find "$SCRIPTS_DIR" -name "scan-draft.py" 2>/dev/null | head -1)
  [ -n "$SCAN_DRAFT" ]
  check "scan-draft.py exists (anti-AI scanner)" $?

  VERIFY_BUS=$(find "$SCRIPTS_DIR" -name "verify-bus.py" 2>/dev/null | head -1)
  [ -n "$VERIFY_BUS" ]
  check "verify-bus.py exists" $?

  VERIFY_ORCH=$(find "$SCRIPTS_DIR" -name "verify-orchestrator.py" 2>/dev/null | head -1)
  [ -n "$VERIFY_ORCH" ]
  check "verify-orchestrator.py exists" $?

  BUILD_SCHED="$SCRIPT_DIR/q-system/marketing/templates/build-schedule.sh"
  [ -f "$BUILD_SCHED" ] && [ -s "$BUILD_SCHED" ]
  check "build-schedule.sh exists and is non-empty" $?

  # No KTLYST in scripts
  SCRIPT_HITS=$(find "$SCRIPTS_DIR" -name "*.py" -o -name "*.sh" | xargs grep -il "KTLYST\|ktlyst\|q-ktlyst" 2>/dev/null | wc -l | tr -d ' ')
  [ "$SCRIPT_HITS" -eq 0 ]
  check "No KTLYST references in scripts ($SCRIPT_HITS files)" $?

  # --- GATE 1.3: Canonical templates ---
  echo ""
  echo "  --- Gate 1.3: Canonical templates ---"

  CANONICAL="$SCRIPT_DIR/q-system/canonical"
  for tmpl in "discovery.md" "objections.md" "talk-tracks.md" "decisions.md" "engagement-playbook.md" "lead-lifecycle-rules.md" "market-intelligence.md" "pricing-framework.md" "verticals.md"; do
    [ -f "$CANONICAL/$tmpl" ]
    check "canonical/$tmpl exists" $?
  done

  MY_PROJECT="$SCRIPT_DIR/q-system/my-project"
  [ -f "$MY_PROJECT/founder-profile.md" ]
  check "my-project/founder-profile.md exists" $?

  grep -q "SETUP_NEEDED" "$MY_PROJECT/founder-profile.md" 2>/dev/null
  check "founder-profile.md contains {{SETUP_NEEDED}}" $?

  CANONICAL_KTLYST=$(grep -ril "KTLYST\|ktlyst\|Assaf\|CISO.*pain\|re-breach" "$CANONICAL"/ 2>/dev/null | wc -l | tr -d ' ')
  [ "$CANONICAL_KTLYST" -eq 0 ]
  check "No KTLYST content in canonical templates ($CANONICAL_KTLYST files)" $?

  # --- GATE 1.4: Voice skill framework ---
  echo ""
  echo "  --- Gate 1.4: Voice skill ---"

  VOICE="$SCRIPT_DIR/.claude/skills/founder-voice"
  [ -f "$VOICE/SKILL.md" ]
  check "founder-voice SKILL.md exists" $?

  [ -f "$VOICE/references/voice-dna.md" ]
  check "voice-dna.md template exists" $?

  [ -f "$VOICE/references/writing-samples.md" ]
  check "writing-samples.md template exists" $?

  VOICE_KTLYST=$(grep -ril "Assaf\|KTLYST\|threat.intel.*Google\|threat.intel.*Meta" "$VOICE"/ 2>/dev/null | wc -l | tr -d ' ')
  [ "$VOICE_KTLYST" -eq 0 ]
  check "No Assaf-specific content in voice framework ($VOICE_KTLYST files)" $?

  # --- GATE 1.5: CLAUDE.md ---
  echo ""
  echo "  --- Gate 1.5: CLAUDE.md ---"

  [ -f "$SCRIPT_DIR/CLAUDE.md" ]
  check "Root CLAUDE.md exists" $?

  [ -f "$SCRIPT_DIR/q-system/CLAUDE.md" ]
  check "q-system/CLAUDE.md exists" $?

  CLAUDE_KTLYST=$(grep -ci "KTLYST\|ktlyst\|Assaf\|re-breach\|CISO.*pain" "$SCRIPT_DIR/q-system/CLAUDE.md" 2>/dev/null || true)
  CLAUDE_KTLYST="${CLAUDE_KTLYST:-0}"
  if [ "$CLAUDE_KTLYST" -eq 0 ] 2>/dev/null; then check "No KTLYST references in q-system/CLAUDE.md ($CLAUDE_KTLYST hits)" 0; else check "No KTLYST references in q-system/CLAUDE.md ($CLAUDE_KTLYST hits)" 1; fi

  # --- GATE 1.6: build-schedule.sh ---
  echo ""
  echo "  --- Gate 1.6: build-schedule.sh ---"

  if [ -f "$BUILD_SCHED" ]; then
    grep -q "verify-schedule" "$BUILD_SCHED" 2>/dev/null
    check "build-schedule.sh has verification gate" $?
  fi

  # --- Full skeleton sweep ---
  echo ""
  echo "  --- Full skeleton sweep ---"

  FULL_SWEEP=$(grep -ril "KTLYST\|ktlyst\|q-ktlyst\|/Users/assafkip" "$SCRIPT_DIR/q-system/" 2>/dev/null | grep -v "PHASE-0-AUDIT\|EXECUTION-PLAN\|validate-separation\|instance-registry" | wc -l | tr -d ' ')
  [ "$FULL_SWEEP" -eq 0 ]
  check "Full skeleton sweep: zero KTLYST/hardcoded refs ($FULL_SWEEP files)" $?
fi

# ---------- PHASE 2: KTLYST subtree ----------
if [ "$PHASE" -ge 2 ]; then
  phase_header 2 "KTLYST_strategy subtree"

  KTLYST="/Users/assafkip/Desktop/KTLYST_strategy"

  [ -d "$KTLYST/q-system" ]
  check "KTLYST has q-system/ directory" $?

  [ ! -d "$KTLYST/q-ktlyst" ]
  check "KTLYST no longer has q-ktlyst/ directory" $?

  # Subtree check: q-system should have agent files
  K_AGENTS="$KTLYST/q-system/.q-system/agent-pipeline/agents"
  if [ -d "$K_AGENTS" ]; then
    K_COUNT=$(find "$K_AGENTS" -name "*.md" -not -name "_*" -not -name "step-*" 2>/dev/null | wc -l | tr -d ' ')
    [ "$K_COUNT" -ge 35 ]
    check "KTLYST q-system/ has agents ($K_COUNT)" $?
  else
    check "KTLYST q-system/ agent directory exists" 1
  fi

  # Instance content separated
  [ -d "$KTLYST/instance" ] || [ -d "$KTLYST/canonical" ]
  check "KTLYST instance content is separated from subtree" $?

  # Instance CLAUDE.md
  [ -f "$KTLYST/CLAUDE.md" ]
  check "KTLYST root CLAUDE.md exists" $?

  if [ -f "$KTLYST/CLAUDE.md" ]; then
    grep -q "@q-system" "$KTLYST/CLAUDE.md" 2>/dev/null || grep -q "q-system/CLAUDE.md" "$KTLYST/CLAUDE.md" 2>/dev/null
    check "KTLYST CLAUDE.md imports skeleton" $?
  fi

  # No plugin dependency
  PLUGIN_REFS=$(grep -ril "kipi-pipeline-plugin" "$KTLYST/" 2>/dev/null | grep -v ".git/" | wc -l | tr -d ' ')
  [ "$PLUGIN_REFS" -eq 0 ]
  check "No kipi-pipeline-plugin references in KTLYST ($PLUGIN_REFS)" $?

  # Scripts work
  if [ -f "$KTLYST/q-system/.q-system/audit-morning.py" ]; then
    python3 -c "import ast; ast.parse(open('$KTLYST/q-system/.q-system/audit-morning.py').read())" 2>/dev/null
    check "audit-morning.py parses without errors" $?
  fi
fi

# ---------- PHASE 3: Plugin eliminated ----------
if [ "$PHASE" -ge 3 ]; then
  phase_header 3 "Plugin elimination"

  [ ! -d "/Users/assafkip/Desktop/kipi-pipeline-plugin" ]
  check "kipi-pipeline-plugin directory removed" $?

  [ ! -d "/Users/assafkip/Desktop/q-founder-os" ]
  check "q-founder-os directory removed" $?

  # Global references
  GLOBAL_PLUGIN=$(grep -ril "kipi-pipeline-plugin" ~/.claude/ 2>/dev/null | wc -l | tr -d ' ')
  [ "$GLOBAL_PLUGIN" -eq 0 ]
  check "No plugin references in ~/.claude/ ($GLOBAL_PLUGIN)" $?
fi

# ---------- PHASE 4: All instances updated ----------
if [ "$PHASE" -ge 4 ]; then
  phase_header 4 "All instances"

  for instance_json in $(python3 -c "
import json
d = json.load(open('$REGISTRY'))
for i in d['instances']:
    print(i['name'] + '|' + i['path'] + '|' + i['subtree_prefix'])
" 2>/dev/null); do
    IFS='|' read -r name path prefix <<< "$instance_json"
    echo ""
    echo "  --- $name ---"

    [ -d "$path/$prefix" ]
    check "$name: $prefix/ directory exists" $?

    if [ -d "$path/$prefix/.q-system/agent-pipeline/agents" ]; then
      I_COUNT=$(find "$path/$prefix/.q-system/agent-pipeline/agents" -name "*.md" -not -name "_*" -not -name "step-*" 2>/dev/null | wc -l | tr -d ' ')
      [ "$I_COUNT" -ge 35 ]
      check "$name: has agents ($I_COUNT)" $?
    else
      check "$name: agent directory exists" 1
    fi

    [ -f "$path/CLAUDE.md" ]
    check "$name: root CLAUDE.md exists" $?
  done
fi

# ---------- PHASE 5: Propagation + docs ----------
if [ "$PHASE" -ge 5 ]; then
  phase_header 5 "Propagation and documentation"

  [ -f "$SCRIPT_DIR/kipi-update.sh" ] && [ -x "$SCRIPT_DIR/kipi-update.sh" ]
  check "kipi-update.sh exists and is executable" $?

  [ -f "$SCRIPT_DIR/kipi-new-instance.sh" ] && [ -x "$SCRIPT_DIR/kipi-new-instance.sh" ]
  check "kipi-new-instance.sh exists and is executable" $?

  [ -f "$SCRIPT_DIR/kipi-push-upstream.sh" ] && [ -x "$SCRIPT_DIR/kipi-push-upstream.sh" ]
  check "kipi-push-upstream.sh exists and is executable" $?

  for doc in "SETUP.md" "UPDATE.md" "CONTRIBUTE.md" "ARCHITECTURE.md"; do
    [ -f "$SCRIPT_DIR/$doc" ]
    check "Documentation: $doc exists" $?
  done

  # No KTLYST in docs
  DOC_KTLYST=$(grep -il "KTLYST\|ktlyst" "$SCRIPT_DIR/SETUP.md" "$SCRIPT_DIR/UPDATE.md" "$SCRIPT_DIR/CONTRIBUTE.md" "$SCRIPT_DIR/ARCHITECTURE.md" 2>/dev/null | wc -l | tr -d ' ')
  [ "$DOC_KTLYST" -eq 0 ]
  check "No KTLYST references in documentation ($DOC_KTLYST)" $?
fi

# ---------- SUMMARY ----------
echo ""
echo -e "${BLUE}==============================${NC}"
echo -e "${BLUE}  VALIDATION SUMMARY (Phase $PHASE)${NC}"
echo -e "${BLUE}==============================${NC}"
echo -e "  ${GREEN}PASS: $PASS${NC}"
echo -e "  ${RED}FAIL: $FAIL${NC}"
echo -e "  ${YELLOW}WARN: $WARN${NC}"

if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo -e "${RED}FAILURES:${NC}"
  echo -e "$ERRORS"
  echo ""
  echo -e "${RED}GATE FAILED. Do not proceed to Phase $((PHASE + 1)).${NC}"
  exit 1
else
  echo ""
  echo -e "${GREEN}ALL CHECKS PASSED. Phase $PHASE gate is GREEN.${NC}"
  exit 0
fi
