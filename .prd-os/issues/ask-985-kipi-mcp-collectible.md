---
id: ask-985-kipi-mcp-collectible
title: kipi-mcp suite collects and runs green under its own runtime (sp-dcd84af1)
status: closed
priority: p1
allowed_files:
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/registry.py
  - plugins/kipi-core/kipi-mcp/tests/test_registry.py
  - plugins/kipi-core/.claude-plugin/plugin.json
disallowed_files: []
required_checks:
  - bash -c 'cd plugins/kipi-core/kipi-mcp && uv run python -m pytest -q tests/'
required_reviews: []
deliverables_count: 3
---
<!-- generated-by: prd_split.py prd=prd-manual finding=sp-dcd84af1 at=2026-08-23T08:30:00Z -->

# kipi-mcp suite collects and runs green under its own runtime

## Context

Five test modules ImportError at collection under bare homebrew python
(ModuleNotFoundError: yaml / feedparser), so they passed by not running
whenever anyone invoked the suite as a whole (sp-dcd84af1). Every one of those
deps is ALREADY a declared main dependency in pyproject.toml; the server itself
runs through uv. The defect is the invocation, not the manifest.

Collecting via uv immediately surfaced a real bug the collection error had
been hiding: `RegistryManager.list_excluded()` bare-indexes `"excluded"`, the
live instance-registry.json drifted to a shape without that key, and the live
`kipi://instances` MCP resource crashes on this box today. Fixed at the
single-writer chokepoint (`load()` setdefaults known keys), pinned by a test
whose RED was shown first.

## Evidence

RED (collection), before any edit:

```
$ cd plugins/kipi-core/kipi-mcp && PYTHONPATH=src python3 -m pytest -q tests/
ERROR tests/test_competitive_intel.py ... 5 errors during collection
```

GREEN via the project runtime:

```
$ uv run python -m pytest -q tests/
706 passed, 1 failed -> after registry fix: all green
```

RED (registry KeyError), before the fix:

```
$ uv run python -m pytest -q tests/test_registry.py::TestPartialRegistryShape
KeyError: 'excluded'  (src/kipi_mcp/registry.py:25)
```

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] RegistryManager.load() tolerates schema drift on read (setdefault at the chokepoint), scar-commented
- [x] Test pinning the drifted live shape, RED shown before the fix
- [x] Full suite collects and passes under `uv run` (zero collection errors)
