---
id: verify-against-the-installed-clone-the-server-actually-starts
kind: pattern
title: Verify against the installed clone the server actually starts, not the repo working tree
date: 2026-08-23
---

A branch fix is invisible to the live MCP tool, and no amount of merging inside the repo moves the running server by itself. Two load-path facts, measured 2026-08-22 (sp-eea17567, sp-d120853a), hit repeatedly in one session:

1. The kipi MCP server runs `uv --directory CLAUDE_PLUGIN_ROOT/kipi-mcp run kipi-mcp`, and CLAUDE_PLUGIN_ROOT is the marketplace clone under `~/.claude/plugins/marketplaces/kipi/`, whose HEAD tracks `origin/main` -- not any feature branch. `grep -c _state_root` returned 0 there while the repo working copy returned 3: same name, different code.

2. The plugin cache is VERSION-KEYED (`~/.claude/plugins/cache/kipi/kipi-core/<VERSION>/`) and the version is pinned per session. Marketplace update moved the clone's content but not the running server; killing the server process did not move it either. A full Claude Code restart is what moved it onto the new version.

Why it matters: a green verdict claimed against the repo tree says nothing about what users of the live tool will see, and a fix "verified" one step ahead of its evidence was the recurring defect of this whole thread. The inverse error is just as real -- an instance `plugins/` directory is a `kipi update` DESTINATION that gets overwritten, so wiring a change into an instance copy proves nothing either (the gap-class checklist that sat inert for weeks).

How to apply:

1. To verify behavior the live tool would exhibit, construct the check inside `~/.claude/plugins/cache/kipi/kipi-core/<version>/` (or read THAT tree), never the repo working tree.
2. A branch cannot be verified live at all until it is merged to main AND pushed AND the marketplace clone refreshed AND Claude Code restarted. Say which of those steps has NOT happened; an unverifiable claim must be labeled as such, not softened.
3. Plugin version bumps exist so deployed clones can tell copies apart; bump on every behavioral change to a plugin.
