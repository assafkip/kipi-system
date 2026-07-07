# HuntKit ↔ 4_points parity + auto-sync

**Date:** 2026-07-01
**What/why:** HuntKit (public plugin, github.com/assafkip/huntkit) is a frozen 2026-04-15 extraction of 4_points_consulting's investigation layer. 4_points kept evolving (content + kipi structural improvements). Bring HuntKit to parity and keep it there deterministically.

## Audit findings (2026-07-01)

| Layer | HuntKit (Apr 15) | 4_points (today) | Gap |
|-------|------------------|-------------------|-----|
| Commands | 22 q-*.md | same 22, 19 drifted (10-24 lines each) | refresh |
| Rules | 4 (evidence-capture, q-investigation, sycophancy, token-discipline) | same 4, all drifted (q-investigation +106 lines) | refresh |
| Skills | osint, structured-analysis | same + ~15 new files (check-collision.py, security-tools.json, findings-verify-hook.py, face-search-plan.md) | selective add |
| Hook wiring | token-guard.py shipped but UNWIRED (plugin.json has no hooks) | wired via settings.json PreToolUse; kipi plugins wire via hooks/hooks.json + ${CLAUDE_PLUGIN_ROOT} | **structural fix: add hooks/hooks.json** |
| Skill-paired hooks | none | osint has findings-verify-hook.py | port + wire |
| MCP servers | osint-infra, threat-intel | + tgspyder (q-investigate/tools/) | review for inclusion |
| Infra scripts | token-guard.py (-2 lines), tool-counter.sh (identical) | q-investigate/.q-system/ | trivial refresh |

**Never sync (exclusion list):** face-env/ (full Python venv w/ tensorflow), skills/osint/config/, __pycache__, invoices, cases/investigations, anything matching client names. face-search-plan.md + security-tools.json: review content before first publish.

**Parity scope decision:** parity = the investigation layer + plugin-native wiring. NOT making HuntKit a kipi instance (no founder OS, no voice/marketing/morning rules — those 26 extra rules in 4_points stay private).

## Approach (the pick)

HuntKit becomes a **build artifact**: a manifest-driven build script assembles it from 4_points. Re-running the build = parity, forever. Options considered: (a) build script + manifest (pick), (b) rsync allowlist only (no path/wiring transforms), (c) git subtree/submodule (can't scrub or transform).

1. `4_points_consulting/scripts/sync-huntkit.sh` (repo ROOT, not q-system/ — RULE-2026-06-30-A) + `sync-huntkit-manifest.json` (allowlist src→dest map + exclusions).
2. Script: copy allowlisted paths → transform (q-investigate/.q-system → .q-system) → gitleaks scan on huntkit tree → git commit in huntkit (NO push).
3. One-time structural fix in huntkit: `hooks/hooks.json` wiring token-guard.py (PreToolUse) + findings-verify-hook.py (PostToolUse) via ${CLAUDE_PLUGIN_ROOT}; bump plugin.json to 0.3.0.
4. Trigger: lefthook post-commit in 4_points, filtered to investigation-layer paths.
5. Push: manual by founder (human gate between client casework and public GitHub).

## Files to touch

- `~/projects/4_points_consulting/scripts/sync-huntkit.sh` (new)
- `~/projects/4_points_consulting/scripts/sync-huntkit-manifest.json` (new)
- `~/projects/4_points_consulting/lefthook.yml` (add post-commit hook)
- `~/projects/huntkit/hooks/hooks.json` (new), `.claude-plugin/plugin.json` (version), commands/, skills/, rules/, .q-system/ (refreshed by first build run)
- `~/projects/huntkit/README.md` (note the sync provenance + new capabilities)

## Acceptance criteria — CLOSED 2026-07-01

- [x] Reviewed new skill files: face-search.py/face-search-plan.md/face-env/config EXCLUDED (facial-recognition pipeline + client case data); security-tools.json, check-collision.*, extract-intake.py, meta-ad + security-stack scripts, tests INCLUDED (screened clean)
- [x] First build verified against a scratch CLONE (never live): 48 files, transforms + exclusions confirmed by independent pass-2 sweep
- [x] Negative test: planted GitHub-PAT-shaped secret in tempdir, gitleaks gate catches it (first version used the AWS docs example key, which gitleaks allowlists — test was vacuous, seen failing, fixed). 13/13 self-tests green
- [x] Negative test: blocklist gate blocked its own first real build (7 hits: seedscope.store, bare q-investigate in code strings) — transforms added, rerun clean
- [x] hooks/hooks.json valid JSON; transformed findings-verify-hook 5/5 self-tests; token-guard compiles. huntkit v0.3.0 = b3f4f42
- [x] Trigger proven live: git post-commit fires shim, sync no-ops when nothing relevant changed (empty-commit test, then soft-reset)
- [x] Push: AUTO (founder decision 2026-07-01, supersedes manual-push in Approach §5). Robot pushed 2d29bdc to github.com/assafkip/huntkit

## Deviations from plan (flagged)

- `sync-huntkit.sh` is a thin wrapper; logic + manifest live in `scripts/sync-huntkit.py` (transforms need real string handling)
- Trigger is a direct `.git/hooks/post-commit` shim, NOT lefthook: 4_points' pre-commit is a custom gitleaks wrapper chain that `lefthook install` would clobber. Shim is local-only (not committed); re-wire after a reclone: `chmod +x .git/hooks/post-commit` pointing at scripts/sync-huntkit.py
- Spillover captured: sp-dd731488 — settings-template.json wires token-guard with `|| true`, swallowing exit-2 blocks fleet-wide

## Patterns to follow

- Hook wiring: `plugins/kipi-core/hooks/hooks.json` (${CLAUDE_PLUGIN_ROOT}, test -f guards)
- Secrets gate: huntkit's own lefthook.yml (gitleaks + blocked-paths)
- Instance automation at repo root: launchd scar 2026-06-30 (kipi update deletes scripts inside synced q-system/)
