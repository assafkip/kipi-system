# Kipi System — Development Guide

## Architecture

This is a Claude Code plugin. Three layers:

1. **MCP Server** (`kipi-mcp/`) — Python, 66 tools. Deterministic data operations. Zero LLM tokens.
2. **Agent Pipeline** (`q-system/agent-pipeline/agents/`) — 30 markdown agent prompts spawned by the orchestrator.
3. **Skills** (`skills/`) — User-facing slash commands that orchestrate MCP tools + agents.

Data flows: External sources → `kipi_harvest` (Python) → SQLite → agents read via `kipi_get_harvest` → agents write via `kipi_store_harvest` → `07-synthesize` (opus) → schedule JSON → HTML.

### Databases (3 separate SQLite files)

- `harvest.db` — transient harvest data (7-day TTL), agent metrics, session handoffs, source cursors, Apify budget, Notion write queue
- `metrics.db` — permanent business data (content performance, outreach logs, behavioral signals, copy edits, daily metrics, A/B tests)
- `system.db` — operational state (loops with escalation tracking)

### Key Patterns

- **HarvestStore** (`harvest_store.py`): `_connect()` with WAL mode + Row factory + foreign_keys, try/finally conn.close(). All methods return dicts.
- **Source Registry** (`source_registry.py`): YAML configs in `kipi-mcp/sources/`, Pydantic models, variable resolution via `${VAR}`.
- **Agent naming**: harvest sources use plain names (`linkedin-feed`), agent outputs use `agent:` prefix (`agent:signals-content`).

## Development

### Setup

```bash
cd kipi-mcp
uv sync
uv run pytest tests/ --ignore=tests/test_git_ops.py -v
```

### Testing

**TDD is mandatory.** Write tests first, then implementation.

- Tests in `kipi-mcp/tests/`. Run: `uv run pytest tests/ --ignore=tests/test_git_ops.py -v`
- Use `tmp_path` fixtures for all file/DB operations. Never touch real data.
- Follow patterns in `test_harvest_store.py` and `test_morning_init.py`.
- Mock all external HTTP calls (httpx MockTransport, apify-client mocks).
- After any Python change: run the full test suite before committing.
- After adding MCP tools: update `EXPECTED_TOOLS` list in `test_server_integration.py`.

### Code Standards

- Follow existing patterns exactly. Read `metrics_store.py` or `harvest_store.py` before writing new store code.
- SQL: always use parameterized queries (`?` placeholders). Never concatenate user input into SQL. Whitelist column names if dynamic.
- No comments unless the logic is non-obvious. No docstrings on private helpers.
- No speculative abstractions. Three similar lines > premature abstraction.
- Security: validate file paths with `.resolve()` + `.relative_to()`. Sanitize HTML via `sanitizeHTML()` in the template.

### Agent Markdown Files

- YAML frontmatter: `name`, `description`, `model` (haiku/sonnet/opus), `maxTurns`
- `## Reads` section: list all data sources (harvest or agent: prefixed)
- `## Writes` section: `kipi_store_harvest("agent:name", results_json, "{{RUN_ID}}")`
- Template variables: `{{DATE}}`, `{{RUN_ID}}`, `{{CONFIG_DIR}}`, `{{DATA_DIR}}`, `{{STATE_DIR}}`, `{{AGENTS_DIR}}`, `{{QROOT}}`
- Copy-generating agents MUST reference `founder-voice/SKILL.md` and call `kipi_voice_lint` before writing output.

### Source YAML Configs

- Location: `kipi-mcp/sources/`
- Schema: see `source_registry.py` SourceManifest model
- Every YAML needs `schema_version: 1`
- Methods: `http`, `apify`, `mcp`, `chrome`, `local`
- Chrome sources need a companion `.md` file in `sources/chrome/`

### Adding a New Data Source

1. Create `kipi-mcp/sources/my-source.yaml`
2. If chrome: create `kipi-mcp/sources/chrome/my-source.md`
3. Done. No code changes needed. Harvester picks it up automatically.

### Adding a New MCP Tool

1. Add method to appropriate store class (`harvest_store.py`, `metrics_store.py`, etc.)
2. Add test in corresponding test file
3. Add `@mcp.tool()` function in `server.py` following existing pattern (try/except/json.dumps/ToolError)
4. Add tool name to `EXPECTED_TOOLS` in `test_server_integration.py`
5. Run full test suite

### Adding a New Agent

1. Create `q-system/agent-pipeline/agents/NN-agent-name.md` with YAML frontmatter
2. Add to correct phase in `step-orchestrator.md`
3. Add to model allocation list in orchestrator
4. If it generates copy: add founder-voice reference + kipi_voice_lint call

## Commit Standards

- Commit message: imperative mood, explain WHY not just WHAT
- Co-author line: `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`
- Never skip hooks (`--no-verify`)
- Stage specific files, not `git add -A`
- Run tests before every commit

## What NOT to Do

- All data goes through SQLite.
- Don't hardcode API keys or tokens. Use `${VAR}` in YAMLs, `os.environ` in Python.
- Don't use f-strings for SQL queries.
- Don't use innerHTML without sanitizeHTML() in the HTML template.
- Don't add agents that are pure data-pull. Use the harvest layer (source YAMLs + Python executors).
- Don't load full canonical files in agents. Use `kipi_canonical_digest` or `kipi_get_harvest`.
