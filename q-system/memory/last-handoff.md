# Session handoff, night of Aug 22 [verified: date -u]. READ THIS FIRST.

## THE ONE THING TO DO IN THIS SESSION

The founder just restarted Claude Code specifically so the kipi MCP server would
reload. Before anything else, run the MCP tool `kipi_canonical_digest` and show
him the raw output.

**If it returns real data** (a populated `decisions` list, empty `warnings`, and
no "not found" messages) it worked. Then run:

```bash
cd ~/projects/kipi-system
R=plugins/prd-os/scripts/prd_runner.py
python3 $R spillover resolve sp-64c9fdfb --resolution-commit de2e4624
python3 $R spillover resolve sp-b2c21bdc --resolution-commit de2e4624
python3 $R spillover resolve sp-88c00ce2 --resolution-commit de2e4624
```

Tell the founder it worked, in one line. He has been at this since morning.

**If it STILL returns** `"talk-tracks.md not found"` with an empty decisions
list, the server is still on the old plugin version. Diagnose in this order:

```bash
ps aux | grep "[k]ipi-mcp" | grep -o "kipi-core/[0-9.]*"
ls ~/.claude/plugins/cache/kipi/kipi-core/
```

- Fixed plugin version, the one to look for: `1.7.19` [provenance: imported]
- Stale version the session was pinned to: `1.5.15` [provenance: imported]
- Everything already tried is in spillover `sp-d120853a`. Read it before
  repeating any of it.

## WHY (context you do not have)

Founder asked whether Obsidian plus the Obsidian Copilot plugin would fix "Claude
losing context" in his projects. It would not. The real defect:
`kipi_canonical_digest` resolved `canonical_dir` to an EMPTY plugin-data
directory, so it returned all-files-not-found on every instance, and agents fell
back to reading raw canonical files instead.

Measured across founder-typed messages only (`promptSource` in typed or queued,
excluding headless prompts, hook injections and subagents), by mining
`~/.claude/projects/*/*.jsonl` with a python classifier whose hits were then
hand-read to check the regex was not lying:

- consulting: `1,345` msgs, `14` "read the canonical files", `7` "it's in the file" [verified: python classifier over the jsonl transcripts]
- kipi-system: `770` msgs, `0` of either pattern [verified: same classifier, same run]

Consulting has three diverged canonical trees with identical filenames
[verified: `git log -1 --format=%ad -- <path>` on each]:

- `q-consult/canonical` is live, last commit `2026-08-20` [verified: git log]
- `q-system/canonical` is frozen template stubs, last commit `2026-07-01` [verified: git log]
- `plugins/kipi-core/kipi-mcp/canonical` frozen, last commit `2026-06-10` [verified: git log]

## SHIPPED AND MERGED

Merge commit `de2e4624` on `origin/main`, from PR #240, squashed [verified: gh pr view 240 --json state,mergeCommit].

`_state_root` occurrences in main's `paths.py`, was zero this morning: `4` [verified: git show origin/main:plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py | grep -c _state_root].

Four Codex review rounds, every finding in Sana's own diff, each reproduced red
before being touched [provenance: observed, read each verdict on PR #240]:

1. cross-instance leak: a shared `active-instance` marker outranked
   `CLAUDE_PROJECT_DIR`, so a restarted session could read another project's
   canonical. Plus a fail-closed resolver silently returning nonexistent
   directories for four real registered instances.
2. a swallowed resolution error that let phase-1 verification pass with the
   detector disabled
3. duplicate registry PATHS unguarded, though names already were
4. APPROVE WITH NITS

Proven under the deployed configuration with nothing hand-fed: instance
`ASK_AI_consultant` resolves to `~/projects/consulting/q-consult/canonical`,
naming `RULE-2026-08-18-A` [verified: PYTHONPATH=... python3 -c over KipiPaths + canonical_digest].

Registry-wide resolver audit: `21` resolve, `4` raise PathContractError all with kind `no-canonical`, `0` silently wrong [verified: python3 loop over instance-registry.json].

## STILL OPEN

Local `main` is `1` ahead and `2` behind origin [verified: git rev-list --count]. Sana owns this, NOT the founder. It carries a stale `status: idea` PRD draft; a pull or rebase, never a reset.

Captured and deliberately untouched:

- `sp-d120853a` session-pinned plugin cache
- `sp-ee4d6ece` duplicate paths not rejected at registry WRITE time
- `sp-eea17567` a branch fix is invisible to the live MCP tool, because the
  server loads a clone that tracks main
- `sp-f7476ec8` `com.kipi.dispatch` is loaded but not running on this box [verified: launchctl print gui/501/com.kipi.dispatch]
- `sp-50db1764` bypass_check registered at close WITHOUT being run [provenance: imported, Sana's finding]
- `sp-e500bf34`, `sp-4c5a00f3`, `sp-1d4ca360`

Always-on instruction budget is `511` lines against a `300` target [verified: python3 q-system/.q-system/scripts/instruction-budget-audit.py]. The founder explicitly chose to keep this SEPARATE from the canonical work. Do not bundle it.

## HOW TO WORK WITH HIM RIGHT NOW

Sana is the human decision maker, informed by data. Route engineering calls to her
with the measurement attached, never to him [provenance: explicit_statement,
"sana has approval to be the human decision maker as long as its informed with
data"]. He corrected me for punting decisions upward, and for assuming he was done
for the day when it was not yet 5pm. Answer his questions; do not convert them
into permission asks.

The recurring defect this whole session, in the tooling AND in my reporting: **a
state claimed one step ahead of its evidence** [provenance: observed]. A green on
one commit reported as green on the next. A "red reproducer" that was actually a
collection error. A fix proven by hand-feeding `base_dir` rather than in the
config the server actually starts under. Quote the tool line and the sha next to
any verdict.
