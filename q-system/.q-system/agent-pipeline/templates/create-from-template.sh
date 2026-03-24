#!/bin/bash
# Create a new output folder from a template
# Usage: bash create-from-template.sh <template-name> <output-name>

set -euo pipefail

TEMPLATE_NAME="$1"
OUTPUT_NAME="$2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TEMPLATE_DIR="${SCRIPT_DIR}/${TEMPLATE_NAME}"
OUTPUT_DIR="${QROOT}/output/${OUTPUT_NAME}"

if [ ! -d "${TEMPLATE_DIR}" ]; then
  echo "Template not found: ${TEMPLATE_NAME}"
  echo "Available templates:"
  ls -d "${SCRIPT_DIR}"/*/ 2>/dev/null | xargs -I{} basename {} | grep -v "^$"
  exit 1
fi

if [ -d "${OUTPUT_DIR}" ]; then
  echo "Output already exists: ${OUTPUT_DIR}"
  exit 1
fi

cp -r "${TEMPLATE_DIR}" "${OUTPUT_DIR}"

# Replace date placeholder in all files
find "${OUTPUT_DIR}" -type f -name "*.md" -exec sed -i '' "s/{{DATE}}/$(date +%Y-%m-%d)/g" {} \;
find "${OUTPUT_DIR}" -type f -name "*.md" -exec sed -i '' "s/{{OUTPUT_NAME}}/${OUTPUT_NAME}/g" {} \;

echo "Created: ${OUTPUT_DIR}"
echo "Files:"
find "${OUTPUT_DIR}" -type f | sort
