#!/bin/bash
# Morning Routine Orchestrator - DEPRECATED
#
# The shell-based orchestrator doesn't work inside Claude Code.
# claude -p hangs when called as a subprocess.
#
# The orchestrator now lives as a step file at:
# .q-system/steps/step-orchestrator.md
#
# It uses Claude Code's native Agent tool to run sub-agents
# in parallel, communicating through bus/ JSON files on disk.
#
# To run: /q-morning (which reads step-orchestrator.md)
echo "This orchestrator is deprecated. Use /q-morning inside Claude Code."
exit 1
