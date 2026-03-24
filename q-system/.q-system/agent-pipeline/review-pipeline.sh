#!/bin/bash
# Content Review Multi-Pass Pipeline
#
# REFERENCE ONLY - do not run this script directly inside Claude Code.
# claude --print does not work as a subprocess inside Claude Code.
# Instead, use these pass definitions with Claude Code's Agent tool.
#
# 4 focused review passes, each checking ONE thing:
#
# Pass 1 - Voice:
#   Check for banned AI words, hedging language, emdashes, generic voice.
#   Reference: founder voice skill (e.g., .claude/skills/founder-voice/SKILL.md)
#
# Pass 2 - Guardrails:
#   Check against content guardrails (marketing/content-guardrails.md).
#   Misclassification, language bans, overclaiming, decision compliance.
#
# Pass 3 - Anti-AI Detection:
#   Check for uniform sentence length, formulaic structure, three-point default,
#   transition-word openers, bold-title bullet restatement, colon overuse.
#   Run perplexity, burstiness, and lexical diversity mental checks.
#
# Pass 4 - Actionability:
#   Check that founder-facing items have: copy-paste text, next physical action,
#   energy tag + time estimate, direct links. If not founder-facing, auto-PASS.
#   Reference: AUDHD executive function skill.
#
# Each pass outputs: PASS/FAIL, specific issues, suggested fixes.
#
# To run via Agent tool:
#   Spawn 4 sequential Sonnet agents, each reading the content file
#   and its specific rules file. Each writes a pass/fail result.

echo "This script is a reference for review pass definitions."
echo "Run review passes using Claude Code's Agent tool instead."
echo "See the comments in this file for pass specifications."
exit 0
