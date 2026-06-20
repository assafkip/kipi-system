# Definition of Done: Fully Wired (ENFORCED)

No implementation task is "done" until every change is connected end-to-end.
This repo's value is that its parts compose; a new skill/command/hook/agent
that isn't connected to the rest is dead weight.

Before declaring done, confirm (evidence required, not assumed):
- Any new skill has a trigger (auto-invoke rule, command, or discoverable description)
- Any new high-stakes auto-invoked skill has a trigger-eval fixture in `q-system/.q-system/skill-evals/` (run advisory/periodic via `skill-trigger-eval.py`; never a blocking gate)
- Any new slash command is registered (listed in CLAUDE.md commands and/or `plugin.json`)
- Any new hook script is referenced from `settings.json`, is executable, and uses the correct exit-code contract
- Any new MCP tool is registered in the server and appears in the plugin description
- Any new agent has a current (non-deprecated) model ID, explicit tool allowlist, and is invoked by the orchestrator
- Any new bus file has both a producer and a consumer, and a schema in `agent-pipeline/schemas/`
- Any new canonical file is in `ripple-graph.json` and the digest is regenerated
- Any new rule is auto-loaded or imported via `@` in CLAUDE.md
- Any new Python harness has a caller and resolves QROOT correctly
- Skeleton-vs-instance placement is correct; `kipi update --dry` confirms propagation if this is `kipi-system`
- The repo's registered bypass gates are green:
  `python3 plugins/prd-os/scripts/prd_runner.py gates run` exits 0 (the
  permanent "no bypass remains" re-proof — issue closeout auto-registers
  every bypass_check into `.prd-os/gates.jsonl`; gates only grow). Skip
  this bullet only if the repo has never run `/prd-os-init` (no `.prd-os/`).

When finished, run `/wiring-check` and produce the WIRING REPORT. "I think it
works" is not done. "I ran X, got Y" is done.

## Propagation gotcha
Root-level `CLAUDE.md` does NOT sync to instances. Only `q-system/CLAUDE.md`,
`.claude/rules/*.md`, `.claude/agents/*.md`, `.claude/output-styles/*.md`, and
`plugins/*/` propagate via `kipi update`. If a rule must reach every instance,
it belongs in `.claude/rules/` (like this file).
