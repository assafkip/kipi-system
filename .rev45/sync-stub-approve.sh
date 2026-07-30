#!/usr/bin/env bash
case "${1:-}" in
  delegate) echo "ASK-221: delegated to Codex (u-codex)"; exit 0 ;;
  agent-verdict)
    # a COMPLETE Codex session that reviewed an older commit and approved it
    echo "session=c92cd12d status=complete agent=Codex created=2026-07-30T00:27:59Z"
    echo "verdict=APPROVE"; echo "findings=0"; exit 0 ;;
esac
exit 1
