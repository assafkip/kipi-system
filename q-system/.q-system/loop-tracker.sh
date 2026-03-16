#!/bin/bash
# Loop Tracker - closes loops that AUDHD opens
# Every outbound action (DM, email, comment, connection request) opens a loop.
# The morning routine reads open loops and forces follow-up or explicit close.
#
# Usage:
#   bash q-system/.q-system/loop-tracker.sh open <type> <target> <context> [notion_id] [card_id] [follow_up_text]
#   bash q-system/.q-system/loop-tracker.sh close <loop_id> <reason> <closed_by>
#   bash q-system/.q-system/loop-tracker.sh escalate
#   bash q-system/.q-system/loop-tracker.sh list [min_level]
#   bash q-system/.q-system/loop-tracker.sh force-close <loop_id> <park|kill>
#   bash q-system/.q-system/loop-tracker.sh stats
#   bash q-system/.q-system/loop-tracker.sh prune [days]
#   bash q-system/.q-system/loop-tracker.sh touch <loop_id>
#
# Loop types: dm_sent, email_sent, materials_sent, comment_posted,
#             action_created, debrief_next_step, dp_offer_sent,
#             connection_request_sent, lead_sourced

set -e

LOOP_FILE="q-system/output/open-loops.json"

# Create file if it doesn't exist
if [ ! -f "$LOOP_FILE" ]; then
  echo '{"schema_version": 1, "loops": []}' > "$LOOP_FILE"
fi

CMD="$1"

case "$CMD" in

  open)
    TYPE="$2"
    TARGET="$3"
    CONTEXT="$4"
    NOTION_ID="${5:-}"
    CARD_ID="${6:-}"
    FOLLOW_UP="${7:-}"
    python3 -c "
import json
from datetime import datetime

with open('${LOOP_FILE}') as f:
    data = json.load(f)

target = '''${TARGET}'''
loop_type = '''${TYPE}'''

# Check for duplicate: same target + type already open
for loop in data['loops']:
    if loop['target'] == target and loop['type'] == loop_type and loop['status'] == 'open':
        loop['touch_count'] = loop.get('touch_count', 1) + 1
        if '''${FOLLOW_UP}''':
            loop['follow_up_text'] = '''${FOLLOW_UP}'''
        with open('${LOOP_FILE}', 'w') as f:
            json.dump(data, f, indent=2)
        print(f'Loop updated: {loop[\"id\"]} touch #{loop[\"touch_count\"]} -> {target}')
        exit(0)

# Generate ID
today = datetime.now().strftime('%Y-%m-%d')
existing_today = [l for l in data['loops'] if l['id'].startswith(f'L-{today}')]
counter = len(existing_today) + 1
loop_id = f'L-{today}-{counter:03d}'

# Determine escalation thresholds based on target type
# High-value contacts get longer windows (set via notion type check later)
loop = {
    'id': loop_id,
    'type': loop_type,
    'target': target,
    'target_notion_id': '''${NOTION_ID}''' or None,
    'opened': today,
    'opened_by': 'morning_routine',
    'action_card_id': '''${CARD_ID}''' or None,
    'context': '''${CONTEXT}''',
    'channel': loop_type.replace('_sent', '').replace('_posted', '').replace('_created', '').replace('_sourced', ''),
    'touch_count': 1,
    'follow_up_text': '''${FOLLOW_UP}''' or None,
    'escalation_level': 0,
    'last_escalated': None,
    'status': 'open',
    'closed': None,
    'closed_by': None,
    'closed_reason': None
}

data['loops'].append(loop)
with open('${LOOP_FILE}', 'w') as f:
    json.dump(data, f, indent=2)
print(f'Loop opened: {loop_id} ({loop_type}) -> {target}')
"
    ;;

  close)
    LOOP_ID="$2"
    REASON="$3"
    CLOSED_BY="$4"
    python3 -c "
import json
from datetime import datetime

with open('${LOOP_FILE}') as f:
    data = json.load(f)

found = False
for loop in data['loops']:
    if loop['id'] == '${LOOP_ID}' and loop['status'] == 'open':
        loop['status'] = 'closed'
        loop['closed'] = datetime.now().strftime('%Y-%m-%d')
        loop['closed_by'] = '${CLOSED_BY}'
        loop['closed_reason'] = '''${REASON}'''
        found = True
        break

if found:
    with open('${LOOP_FILE}', 'w') as f:
        json.dump(data, f, indent=2)
    print(f'Loop closed: ${LOOP_ID} ({CLOSED_BY}: ${REASON})')
else:
    print(f'Loop not found or already closed: ${LOOP_ID}')
"
    ;;

  force-close)
    LOOP_ID="$2"
    ACTION="$3"  # park or kill
    python3 -c "
import json
from datetime import datetime

with open('${LOOP_FILE}') as f:
    data = json.load(f)

for loop in data['loops']:
    if loop['id'] == '${LOOP_ID}' and loop['status'] == 'open':
        loop['status'] = '${ACTION}ed'
        loop['closed'] = datetime.now().strftime('%Y-%m-%d')
        loop['closed_by'] = 'founder'
        loop['closed_reason'] = '${ACTION}'
        break

with open('${LOOP_FILE}', 'w') as f:
    json.dump(data, f, indent=2)
print(f'Loop force-closed: ${LOOP_ID} -> ${ACTION}')
"
    ;;

  escalate)
    python3 -c "
import json
from datetime import datetime

with open('${LOOP_FILE}') as f:
    data = json.load(f)

today = datetime.now()
counts = {0: 0, 1: 0, 2: 0, 3: 0}

for loop in data['loops']:
    if loop['status'] != 'open':
        continue
    opened = datetime.strptime(loop['opened'], '%Y-%m-%d')
    age = (today - opened).days

    # Standard thresholds
    if age >= 14:
        new_level = 3
    elif age >= 7:
        new_level = 2
    elif age >= 3:
        new_level = 1
    else:
        new_level = 0

    if new_level > loop.get('escalation_level', 0):
        loop['escalation_level'] = new_level
        loop['last_escalated'] = today.strftime('%Y-%m-%d')

    counts[loop['escalation_level']] += 1

with open('${LOOP_FILE}', 'w') as f:
    json.dump(data, f, indent=2)

total = sum(counts.values())
print(f'Escalated: {total} open loops (L0:{counts[0]} L1:{counts[1]} L2:{counts[2]} L3:{counts[3]})')
"
    ;;

  touch)
    LOOP_ID="$2"
    python3 -c "
import json

with open('${LOOP_FILE}') as f:
    data = json.load(f)

for loop in data['loops']:
    if loop['id'] == '${LOOP_ID}' and loop['status'] == 'open':
        loop['touch_count'] = loop.get('touch_count', 1) + 1
        break

with open('${LOOP_FILE}', 'w') as f:
    json.dump(data, f, indent=2)
print(f'Touch added: ${LOOP_ID}')
"
    ;;

  list)
    MIN_LEVEL="${2:-0}"
    python3 -c "
import json
from datetime import datetime

with open('${LOOP_FILE}') as f:
    data = json.load(f)

today = datetime.now()
for loop in sorted(data['loops'], key=lambda x: x.get('escalation_level', 0), reverse=True):
    if loop['status'] != 'open':
        continue
    if loop.get('escalation_level', 0) < ${MIN_LEVEL}:
        continue
    opened = datetime.strptime(loop['opened'], '%Y-%m-%d')
    age = (today - opened).days
    level = loop.get('escalation_level', 0)
    level_label = ['NEW', 'WARM', 'HOT', 'FORCE'][level]
    print(f'  [{level_label}] {loop[\"id\"]} | {loop[\"type\"]} | {loop[\"target\"]} | {age}d | touches:{loop.get(\"touch_count\",1)} | {loop[\"context\"][:60]}')
"
    ;;

  stats)
    python3 -c "
import json
from datetime import datetime

with open('${LOOP_FILE}') as f:
    data = json.load(f)

today = datetime.now()
open_loops = [l for l in data['loops'] if l['status'] == 'open']
closed_today = [l for l in data['loops'] if l.get('closed') == today.strftime('%Y-%m-%d')]
counts = {0: 0, 1: 0, 2: 0, 3: 0}
oldest = 0

for loop in open_loops:
    level = loop.get('escalation_level', 0)
    counts[level] = counts.get(level, 0) + 1
    opened = datetime.strptime(loop['opened'], '%Y-%m-%d')
    age = (today - opened).days
    oldest = max(oldest, age)

auto_closed = len([l for l in closed_today if l.get('closed_by', '').startswith('auto')])
manual_closed = len([l for l in closed_today if l.get('closed_by') == 'founder'])

print(f'Open: {len(open_loops)} | Closed today: {len(closed_today)} ({auto_closed} auto, {manual_closed} manual)')
print(f'L0:{counts[0]} L1:{counts[1]} L2:{counts[2]} L3:{counts[3]} | Oldest: {oldest}d')
"
    ;;

  prune)
    DAYS="${2:-30}"
    python3 -c "
import json
from datetime import datetime, timedelta

with open('${LOOP_FILE}') as f:
    data = json.load(f)

cutoff = (datetime.now() - timedelta(days=${DAYS})).strftime('%Y-%m-%d')
before = len(data['loops'])
data['loops'] = [l for l in data['loops'] if l['status'] == 'open' or (l.get('closed', '9999') > cutoff)]
after = len(data['loops'])

with open('${LOOP_FILE}', 'w') as f:
    json.dump(data, f, indent=2)
print(f'Pruned: {before - after} loops older than ${DAYS} days. {after} remaining.')
"
    ;;

  *)
    echo "Usage: bash q-system/.q-system/loop-tracker.sh <open|close|force-close|escalate|touch|list|stats|prune> [args...]" >&2
    exit 1
    ;;
esac
