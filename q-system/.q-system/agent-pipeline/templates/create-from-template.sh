#!/bin/bash
# Create a new output folder from a template
# Usage: bash create-from-template.sh <template-name> <output-name>

set -euo pipefail

# Portable in-place sed (BSD/macOS requires `sed -i ''`, GNU/Linux requires `sed -i`)
sed_inplace() {
  if [[ "$(uname)" == "Darwin" ]]; then
    sed -i '' "$@"
  else
    sed -i "$@"
  fi
}

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
# Use while-read instead of find -exec so we can call the sed_inplace shell function
# (find -exec spawns a new process and can't see shell functions)
DATE_STR="$(date +%Y-%m-%d)"
while IFS= read -r -d '' f; do
  sed_inplace "s/{{DATE}}/$DATE_STR/g" "$f"
  sed_inplace "s/{{OUTPUT_NAME}}/${OUTPUT_NAME}/g" "$f"
done < <(find "${OUTPUT_DIR}" -type f -name "*.md" -print0)

echo "Created: ${OUTPUT_DIR}"
echo "Files:"
find "${OUTPUT_DIR}" -type f | sort
