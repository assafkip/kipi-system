#!/bin/bash
# ASK-191 local reproduction of the CI `validate` step 7 invocation.
cd /Users/assafkipnis/.config/kipi/worktrees/ask-191
export CI=true
export CAPABILITY_GATE_SKIP=1
python3 validate-separation.py 1
echo "VALIDATE_EXIT=$?"
