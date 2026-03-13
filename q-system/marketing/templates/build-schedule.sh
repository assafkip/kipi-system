#!/bin/bash
# Build daily schedule HTML from JSON data + template
# Usage: ./build-schedule.sh <json-file> [output-file]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="$SCRIPT_DIR/daily-schedule-template.html"
JSON_FILE="$1"
OUTPUT_FILE="$2"

if [ -z "$JSON_FILE" ]; then
  echo "Usage: $0 <json-file> [output-file]" >&2
  exit 1
fi

if [ ! -f "$JSON_FILE" ]; then
  echo "Error: JSON file not found: $JSON_FILE" >&2
  exit 1
fi

if [ ! -f "$TEMPLATE" ]; then
  echo "Error: Template not found: $TEMPLATE" >&2
  exit 1
fi

python3 -c "
import json, sys

with open('$TEMPLATE') as f:
    template = f.read()

with open('$JSON_FILE') as f:
    data = json.load(f)

js_json = json.dumps(data, ensure_ascii=True)
result = template.replace('__SCHEDULE_DATA__', js_json)

output = '$OUTPUT_FILE'
if output:
    with open(output, 'w') as f:
        f.write(result)
    print('Built: ' + output)
else:
    print(result)
"
