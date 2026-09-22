---
id: tests-are-triggered-they-never-trigger
kind: pattern
title: Tests are triggered; they never trigger
date: 2026-09-02
---

The trigger inventory closed over every script named inside a triggered script. The capability manifest triggers test files, and a test that exercises the upstream push named it, so the push read as triggered in production. Docstrings did the same for a library. The closure now stops at test files and strips comments and Python docstrings before reading a script for names. prd-lessons-rail-and-up-rail issues 6 and 8.

How to apply:

1. When deriving "what runs X" from text, exclude tests and prose: a test invoking a script is not a production trigger, and a docstring mentioning it is not a call.
2. Read the live output before trusting the derivation: the first run listed 98 dead stages and 45 of them were test files and MCP-served tools the surfaces did not cover.
