#!/bin/bash
# Morning routine step logger
# Writes step completion to the morning log JSON file on disk.
#
# Usage:
#   bash q-system/.q-system/log-step.sh <date> <step_id> <status> <result> [error]
#
# Examples:
#   bash q-system/.q-system/log-step.sh 2026-03-14 0f_connection_check done "7/7 passed"
#   bash q-system/.q-system/log-step.sh 2026-03-14 1_notion_actions failed "" "property Status not found"
#   bash q-system/.q-system/log-step.sh 2026-03-14 5_site_metrics skipped "" "Monday only"
#   bash q-system/.q-system/log-step.sh 2026-03-14 5.9_lead_sourcing partial "LinkedIn+Reddit only"
#
# Special commands:
#   bash q-system/.q-system/log-step.sh <date> init
#     Creates the morning log file with empty structure
#
#   bash q-system/.q-system/log-step.sh <date> add-card <id> <type> <target> <draft_text>
#     Adds an action card to the morning log
#
#   bash q-system/.q-system/log-step.sh <date> gate-check <gate_step> <all_prior_done> [missing_steps]
#     Logs a gate check result
#
#   bash q-system/.q-system/log-step.sh <date> checksum-start <key> <value>
#     Records a session-start state checksum
#
#   bash q-system/.q-system/log-step.sh <date> checksum-end <key> <value>
#     Records a session-end state checksum
#
#   bash q-system/.q-system/log-step.sh <date> verify <claim> <source> <verified> <result>
#     Adds or updates a verification queue entry

set -e

DATE="$1"
LOG_FILE="q-system/output/morning-log-${DATE}.json"

if [ -z "$DATE" ]; then
  echo "Usage: bash q-system/.q-system/log-step.sh <date> <step_id> <status> <result> [error]" >&2
  exit 1
fi

# INIT: Create empty morning log
if [ "$2" = "init" ]; then
  python3 -c "
import json
from datetime import datetime
log = {
    'date': '${DATE}',
    'session_start': datetime.now().isoformat(),
    'steps': {},
    'action_cards': [],
    'state_checksums': {
        'session_start': {},
        'session_end': {},
        'drift_detected': []
    },
    'verification_queue': [],
    'gates_checked': {},
    'audit': None
}
with open('${LOG_FILE}', 'w') as f:
    json.dump(log, f, indent=2)
print('Created: ${LOG_FILE}')
"
  exit 0
fi

# ADD-CARD: Add an action card
if [ "$2" = "add-card" ]; then
  CARD_ID="$3"
  CARD_TYPE="$4"
  CARD_TARGET="$5"
  CARD_TEXT="$6"
  CARD_URL="${7:-}"
  python3 -c "
import json
from datetime import datetime
with open('${LOG_FILE}') as f:
    log = json.load(f)
card = {
    'id': '''${CARD_ID}''',
    'type': '''${CARD_TYPE}''',
    'target': '''${CARD_TARGET}''',
    'draft_text': '''${CARD_TEXT}'''[:200],
    'url': '''${CARD_URL}''' if '''${CARD_URL}''' else None,
    'card_delivered': False,
    'founder_confirmed': False,
    'logged_to': []
}
log['action_cards'].append(card)
with open('${LOG_FILE}', 'w') as f:
    json.dump(log, f, indent=2)
print('Added card: ${CARD_ID} (${CARD_TYPE}) -> ${CARD_TARGET}')
"
  exit 0
fi

# DELIVER-CARDS: Mark all undelivered cards as delivered (run after Step 11)
if [ "$2" = "deliver-cards" ]; then
  python3 -c "
import json
with open('${LOG_FILE}') as f:
    log = json.load(f)
count = 0
for card in log['action_cards']:
    if not card.get('card_delivered'):
        card['card_delivered'] = True
        count += 1
with open('${LOG_FILE}', 'w') as f:
    json.dump(log, f, indent=2)
print(f'Marked {count} cards as delivered')
"
  exit 0
fi

# GATE-CHECK: Log a gate check
if [ "$2" = "gate-check" ]; then
  GATE_STEP="$3"
  ALL_PRIOR="$4"
  MISSING="$5"
  python3 -c "
import json
with open('${LOG_FILE}') as f:
    log = json.load(f)
missing_list = [s.strip() for s in '''${MISSING}'''.split(',') if s.strip()] if '''${MISSING}''' else []
log['gates_checked']['${GATE_STEP}'] = {
    'checked': True,
    'all_prior_done': '''${ALL_PRIOR}''' == 'true',
    'missing': missing_list
}
with open('${LOG_FILE}', 'w') as f:
    json.dump(log, f, indent=2)
status = 'PASS' if '''${ALL_PRIOR}''' == 'true' else 'FAIL'
print(f'Gate ${GATE_STEP}: [{status}]' + (f' Missing: {missing_list}' if missing_list else ''))
"
  exit 0
fi

# CHECKSUM-START: Record session-start checksum
if [ "$2" = "checksum-start" ]; then
  KEY="$3"
  VALUE="$4"
  python3 -c "
import json
with open('${LOG_FILE}') as f:
    log = json.load(f)
log['state_checksums']['session_start']['''${KEY}'''] = '''${VALUE}'''
with open('${LOG_FILE}', 'w') as f:
    json.dump(log, f, indent=2)
print('Checksum start: ${KEY} = ${VALUE}')
"
  exit 0
fi

# CHECKSUM-END: Record session-end checksum
if [ "$2" = "checksum-end" ]; then
  KEY="$3"
  VALUE="$4"
  python3 -c "
import json
with open('${LOG_FILE}') as f:
    log = json.load(f)
log['state_checksums']['session_end']['''${KEY}'''] = '''${VALUE}'''
# Check for drift
start_val = log['state_checksums']['session_start'].get('''${KEY}''')
if start_val is not None and start_val != '''${VALUE}''':
    drift_msg = f'${KEY}: {start_val} -> ${VALUE}'
    if drift_msg not in log['state_checksums']['drift_detected']:
        log['state_checksums']['drift_detected'].append(drift_msg)
with open('${LOG_FILE}', 'w') as f:
    json.dump(log, f, indent=2)
print('Checksum end: ${KEY} = ${VALUE}')
"
  exit 0
fi

# VERIFY: Add/update verification queue entry
if [ "$2" = "verify" ]; then
  CLAIM="$3"
  SOURCE="$4"
  VERIFIED="$5"
  RESULT="$6"
  python3 -c "
import json
with open('${LOG_FILE}') as f:
    log = json.load(f)
entry = {
    'claim': '''${CLAIM}''',
    'source_file': '''${SOURCE}''',
    'verified': '''${VERIFIED}''' == 'true',
    'verification_method': '',
    'result': '''${RESULT}''' if '''${RESULT}''' else None
}
# Update existing or append new
found = False
for i, v in enumerate(log['verification_queue']):
    if v['claim'] == '''${CLAIM}''':
        log['verification_queue'][i] = entry
        found = True
        break
if not found:
    log['verification_queue'].append(entry)
with open('${LOG_FILE}', 'w') as f:
    json.dump(log, f, indent=2)
status = 'VERIFIED' if '''${VERIFIED}''' == 'true' else 'UNVERIFIED'
print(f'Verification: [{status}] ${CLAIM}')
"
  exit 0
fi

# DEFAULT: Log a step
STEP_ID="$2"
STATUS="$3"
RESULT="$4"
ERROR="${5:-}"

if [ -z "$STEP_ID" ] || [ -z "$STATUS" ]; then
  echo "Usage: bash q-system/.q-system/log-step.sh <date> <step_id> <status> <result> [error]" >&2
  exit 1
fi

python3 -c "
import json
from datetime import datetime
with open('${LOG_FILE}') as f:
    log = json.load(f)
log['steps']['${STEP_ID}'] = {
    'status': '${STATUS}',
    'timestamp': datetime.now().isoformat(),
    'result': '''${RESULT}''' if '''${RESULT}''' else None,
    'error': '''${ERROR}''' if '''${ERROR}''' else None
}
with open('${LOG_FILE}', 'w') as f:
    json.dump(log, f, indent=2)
icon = {'done': 'OK', 'failed': 'FAIL', 'skipped': 'SKIP', 'partial': 'WARN'}.get('${STATUS}', '??')
print(f'[{icon}] ${STEP_ID}: ${STATUS}' + (f' - ${RESULT}' if '''${RESULT}''' else '') + (f' (${ERROR})' if '''${ERROR}''' else ''))
"
