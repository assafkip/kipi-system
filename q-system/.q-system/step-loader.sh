#!/bin/bash
# Step Loader - Echo of Prompt (EOP) for morning routine steps.
#
# Extracts the specific step definition from commands.md and prints it.
# This re-injects the step's requirements into the LLM's context
# RIGHT BEFORE the step executes, combating "Lost in the Middle."
#
# Research: "Echo of Prompt" behavior increases answer-to-answer-prefix
# attention in middle layers, guiding the model to concentrate on
# critical details that are often overlooked.
#
# Usage:
#   bash q-system/.q-system/step-loader.sh <step_id>
#   Example: bash q-system/.q-system/step-loader.sh 5.85
#
# The output goes to stdout and should be read by Claude before
# executing the step. This is NOT optional.

STEP_ID="$1"
COMMANDS_FILE="q-system/.q-system/commands.md"
STEPS_DIR="q-system/.q-system/steps"

if [ -z "$STEP_ID" ]; then
  echo "Usage: bash q-system/.q-system/step-loader.sh <step_id>" >&2
  exit 1
fi

# Try individual step file FIRST (saves ~43K tokens vs reading full commands.md)
SAFE_ID=$(echo "$STEP_ID" | sed 's/\./-/g')
STEP_FILE="${STEPS_DIR}/step-${SAFE_ID}.md"

if [ -f "$STEP_FILE" ]; then
  echo "================================================================"
  echo "  STEP ${STEP_ID} REQUIREMENTS (loaded from step file)"
  echo "  Read these BEFORE executing. Do not skip any requirement."
  echo "================================================================"
  echo ""
  cat "$STEP_FILE"
  echo ""
  echo "================================================================"
  echo "  Execute this step now. Log deliverables, not just 'done'."
  echo "================================================================"
  exit 0
fi

# Fallback: extract from monolithic commands.md
if [ ! -f "$COMMANDS_FILE" ]; then
  echo "Neither step file ($STEP_FILE) nor commands file ($COMMANDS_FILE) found" >&2
  exit 1
fi

# Map step IDs to search patterns in commands.md
case "$STEP_ID" in
  "5.85") PATTERN="Step 5.85" ;;
  "5.86") PATTERN="Step 5.86" ;;
  "5.9")  PATTERN="Step 5.9 -" ;;
  "5.9b") PATTERN="Step 5.9b\|Daily Engagement Hitlist" ;;
  "4")    PATTERN="Step 4:" ;;
  "4.1")  PATTERN="Step 4.1" ;;
  "3")    PATTERN="Step 3 —\|Step 3:" ;;
  "3.8")  PATTERN="Step 3.8" ;;
  "0b.5") PATTERN="0b.5 - Loop" ;;
  "8")    PATTERN="Step 8 —\|GATE CHECK.*step 8" ;;
  "9")    PATTERN="Step 9 —" ;;
  "11")   PATTERN="Step 11\|MANDATORY FINAL STEP" ;;
  *)      PATTERN="Step ${STEP_ID}" ;;
esac

# Extract the step section (from the pattern to the next "Step X" or "---")
echo "================================================================"
echo "  STEP ${STEP_ID} REQUIREMENTS (re-injected from commands.md)"
echo "  Read these BEFORE executing. Do not skip any requirement."
echo "================================================================"
echo ""

# Use python for reliable multi-line extraction
python3 -c "
import re
with open('${COMMANDS_FILE}') as f:
    content = f.read()

# Find the step section
pattern = r'${PATTERN}'
lines = content.split('\n')
start = None
for i, line in enumerate(lines):
    if re.search(pattern, line):
        start = i
        break

if start is None:
    print('Step ${STEP_ID} not found in commands.md')
    exit(0)

# Extract until next major step header or separator
end = start + 1
step_pattern = re.compile(r'^\*\*Step \d|^---$|^##')
for i in range(start + 1, min(start + 100, len(lines))):
    if step_pattern.match(lines[i]) and i > start + 2:
        end = i
        break
    end = i

# Print the step definition (max 80 lines to keep context manageable)
section = lines[start:min(end, start + 80)]
print('\n'.join(section))
"

echo ""
echo "================================================================"
echo "  Execute this step now. Log deliverables, not just 'done'."
echo "================================================================"
