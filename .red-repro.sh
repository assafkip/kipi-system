#!/usr/bin/env bash
# Throwaway: run test-review-comment-body.sh with a HOME that holds no captured
# review, which is the CI runner's condition (the synthesized fixture path).
export HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.nohome"
mkdir -p "$HOME"
exec bash "$(dirname "${BASH_SOURCE[0]}")/q-system/.q-system/scripts/test/test-review-comment-body.sh"
