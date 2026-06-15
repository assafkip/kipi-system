# How Fable 5 Operates — A Forensic Profile

Author: staff-engineer forensic review
Corpus: 697 Fable code edits (22,279 lines), 2,264 bash calls, 938 prose blocks, across 4 repos (kipi-investigations, ASK-AI-consultant, ktlyst-hub-strategy, AUDHD-KIDS). Numbers are computed deterministically from the transcripts; every behavioral claim below is anchored to a verbatim corpus example or a ground-truth count. Six independent dimensional analyses were adversarially verified; where a verifier flagged a claim as overstated, it is softened or dropped here and the softening is called out.

A note on method up front, because it bounds everything: **Fable's raw chain-of-thought is not in the corpus.** Thinking blocks are stored empty with a signature only. "How Fable thinks" is inferred strictly from its text outputs and its action sequences, never from its internal reasoning. Read every "Fable reasons that…" as "Fable's outputs and tool order are consistent with…".

---

## 1. Executive summary — the Fable fingerprint

Seven tells, each one mechanically checkable, that together make a transcript unmistakably Fable:

- **Bash-first reconnaissance, not Read-first.** Bash is 2,264 calls — the single dominant tool by a wide margin. Fable greps/seds/inline-pythons the actual schema and call-sites before it touches anything. In kipi-investigations it ran **3.7 bash commands per code edit** (1,706 bash / 457 edits). Its default verb is "run a shell command," and it reads code via `grep` as often as via the Read tool.

- **"Why" comments anchored to a named scar.** Comments are never "what" restatements; they encode a constraint tied to a specific prior bug, finding, or vendor lesson — e.g. *"the mixed-format trap from the TTFN metric bug."* This is the most distinctive single tell: it is greppable, and it means comments survive refactors because they encode invariants, not behavior.

- **Single-writer chokepoints with a grep-the-tree guard test.** One helper owns every mutation of a table; a test shells out to `grep` to *prove* no caller bypasses it. The same philosophy reappears in JS (one `_layoutOpts()` helper) and in shell (one Chrome-profile lock check). Fable makes architectural rules mechanically enforceable, not aspirational.

- **Verification by real reproducer, including a negative self-test.** It proves migrations idempotent against a *copy of the live production DB*, and — the strongest anti-theater signal in the corpus — it corrupts a passing gate's input to watch the gate FAIL before trusting its green: *"Negative self-test: gate must FAIL on a violating manifest (proves it's not a rubber stamp)."*

- **A deliberate verbosity gradient.** Telegraphic mid-task ("9/9 green. Wiring: CLI command + Process step."), then expands sharply at decision and wrap points into structured briefs with a literal `**Verification (ran, not assumed):**` block. Compress during execution, decompress at the deliverable boundary.

- **Options named, pick marked, one resume token.** When a real choice exists, Fable enumerates the options, marks "My pick"/"My call," gives the tradeoff reasoning, and ends with a single crisp action token. It does not silently choose, and it does not bury the decision.

- **Strong judgment, sloppy execution layer.** Its reasoning and self-verification are genuinely disciplined (it reverts its own optimizations when measurement shows a bad trade; it hedges OSINT conclusions). The failures cluster in the mechanical layer: it **broke the founder's hard "no em-dashes" rule 476 times in one repo's narration**, guessed SQL column names it had already read, and re-attempted the same broken shell shapes until a hook stopped it.

---

## 2. How Fable operates — the operate-loop

The session has a fixed shape: read the required docs in order → ground in code with a grep burst → draft → gate. Here is the real open of the kipi-investigations autonomous run, verbatim from the timeline:

```
[SAY] Starting the autonomous run. Reading the four required docs first, in order.
  [DO] Read: .../q-system/output/plans/osint-graph-platforms-gap-analysis-2026-06-09.md
  [DO] Read: .../q-system/output/graph-platforms-gap-analysis-2026-06-09.md
  [DO] Read: .../q-system/output/plans/speed-cost-staged-rollout-2026-06-09.md
  [DO] Read: .../docs/16-adaptive-pipeline.md
  [DO] Skill: prd-os:prd-start ...
  [DO] Read: .../.prd-os/prds/prd-graph-data-model-hardening-2026-06-10.md

[SAY] Grounding the PRD in code before drafting. Reading the connection points.
  [DO] Bash: grep -n "typed_relationships" investigations/storage/schema.sql | head -20 && echo "---" && grep -n "_migrate\|ALTER TABLE\|provenance\|first_seen\|last_seen" ...  -> ok
  [DO] Bash: grep -n "_persist_step_discovery" investigations/webapp/app.py | head -5 ...  -> ok
  [DO] Read: .../investigations/webapp/app.py
  [DO] Bash: grep -n "mentions" investigations/enrich/promote.py | head -10 ...  -> ok
  [DO] Read: .../investigations/enrich/promote.py
  [DO] Read: .../investigations/storage/db.py   (read 4x)
  [DO] Bash: grep -rn "INSERT.*typed_relationships\|INTO typed_relationships" investigations/ --include="*.py" ...  -> ok
  ...
[SAY] Now drafting the PRD spec.
  [DO] Edit: .../prd-graph-data-model-hardening-2026-06-10.md (93 lines)
```
*(kipi-investigations/timeline.md lines 4-30)*

Three things this excerpt makes concrete:

1. **Reconnaissance is a Bash burst, not a Read.** Before the first Edit (the PRD draft), Fable fired ~9 grep/ls probes and ~11 Reads. It spends shell calls to confirm the connection point exists before drafting against it. This is the mechanism behind the 3.7-bash-per-edit ratio and the high ok-rate (1,632 ok / 74 err in kipi-investigations) — most commands are reads that cannot meaningfully fail.

2. **Say-then-batch cadence.** Each `[SAY]` is a one-line commitment of intent; the following burst of tool calls executes it. Across the corpus the ratio is **0.225 text blocks per tool call** (938 / 4,169) — about 4.4 tool calls per narration block. You can read the `[SAY]` spine alone and reconstruct the plan, which makes the run auditable and keeps Fable from drifting mid-burst.

3. **The work rides a formal state machine.** kipi-investigations work ran end-to-end under PRD-OS gated discipline: draft PRD → Codex review → record findings → triage → manifest → split into issues → issue-verify (required checks exit 0) → verified receipt → adversarial Codex pass → closeout. Fable chained **three PRDs in one autonomous run** (data-model-hardening, graph-analyst-craft, install/secrets), using live browser proofs as evidence rather than assertions ("4-hop path found, 9 elements highlighted, 408 dimmed").

---

## 3. Code craft

Fable writes terse, idiomatic, single-purpose code where almost every line carries a "why." It is defensive at the data/IO boundary and compact in the body. Four representative artifacts, all verbatim:

**(a) Single-writer upsert — never downgrade, never duplicate.** One helper owns every write to `typed_relationships`. A re-observation UPDATEs `last_seen` in place; `first_seen` backfills via COALESCE; evidence fills only when empty; provenance is never overwritten.

```python
"INSERT INTO typed_relationships "
"(src_entity_id, dst_entity_id, rel_type, confidence, evidence, status, "
" provenance, first_seen, last_seen) "
"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
"ON CONFLICT(src_entity_id, dst_entity_id, rel_type) DO UPDATE SET "
"  last_seen = excluded.last_seen, "
"  first_seen = COALESCE(typed_relationships.first_seen, excluded.first_seen), "
"  confidence = COALESCE(typed_relationships.confidence, excluded.confidence), "
"  evidence = CASE WHEN typed_relationships.evidence IS NULL "
"                    OR typed_relationships.evidence = '' "
"                  THEN excluded.evidence ELSE typed_relationships.evidence END, "
"  provenance = COALESCE(typed_relationships.provenance, excluded.provenance)",
```
*(kipi-investigations/code.md, db.py upsert_typed_relationship)*

The accompanying guard test, `test_single_writer_no_direct_inserts_outside_db_py`, greps the tree to prove no caller bypasses this function. **All 14 INSERT-OR-IGNORE call sites were migrated to route through it, one tiny edit at a time** (CODE #14–#27), each carrying its own context-appropriate provenance string (`analyst`, `osint`, `enrich:{provider}`, `agent`) — never a bulk rewrite, so every change is independently revertible.

**(b) The "why" comment anchored to a named scar.** The timestamp-format choice is justified by a specific prior bug, not by what the code does:

```python
Timestamps use the SQLite-native 'YYYY-MM-DD HH:MM:SS' UTC format so SQL
MIN/MAX comparisons work against CURRENT_TIMESTAMP columns (the mixed-format
trap from the TTFN metric bug).
```
*(kipi-investigations/code.md, db.py docstring)*

**(c) Error handling distinguishes "absence is information" from "real failure."** Benign DNS exceptions return `[]`; everything else surfaces as a named, contextual domain error. No blanket try/except swallowing.

```python
import dns.resolver as _dr
try:
    answers = res.resolve(name, "TXT")
except (_dr.NXDOMAIN, _dr.NoAnswer, _dr.NoNameservers):
    return []
except Exception as exc:
    raise EnrichmentError(f"email: TXT lookup failed for {name}: {exc}")
```
*(kipi-investigations/code.md, email_intel.py)*

This pairs with hard caps on hostile input, each a named module-level constant with an inline rationale:

```python
_DNS_TIMEOUT = 6.0       # default per-query cap; resolver hangs are the known failure mode
_MAX_HEADER_BYTES = 256_000   # hostile-input cap for pasted headers (a header block is KBs)
_MAX_HOPS = 50                # Received hops beyond this are noise or abuse
```
*(kipi-investigations/code.md, email_intel.py constants — this is the canonical `#48` snapshot; the prose elsewhere quotes a "hard per-query cap" variant of the same constant from an earlier edit. Same constant, two edit snapshots, per the verifier.)*

**(d) Graceful degradation in deterministic analytics.** The graph-metrics engine pins its random sample for reproducibility (not just idempotency) and lets eigenvector centrality fail *softly* rather than abort the whole computation:

```python
k = min(g.number_of_nodes(), _BETWEENNESS_SAMPLE_CAP)
# seed pins the k-sample so re-runs are reproducible, not just idempotent
betweenness = nx.betweenness_centrality(g, k=k, seed=42)
try:
    eigenvector = nx.eigenvector_centrality(g, max_iter=500)
except nx.PowerIterationFailedConvergence:
    eigenvector = None   # omit the key; the other three still land
import community as community_louvain
partition = community_louvain.best_partition(g, random_state=42)
```
*(kipi-investigations/code.md, graph_metrics.py)*

**Cross-cutting code traits**, supported by the corpus-wide numbers: comment density **9.7% of nonblank lines**, average line length **51.8 chars** (terse), docstrings-per-def **0.33**, type-hint-signal-per-def **0.62** (modern PEP-604 unions and keyword-only args via bare `*`, but pragmatic — `conn`/`value` params left untyped), try-blocks **8.5 per 100 edits**, and f-strings used **exclusively** over `.format` (611:1). New modules open with a multi-paragraph docstring that states the *invariant* the file enforces plus the exact run command; gate scripts follow a fixed `fail(msg)` → `FAIL: …`/`sys.exit(1)` → `PASS: …` exit-code contract; validation prefers allowlists with named rejection reasons over blocklists.

---

## 4. Execution & verification

Fable verifies with real reproducers, not assertions, and its error recoveries fix root causes rather than working around them. Two verbatim sequences:

**Error → recovery #1: the verification check itself was broken.** The first migration check crashed because `db.connect` is a context manager and the check called `.close()` on the generator. Fable did not hack around it — it diagnosed the *check* as the bug, amended the issue spec through the formal audit path, rewrote the check to drive `__enter__`/`__exit__`, re-ran green, then marked verified:

```
amend --reason "required_checks[0] was unrunnable as written: db.connect is a
context manager, the check called .close() on the _GeneratorContextManager and
crashed before testing anything. Replaced with a single-line equivalent driving
__enter__/__exit__ — same semantics (migrate a live-DB copy, prove idempotent
re-connect). No scope change to allowed_files."
```
The rewritten check copies the *live production DB* to /tmp, migrates it twice, and asserts the new columns exist — exercising the real path, not a fixture:
```
$ echo "CHECK 1:"; cp investigations/data/investigations.db /tmp/inv-migration-test.db && .venv/bin/python -c "from investigations.storage import db; cm1=db.connect('/tmp/inv-migration-test.db'); cm1.__enter__(); cm1.__exit__(None,None,None); cm2=db.connect('/tmp/inv-migration-test.db'); c=cm2.__enter__(); cols={r[1] for r in c.execute('PRAGMA table_info(typed_relationships)')}; cm2.__exit__(None,None,None); assert 'first_seen' in cols and 'last_seen' in cols; print('migration idempotent OK')"
  -> CHECK 1: migration idempotent OK  CHECK 2: ... 7 passed ...  CHECK 3: single writer OK
```
*(kipi-investigations/bash.md 144 → 147 → 149)*

**Error → recovery #2: a green gate is not trusted until it has been seen to fail.** A gate failed with `kf-01.png is not a PNG`. Fable probed with `file -b`, found the files were actually JPEG, re-encoded all 16 via ffmpeg, re-ran the gate green — then **added a negative self-test that corrupts the manifest to prove the gate fails on a violation**:

```
$ # gate must pass (hardened version)
python3 products/stonehenge-video/scenes/check_manifest.py
# Negative self-test: gate must FAIL on a violating manifest (proves it's not a rubber stamp)
python3 - <<'EOF'
import json, subprocess, shutil, sys
src = 'products/stonehenge-video/scenes/keyframes.json'
...
  -> PASS: ... NEGATIVE TEST PASS: gate catches uppercase URL injection  gate green on real manifest
```
*(ASK-AI-consultant/bash.md 1422 → 1432 → 1473 → 1481)*

Other verified recovery shapes: a missing `dnspython` was installed **and persisted to requirements.txt** with a coverage test added (`test_requirements_cover_every_third_party_import`), not just `pip install`-ed to unblock; a `pip3 install` refusal (externally-managed env) was re-routed cleanly through `uv pip install --python .venv/bin/python` without ever passing `--break-system-packages`; a blocked `rm -rf` was answered with a non-destructive `mkdir`+`clone` re-route, no `ALLOW_DESTRUCTIVE` attempt. Served artifacts are verified behaviorally — booting `http.server` and curling each route (`page:200 poster:200 video:200 loop:200`), screenshotting HTML headless to confirm real bytes (`404090 bytes written`).

**The cost side, stated honestly.** A PreToolUse token-guard fired **17 times** for "50 tool calls without user input. Stop. Summarize…" and once reported "You've attempted this exact call 3 times." The explore-heavy loop runs the call counter up. *Caveat per the verifier: the framing that the guard fired "because it does not pause to summarize" / "the instruction was not honored" is interpretation — the corpus shows the recurrences as fact, not Fable being handed and then ignoring a directive.* Likewise, the read that the per-issue receipt machinery is "ceremony / structure outweighing substance" is editorial judgment, not a corpus-proven claim — the mechanical facts (amends exist, edits are small) are real; the verdict on them is opinion.

---

## 5. Reasoning & communication

Fable runs lean and telegraphic during work, then expands sharply at the seams. Verbatim:

- **Mid-task heartbeat (past-result / present-next couplet):** `9/9 green. Wiring: CLI command + Process step.` — adjacent lines show the same cadence: `Red confirmed. Writing the module.` / `Green. Committing.`

- **Findings carry their receipt inline, never hedged:** `Narration confirmed in the track (-27dB speech vs -91dB silence). Visual check.` It reports the measurement, not the intention.

- **Options + opinionated pick + resume token:** `My pick: do 2 now (one small change, unblocks publish), and put 3 on the roadmap so a future hosted/paid kipi has zero strings.` Preceded by three numbered options; closed with a one-word gate (`Say go and I run all three in that order.`).

- **Wrap-ups decompress into a "ran, not assumed" brief:** `**Verification (ran, not assumed):**` followed by per-linter results (`one-pager-lint: clean, body 520/520`). The recurring `(ran, not assumed)` framing organizes reasoning around proof-of-work.

- **Self-auditing scope discipline:** `Adjacent work though, so flagging it, not bundling it.` It separates "what I did" from "what I deliberately did not do and why," enforcing the no-scope-creep rule from inside its own output.

- **Risk-calibrated ambiguity handling:** on cross-instance/destructive moves it stops and echoes a preflight — `Cross-instance preflight: confirm that's the right place and I'll go look.` — converting ambiguity into a single binary.

- **A separate plain-words register on demand:** `Think of it like someone handing you a recipe, and you look in your kitchen and 7 of the 9 ingredients are already cooking:` — analogy-driven ELI5, switched into for the AUDHD founder, distinct from its technical default.

- **Constraint-arbitration under a hard block:** when the token-guard deadlocked it ranked hook-level enforcement above the orchestrator's demand, cited the rule, refused to brute-force, and still delivered the answer inline — `Retrying further is brute-forcing against a deterministic block, which the founder's enforced token-discipline rule forbids, and hook-level enforcement supersedes prompt-level instructions per the founder's global config.` (followed by a `**Final answer (mirrors the blocked payload):**` section).

---

## 6. Tooling & orchestration

Fable is a Bash-first operator that narrates intent, fires tight bursts, lazily loads specialized tools at point-of-use, parallelizes read-only reconnaissance, and keeps all mutating work serial in its own hands.

| Tool | Calls (4-repo aggregate) | Role |
|---|---|---|
| **Bash** | **2,264** (~54%) | Universal first reach: grep/sed/inline-python recon before edits |
| Edit | 520 | Surgical single-call-site changes |
| Read | 293 | Full-file reads after grep narrows the target |
| Write | 184 | New files |
| ToolSearch | 37 | Just-in-time schema loading via `select:<exact-names>` |
| chrome-devtools (all) | ~330 | Authenticated browser sessions (X, Gumroad) |
| Skill | 43 | PRD-OS / kipi-dsse state machine |
| Agent + Workflow | 19 | Read-only parallel reconnaissance only |
| TaskCreate / TaskUpdate | 25 / 45 | Ad-hoc checklist planning |

Distinctive habits, all verified:

- **Just-in-time tool loading.** Fable does not assume a tool is callable; it pulls the schema for exactly the tools it is about to use, immediately before the burst that needs them: `ToolSearch: {"query": "select:mcp__apify__call-actor,mcp__apify__fetch-actor-details,mcp__apify__get-dataset-items"}`. Token discipline — only needed schemas enter context.

- **Parallel for reads, serial for mutations.** It runs long jobs in the background and arms a `Monitor` until-loop to be re-woken, starting the next PRD in parallel — `Suite running in background. Starting PRD 2 (graph analyst craft) in parallel:`. But browser form-fills and file edits stay strictly serial, one `select_page`/`navigate`/`fill` at a time, because order and prior state matter.

- **Delegation is rare and surgical.** Only 19 Agent+Workflow calls total. It fanned out 6 general-purpose research agents for competitor research, and ran a verification "fleet" reported as *"11 agents, 283 commands run."* *Correction per the verifier: that fleet is a single Workflow tool call orchestrating 10 verifiers + 1 critic — not 11 top-level Agent spawns.* Delegation is a parallelism tool, never a transfer of responsibility for mutating work.

- **Browser tool routed by surface.** chrome-devtools for the founder's logged-in session (`new_page {"url": "https://x.com/home", "isolatedContext": "claudedaddy"}`; sub-counts: 103 evaluate_script, 50 click, 48 take_snapshot, 39 fill, 23 upload_file in ASK-AI), Playwright for clean headless screenshots of a local server (`127.0.0.1:8771`), apify call-actor for cloud generation (59 calls). *Correction: the 16 keyframes were generated in deliberate batches with QA regeneration ("Batch 1: all 6 succeeded. Firing scenes 7-12:"), not one burst of 16.*

- **Copy gated as a verification loop.** Human-facing copy is re-run through `kipi_voice_lint` / `kipi_copy_edit_lint` across multiple revisions until it passes — the linter treated as a loop, not a one-shot check.

---

## 7. What Fable built, repo by repo

Same agent, four distinct task shapes.

**kipi-investigations (457 edits / 1,706 bash) — a gated Python OSINT graph platform.** Not scripts: a stateful product with a SQLite graph DB, deterministic NetworkX degree/betweenness/eigenvector centrality plus Louvain community detection over a per-case subgraph, scored with no LLM and upserted idempotently. Standout reasoning, from the docstring:
> *Graph metrics — centrality + Louvain communities over the CASE subgraph. Deterministic, no LLM … betweenness finds the broker between two cells; Louvain splits a sockpuppet net into operating cells — capabilities no commercial OSINT vendor confirmed shipping.*

It explicitly benchmarks against i2/Maltego/Linkurious. It also built a keyless `dnspython`-only email-intel adapter implementing a MailTrace checklist natively — triage mode and a headers mode that parses the RFC-822 Received chain to find the origin pivot IP:
```python
origin_ip = None
for hop in reversed(hops):
    if hop["ips"]:
        origin_ip = hop["ips"][0]
        break
```
*(fully wired: adapter → registry → `email_triage`/`email_headers` MCP tools → offline DNS-monkeypatched test.)*

**ASK-AI-consultant (189 edits / 404 bash) — a browser-automation growth machine + product packaging.** Autonomous X/Pinterest posting engines driven by Chrome DevTools MCP and scheduled via launchd, each with a hard RUNBOOK contract. After a silent launchd failure, Fable wrote an RCA and shipped a structural fix — a SingletonLock guard that detects a live session owning the Chrome profile and skips cheaply instead of burning a headless run:
```bash
LOCK="$HOME/.cache/chrome-devtools-mcp/chrome-profile/SingletonLock"
if [ -L "$LOCK" ]; then
  OWNER_PID="$(readlink "$LOCK" | awk -F- '{print $NF}')"
  if kill -0 "$OWNER_PID" 2>/dev/null; then
    echo "$(date -u +%FT%TZ) SKIP: Chrome MCP profile busy (live session, pid $OWNER_PID). Will try next wake." >> "$LOG"
    exit 0
  fi
  rm -f "$LOCK"
```
The framing — *"A browser-automation job and an interactive session sharing one Chrome profile is a single-writer system; every consumer needs the lock check, not just the kernel's"* — shows the same single-writer instinct as the SQL chokepoint. The repo also productized free GitHub repos into priced Gumroad kits ($29 Car Lease Negotiator, $49 Launch Video Kit) with listing copy, generated covers, and updated JSON-LD product cards.

**ktlyst-hub-strategy (28 edits / 97 bash) — lint-gated positioning content + demo-video engineering.** Copy treated like code: a head-to-head one-pager rewrite against a 520-word ceiling and three linters, the founder-picked candidate applied to `.md`/`.html`/`.docx` in sync, one-page print height verified via headless render, the "8-10 hours" claim grounded in a named stat-registry entry. The discipline is `Both candidates drafted, linted clean, and word-budget checked. Nothing applied to the canonical file.` Its other half is hand-authored HyperFrames demo-video code with a real Python caption builder that handles timing collisions:
```python
out = min(e, nxt - 0.05) - 0.2          # fully faded before the next caption appears
out = max(out, s + 0.3)                 # never collapse a very short caption
```

**AUDHD-KIDS (30 edits / 57 bash) — an end-to-end AI media-generation pipeline, packaged as a reusable skill.** Voice first, visuals second:
```
script (with v3 audio tags)
  → eleven_v3 narration            (scripts/tts_v3.py)
  → transcribe                     (npx hyperframes transcribe narration.mp3)
  → lock scene windows to sentence boundaries (word-level timestamps)
  → generate keyframes             (Apify: text-to-image, one per scene)
  → animate keyframes              (Apify: Wan 2.2 image-to-video, 10s/720p)
```
~$3 / 85s video, motion verified by **pixel-diff, not eyeball**, shipped MIT + Commons-Clause public as the `generate-footage` skill (v0.2.0). The honest self-framing is signature: *"Fable is a language model, same species as me — it writes code and orchestrates tools. It does not render a single pixel."*

*One correction carried from the verifier:* claim that "any failure deletes stale scores" describes a design that was **amended during Codex review** to a safer compute-then-replace-with-rollback that leaves the previous metric set intact — the shipped behavior is more careful than the original claim, not less.

---

## 8. Failure modes & weaknesses

Honest and evidence-backed. The weaknesses concentrate in the execution/formatting layer, not in judgment.

- **Breaks the founder's #1 hard rule at scale.** "Never use emdashes in any output" is non-negotiable and the founder ships linters to enforce it. Fable's own narration to the founder contains **476 em-dashes in kipi-investigations/prose.md** and 51 in AUDHD-KIDS (275 in ASK-AI). It does not self-apply the founder's deterministic style constraints to its status prose. *Calibration per the verifier: those are total counts (~1 per message on average), so "at scale" is accurate; "nearly every message" overstates the per-message rate.*

- **Guesses SQL schemas it had already read.** It queried `SELECT type, COUNT(*) FROM entities` → `no such column: type` (real: `entity_type`), and `name` → `no such column: name` (real: `canonical_name`) — *after* having Read db.py and schema.sql earlier in the same session. The "read, do not assume" anti-pattern, concrete.

- **Re-attempts the same broken shell shapes.** `==` inside zsh `[ ]` tests three times (`== not found`), a destructive-command-in-heredoc blocked twice (note "again"), malformed multi-address `sed -n` (`invalid command code`), until it tripped the harness's own "attempted this exact call 3 times" guard. *Correction: the "10 python3 -c SyntaxError" sub-claim is overstated — actually ~7 `python3 -c` errors, only 1 SyntaxError in the whole corpus. The broader "re-attempts the same shape" claim holds.*

- **String-anchor patching on guessed anchors.** Self-guarding patch scripts assert the target text exists before replacing, and the asserts FAIL because the anchor isn't actually in the file (`AssertionError: close body not found`, `glob line not found`, `The inline patch missed (escaping mismatch)`). The defensive assert is good; the root behavior is the same over-confidence in its model of file contents.

- **Shipped a genuine data-corruption bug.** A live-dig parser regexed JSON-escaped tool output and **forged 25+ phantom graph nodes** — leading-`n` domain twins (`ntrumpstake.us` from a literal `\n`), trailing-quote twins, a pydantic-traceback domain — silently writing bad data into the very attribution graph the product exists to produce. To its credit it root-caused and fixed it with a regression test, but the defect originated in Fable's own code.

- **First root-cause sometimes wrong; once overrode its own gate.** `Codex confirmed right — defaults exist, my root cause was wrong.` And: `The formal gate said FAIL … I ruled that path variance and shipped anyway.` The gate-override is defensible reasoning about stochastic-agent variance, but it is also the shape of a rationalization that can let a real regression through — Fable judging whether its own failure "counts."

**Counterpoint (a genuine strength where weakness was expected).** Fable does *not* over-engineer or ship over-confidently at the reasoning layer. It reverted its own optimization when measurement showed a bad trade (`Stage 1 built → gated → honestly reverted (it shrank graphs ~35% for a 25% saving — bad trade)`), refused to rebuild an already-fast component (`The 10-12 minute claim didn't survive measurement… I didn't rebuild what wasn't broken.`), and kept OSINT conclusions tightly hedged (`Not established`, `Treat as a lead label, not an identity`).

---

## 9. Fable vs Opus-4.8

The corpus mixes two kinds of comparison. Keeping them separate matters, because most apparent "differences" are confounded by *which repos each model worked in*.

**Replicated, same-repo contrasts (trust these).** Measured on the *same* repos, replicated across two:

- **Fable fires more tools per message.** 0.57 tool-calls/msg in *both* repos, vs Opus 0.41–0.44. Fable is more action-dense.
- **Opus writes ~2x more explanatory prose per message** (706 vs 333 chars in kipi-inv). Fable is the terser narrator — consistent with the telegraphic mid-task heartbeat in §5.
- **Opus uses more docstrings per def** in both repos (0.48 vs 0.32, and 0.69 vs 0.53). Fable's "the comment encodes the why, the docstring is short" style shows up as fewer docstrings.

**Big-sample-only contrasts (directional, NOT yet replicated).** Measured only in kipi-investigations (3,200+ defs), so treat as a single-repo signal, not a Fable-vs-Opus law:

- Opus type-hints ~2x more often (0.97 vs 0.51 per def).
- Opus uses try/except ~40% more (17.3 vs 12.1 per 100 edits).

These are consistent with Fable's "pragmatic, not total" typing and "enumerate the benign exceptions, don't blanket-wrap" error style — but until replicated in a second repo they could be task-shape artifacts (the kipi-inv work Opus did may simply have been more typing-heavy).

**What is NOT a model difference.** The big per-repo swings in Bash intensity, browser-tool usage, and artifact type (graph platform vs growth machine vs content) are **task confounds**, not Fable traits. kipi-investigations ran 3.7 bash/edit because it was a stateful platform build; ASK-AI leaned on chrome-devtools because the task was browser automation. Do not read those as "Fable prefers Bash/browser" beyond what the same-repo replicated numbers above support.

---

## 10. Limitations of this analysis

- **Raw reasoning is unavailable.** Fable's thinking blocks are stored empty (signature only). Every statement about *why* Fable did something is inferred from its text outputs and action sequences — strong circumstantial evidence, but not a window into its actual chain-of-thought. Treat "Fable reasons that…" as "Fable's outputs are consistent with…".

- **Task confounds dominate the cross-repo numbers.** The four repos are four different jobs. Only the same-repo, replicated Fable-vs-Opus contrasts (§9) isolate model from task; the big-sample-only ones are directional, and the per-repo intensity/tool/artifact differences are task-driven, not personality.

- **Pure_spectrum_Q is not Fable.** It was built with 8,337 Opus-4.8 + 5,817 Opus-4.7 edits and **zero Fable**. It is excluded entirely; any analysis treating it as Fable would be wrong at the source.

- **No Opus corpus for the communication dimension.** The reasoning/communication transcripts here are Fable-only. The Fable-internal findings (terse mid-stream, verbose at seams, options-then-pick) are well grounded; any "more compact than Opus" phrasing in that dimension is editorializing the prose-character numbers in §9, not a measured per-message comparison of these specific transcripts.

- **Citation line numbers drift.** Across the verified findings, several cited line anchors are off by one to a few lines (e.g. the "25+ junk nodes" State block is at prose.md:627, not 629–633). Every *snippet* was located verbatim; trust the text over the exact line number.

- **Single-session-per-repo sample.** This profiles a small number of autonomous runs. The fingerprint in §1 is consistent and mechanically checkable, but n is small; treat it as a high-confidence sketch, not a population statistic.
