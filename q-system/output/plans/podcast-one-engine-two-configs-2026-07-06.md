# Plan: merge the two podcasts to one engine, two configs

**What/why:** Cole runs the daily AI-news podcast TWICE as the same code: the live private show
(`cole-gtm/gtm/scripts/podcast/`) and the public OSS repo (`cole-gtm/projects/notebooklm-daily-podcast/`).
Dedup audit (RULE-2026-07-06-B) confirmed same codebase, cosmetic deltas. Two copies = a bug fix
must land twice; they WILL drift. Goal: ONE engine (the OSS repo), the live show becomes a config
on top. Zero duplicated code, both keep existing (private show + public repo).

**Status: PARKED — do not merge (decided 2026-07-06, RULE-2026-07-06-B).** Recon showed the two
podcasts share only a small STABLE mechanism (dedup.py 4-line diff, make_podcast.sh 7); the
show-specific files diverged hard (fetch_sources 260, build_email_html 377) into two real products.
A full merge reconciles diverged code against a LIVE show for modest payoff; a shared-lib extract
couples a live branded show to a public repo — both worse than the copy-paste. Instead: boundary
declared (live = source of truth, repo = sanitized export) + sync-on-change note in the two shared
files. This plan is kept as the record of what was evaluated and why it was parked. The sections
below are the merge design that was NOT executed.

---

## Ground truth (scanned 2026-07-06)

- **Shared engine files** (near-identical per dedup audit): `make_podcast.sh`, `dedup.py`,
  `build_rss.py`, `fetch_sources.py`. `dedup.py` header even says "Ported from ASK ai-news-podcast".
- **Live-only / Cole-specific:** `run_daily.sh` (350+ lines) — the orchestrator. It hardcodes:
  Cole persona in every LLM prompt ("You are Cole…"), audience string, `OUT=$HOME/cole-podcasts`,
  `CREDS=$HOME/.config/ai-news-podcast/env`, Friday recap logic. Driven by env vars already
  (`PODCAST_TEST_TO`, `PODCAST_RECAP`, `AUDIENCE`).
- **OSS repo** is config-driven: `config.example.json` + `PODCAST_SHOW_NAME` + clone-and-configure.

So the engine (fetch→dedup→curate→build→rss→email) is shared; the ORCHESTRATOR differs only in
config values + the persona/voice strings embedded in prompts.

---

## Target architecture

```
projects/notebooklm-daily-podcast/     = THE ENGINE (owns the pipeline scripts + orchestrator)
  run.sh --config <path>               (reads all show-specifics from a config file)
  config.example.json                  (public template)

cole-gtm/gtm/config/cole-podcast.json  = Cole's private config (show name, audience, persona
                                          voice string, OUT dir, creds path, sources, recap on/off)
```

- The launchd job calls `notebooklm-daily-podcast/run.sh --config gtm/config/cole-podcast.json`.
- `gtm/scripts/podcast/` shared pipeline files are DELETED (engine now lives once, in the repo);
  Cole keeps only its config + any Cole-only assets (episode pages template, etc.).
- The persona/voice ("You are Cole…") + audience become CONFIG VALUES the engine interpolates
  into its prompts — not hardcoded in a Cole copy.

---

## The risk + how the dry proves it safe

The live show airs daily and publishes to podcast.ktlystlabs.com. Breaking it is the worst miss.
So, before ANY switch:
1. Add `--config` support to the OSS engine (config carries show name, audience, persona string,
   OUT, creds, sources, recap flag). No change to the live job yet.
2. Write `cole-podcast.json` reproducing the live show's exact current settings.
3. **Test run** the merged engine with Cole's config in test mode (`PODCAST_TEST_TO=<founder>`),
   producing to a scratch OUT dir. Compare to a normal `run_daily.sh` run of the same day:
   same selected stories, same RSS `feed.xml` shape, same email HTML.
4. Only when the test episode matches: repoint the launchd job to the engine + Cole config,
   reload, watch one real run, THEN delete the duplicated `gtm/scripts/podcast/` pipeline files.

## Files to touch
- `projects/notebooklm-daily-podcast/run.sh` (+ engine scripts): add `--config` / config-loading.
- NEW `cole-gtm/gtm/config/cole-podcast.json` (private; gitignored if it holds creds paths).
- `~/Library/LaunchAgents/com.cole.daily-podcast.plist` (+ report/weekly): repoint ProgramArguments.
- DELETE (last, after green): `cole-gtm/gtm/scripts/podcast/{make_podcast,dedup,build_rss,fetch_sources}.py` etc.

## Acceptance criteria
- [ ] Engine accepts `--config`; all show-specifics (name, audience, persona, OUT, creds, recap) come from it
- [ ] `cole-podcast.json` reproduces today's live settings exactly
- [ ] Test run (test-send mode, scratch OUT) === a same-day `run_daily.sh` run: same stories, RSS, email
- [ ] launchd repointed + one real run watched green before deleting the old copy
- [ ] `com.cole.daily-podcast` + `podcast-report` + `podcast-weekly-report` all fire from the engine
- [ ] Public repo still clones-and-configures for outside users (didn't break the OSS path)
- [ ] Rollback: keep the old `gtm/scripts/podcast/` until the real run is green (delete is the last step)

## Patterns
Verify-against-a-copy (test-send + scratch OUT before switching a live job); delete-last (the old
copy is the rollback until the new path is proven); founder-facing output through assaf-voice N/A (internal).
