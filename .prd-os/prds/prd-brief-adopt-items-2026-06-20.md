---
id: prd-brief-adopt-items-2026-06-20
title: Brief Adopt Items
status: approved
created_at: 2026-06-20T01:34:03Z
updated_at: 2026-06-20T01:42:05Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-brief-adopt-items-2026-06-20-findings.jsonl
codex_reviewed_at: 2026-06-20T01:42:04Z
---

# Brief Adopt Items

<!-- PROVENANCE: Goal 2. A 14-agent re-evaluation of the claudesidian canonical brief
(q-system/output/plans/claudesidian-canonical-brief-2026-06-19.md) against current repo
state. Of 15 adopt items: 8 verifier-confirmed still worth doing here (H1,H2,H4,H5,H7,
H8,H10,H13); 5 DROPPED (H3,H6 low-value convenience; H9 high-false-positive park; H11
already-covered/reject; H12 opportunistic-after-H1); 2 CROSS-REPO to kipi-investigations
(H14,H15 -- need founder cross-instance preflight, NOT in this repo's scope). -->

## Problem

The claudesidian brief's adopt list (H1-H15) is still mostly open. Re-evaluation against the current repo confirmed 8 real, unaddressed gaps worth closing now, chunked into 5 atomic issues. None were obsoleted by the H0 cross-instance-learning work. The gaps:

- **kipi update is not safe/transparent (H2, H4):** an untracked file in a synced non-excluded dir is destroyed by `rsync --delete` (the existing pre-commit guard is `git add -u`/commit, tracked-only); and `kipi update --dry` only compares file COUNTS, not the actual changed/deleted files.
- **A dangerous unwired hook (H5):** `q-system/hooks/auto-update.sh` does a silent `git subtree pull --squash` with the wrong prefix and is unwired; it should be de-fanged to a nudge and wired at SessionStart.
- **No skill-trigger measurement (H1, H13):** kipi never measures whether an auto-invoked skill actually FIRES; description-based triggering is unverified. (The brief's headline "one real capability gap.")
- **voice-lint detector gaps (H8, H10):** emphasis-opener AI tells ("it's worth mentioning", "Importantly,") are uncaught; voice-substance-lint's anchor check passes a draft on a single generic proper noun.
- **No scrape-to-file research lane (H7):** the research cascade summarizes web content into context instead of persisting full source; Firecrawl is the one integration kipi lacks.

## Goals

- Make `kipi update` fail-safe (no untracked-file loss) and transparent (real itemized dry-run).
- De-fang and wire the auto-update nudge.
- Ship a skill-trigger eval harness (on-demand, offline-testable) + its wiring.
- Close the two voice-lint detector gaps.
- Add a fail-closed Firecrawl scrape-to-file lane (env-key gated, offline-testable).

## Non-goals

- DROPPED items H3 (rollback verb), H6 (resumable manifest), H9 (rhetorical-question detector), H11 (skill-discovery hook -- already covered by find-skills + semantic auto-invoke), H12 (with/without benchmark -- opportunistic after H1).
- CROSS-REPO items H14, H15 (Obsidian Bases/callouts) -- they land in `~/projects/kipi-investigations` (separate repo, own .prd-os); require founder cross-instance preflight; explicitly out of this PRD.
- Live API / `claude -p` calls inside any required_check: all tests are OFFLINE (mock/fail-closed paths). Provisioning `FIRECRAWL_API_KEY` is a founder action, not part of this PRD.

## Proposed approach

Five atomic issues (priority order):

1. **kipi-update-safety (H2+H4):** before the `rsync --delete` in `kipi-update.sh`, take a deterministic TMP-DIR snapshot of the instance's target dir (NOT `git stash -u`: adversarial review showed stash does not cover gitignored-but-synced paths like `q-system/sources/`, and stash/pop is not collision-safe -- a merge-base-class trap). After a clean sync, restore any file the sync DELETED that the skeleton does not manage (untracked instance content, ignored or not). Replace the `--dry` SKEL_COUNT/INST_COUNT heuristic with `rsync -ain --delete` built from the SAME `git archive HEAD` source AND the same excludes as the real run (so dry cannot drift). Test MUST use a fixture in a gitignored-but-synced path (the case `stash -u` misses) and assert it survives; plus `--dry` lists the actual changed/deleted files.
2. **auto-update-nudge (H5):** REMOVE the `git subtree pull --squash` block FIRST (de-fang), rewrite `auto-update.sh` to nudge-only (detect skew, print "run: kipi update", touch a daily sentinel, exit 0, never block), then register it in `settings-template.json` + `.claude/settings.json` SessionStart (advisory form). Test: the script contains no `subtree pull`, exits 0, prints a nudge on skew, and is registered.
3. **skill-trigger-eval (H1+H13):** `skill-trigger-eval.py` reads tiny per-skill fixture sets (`skill-evals/<skill>.json` with should_trigger prompts) for the 4 high-stakes skills and shells `claude -p` from the real repo root (so the `.claude/rules` auto-invoke path loads), reporting trigger_rate. On-demand, NOT a hook. Wire H13: document the trigger-eval pairing in `skill-hook-pairing.md` + a `wiring-check.md` bullet (advisory/periodic, never a blocking exit-2). Test: OFFLINE -- the harness parses fixtures and builds the correct command with `claude -p` MOCKED (no live call); a malformed fixture is rejected. NOTE: the offline test validates only harness plumbing, NOT the triggering premise; a green check means the harness works, not that triggering works (the live run yields a noisy advisory trigger_rate, never a hard pass/fail).
4. **voice-lint-topups (H8+H10):** add emphasis-opener tells ("it's/it is worth mentioning|noting|highlighting", opener-anchored "Importantly,/Notably,") to `voice-lint.py` AND the MCP linter; tighten `voice-substance-lint.py` so BOTH word-count branches require >=2 anchors (a single dropped proper noun no longer passes an anchorless draft). The voice-substance change MUST stay WARN-class (exit 0, never hard-block published content); the test asserts the rule stays in the WARN path. Each ships its paired test.
5. **firecrawl-scrape (H7):** `firecrawl-scrape.py` (stdlib urllib, onlyMainContent markdown, fail-CLOSED on empty body, CJK/path-safe filename), an `.mcp.json`/env stanza using `${FIRECRAWL_API_KEY}` (no committed secret), wired as an explicit "persist full source" rung in research-mode. Test: OFFLINE -- fail-closed on empty body, filename sanitize, graceful no-key behavior (mock the HTTP layer).

## Risks and rollback

- H2 snapshot: a deterministic tmp-dir copy/restore (not the git stash stack) avoids stash-pop collisions and covers gitignored-but-synced content. Test asserts an untracked gitignored-synced file round-trips.
- H5 ordering: de-fang BEFORE wiring (never wire a dangerous pull). The issue enforces order; test asserts no subtree-pull remains.
- H1 cost: the harness shells `claude -p` (real cost) only when the founder runs it; the required_check mocks it (no live call, no cost in CI).
- Each issue is independently revertible (git revert).

## Open questions

Resolved (owner-delegated, autonomous): all 5 chunks are verifier-confirmed worth doing now; the rest are dropped/cross-repo. `FIRECRAWL_API_KEY` provisioning is a founder action noted in issue 5.

## Issues

```json
[
  {
    "id": "kipi-update-safety",
    "title": "kipi update fail-safe + transparent: deterministic tmp-dir untracked-snapshot before rsync --delete (covers gitignored-synced; H2), and a real rsync -ain itemized --dry from git archive HEAD replacing the file-count heuristic (H4)",
    "finding_id": "finding-1",
    "allowed_files": ["kipi-update.sh", "q-system/.q-system/scripts/test/test-kipi-update-safety.sh"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh"],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh"
  },
  {
    "id": "auto-update-nudge",
    "title": "De-fang auto-update.sh (remove the dangerous git subtree pull --squash) and rewrite to a never-blocking SessionStart nudge, then wire into settings-template.json + .claude/settings.json (H5)",
    "finding_id": "finding-2",
    "allowed_files": ["q-system/hooks/auto-update.sh", "settings-template.json", ".claude/settings.json", "q-system/.q-system/scripts/test/test-auto-update-nudge.sh"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-auto-update-nudge.sh"],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-auto-update-nudge.sh"
  },
  {
    "id": "skill-trigger-eval",
    "title": "Skill-trigger eval harness + fixtures for the 4 high-stakes skills, on-demand claude -p from real repo root (H1), plus the skill-hook-pairing + wiring-check documentation (H13); required_check is OFFLINE (claude -p mocked)",
    "finding_id": "finding-3",
    "allowed_files": ["q-system/.q-system/scripts/skill-trigger-eval.py", "q-system/.q-system/skill-evals/**", ".claude/rules/skill-hook-pairing.md", ".claude/rules/wiring-check.md", "q-system/.q-system/scripts/test/test-skill-trigger-eval.sh"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-skill-trigger-eval.sh"],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-skill-trigger-eval.sh"
  },
  {
    "id": "voice-lint-topups",
    "title": "voice-lint emphasis-opener detector (H8) across voice-lint.py + the MCP linter, and voice-substance-lint single-proper-noun loophole fix requiring >=2 anchors on both word-count branches (H10), each with a paired test",
    "finding_id": "finding-4",
    "allowed_files": ["q-system/.q-system/scripts/voice-lint.py", "q-system/.q-system/scripts/voice-substance-lint.py", "plugins/kipi-core/kipi-mcp/**", "q-system/.q-system/scripts/test/test-voice-lint-topups.sh"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-voice-lint-topups.sh"],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-voice-lint-topups.sh"
  },
  {
    "id": "firecrawl-scrape",
    "title": "Firecrawl scrape-to-FILE lane (H7): firecrawl-scrape.py (stdlib, onlyMainContent, fail-closed on empty body, safe filename), env-key stanza (no committed secret), wired into research-mode; required_check OFFLINE (HTTP mocked)",
    "finding_id": "finding-5",
    "allowed_files": ["q-system/.q-system/scripts/firecrawl-scrape.py", ".mcp.json", "plugins/kipi-core/skills/research-mode/SKILL.md", "q-system/.q-system/scripts/test/test-firecrawl-scrape.sh"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-firecrawl-scrape.sh"],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-firecrawl-scrape.sh"
  }
]
```
