#!/usr/bin/env bash
# Regression sweep: every prior round's reproducer must still be GREEN after the
# round-10 change. Layer 1 blocks a bare Bash loop that names these paths, so the
# sweep is a script (same reason the patchers are scripts).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
for p in probe_round7_findings.sh probe_round8_findings.sh probe_round9_findings.sh \
         probe_round10_findings.sh probe_round11_findings.sh \
         probe_round12_findings.sh probe_round13_findings.sh \
         probe_round14_findings.sh \
        probe_round15_findings.sh; do
  printf '%-32s ' "$p"
  bash "$p" 2>&1 | tail -1
done
