#!/bin/bash
# apify-run.sh - Reusable Apify REST API wrapper
# Handles the data.{} nesting that breaks every morning
#
# Usage:
#   bash apify-run.sh <actor_id> '<input_json>' [max_wait_seconds]
#
# Examples:
#   bash apify-run.sh "supreme_coder~linkedin-post" '{"urls":["https://..."],"deepScrape":false,"maxItems":10}' 120
#   bash apify-run.sh "trudax~reddit-scraper-lite" '{"startUrls":[{"url":"https://..."}],"maxItems":10}' 120
#   bash apify-run.sh "apidojo~tweet-scraper" '{"handles":["BushidoToken"],"maxItems":10,"mode":"profile"}' 120
#
# Output: JSON array of dataset items to stdout
# Exit codes: 0=success, 1=run failed, 2=no results

set -euo pipefail

ACTOR_ID="$1"
INPUT_JSON="$2"
MAX_WAIT="${3:-120}"

# Token from environment - MUST be set via settings.json env vars or shell export
TOKEN="${APIFY_TOKEN:?ERROR: APIFY_TOKEN not set. Add it to .claude/settings.local.json under env.}"

# Step 1: Start the actor run and wait for completion
# CRITICAL: Response is wrapped in {"data": {...}} - always extract .data first
RUN_RESPONSE=$(curl -s -X POST \
  "https://api.apify.com/v2/acts/${ACTOR_ID}/runs?token=${TOKEN}&waitForFinish=${MAX_WAIT}" \
  -H "Content-Type: application/json" \
  -d "${INPUT_JSON}" 2>&1)

# Extract from data wrapper
STATUS=$(echo "$RUN_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('data',{}).get('status','UNKNOWN'))" 2>/dev/null || echo "PARSE_ERROR")
DATASET_ID=$(echo "$RUN_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('data',{}).get('defaultDatasetId',''))" 2>/dev/null || echo "")

if [ "$STATUS" != "SUCCEEDED" ]; then
  echo "APIFY_ERROR: Actor ${ACTOR_ID} returned status: ${STATUS}" >&2
  # Print raw response for debugging (truncated)
  echo "$RUN_RESPONSE" | head -c 500 >&2
  exit 1
fi

if [ -z "$DATASET_ID" ]; then
  echo "APIFY_ERROR: No dataset ID returned for ${ACTOR_ID}" >&2
  exit 1
fi

# Step 2: Fetch dataset items
ITEMS=$(curl -s "https://api.apify.com/v2/datasets/${DATASET_ID}/items?token=${TOKEN}" 2>&1)

# Validate it's a JSON array
ITEM_COUNT=$(echo "$ITEMS" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

if [ "$ITEM_COUNT" = "0" ]; then
  echo "[]"
  exit 2
fi

echo "$ITEMS"
exit 0
