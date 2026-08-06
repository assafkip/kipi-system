# Last handoff — 2026-08-06

Tracking **ASK-402** (related: ASK-363). All three PRs merged to main [verified: `gh pr view 110|111|112 --json state,mergedAt` — all MERGED].
Numbers below carry their source on their own line; anything marked `imported`
came from Sana's report and was NOT re-run by me.

## What this session was

A research doc on "adversarial AI code review" was pasted for comparison against
prd-os. My first review concluded "we already have that" — wrong, because it
compared architectures by READING. The founder pushed back: his own
adversarial-tester prompt had previously found a long list of real breakage
[provenance: explicit_statement]. Everything below came from EXECUTING the
system in virgin repos instead.

## Shipped

| PR | What |
|---|---|
| #111 | **P0 data-loss.** `kipi update`'s rsync `--delete` could remove `my-project/`, `memory/`, `canonical/`: the anchored excludes only line up when the destination IS the instance's q-system dir. `kipi-update-deletion-guard.py` reads what rsync actually plans to delete and refuses. [verified: ran a real `kipi update` against a fixture — without the guard `my-project/current-state.md` and `memory/last-handoff.md` were DESTROYED; with it, refused and intact] |
| #110 | prd-os delivers what it promises: `/prd-os-init` writes the `.gitignore` entry it claimed, `archive` consults spillover, the "portable core" stops writing `q-system/` into any repo, receipts are computed not stamped, `verify` cross-checks by default. Plus `test_virgin_repo_lifecycle.py`. [verified: most new checks RED against the pre-change tree] |
| #112 | `grep -c ... \|\| echo 0` is not a zero-safe count [verified: `grep -rn 'grep -c .* \|\| echo 0' test/*.sh`]. Plus `spillover reclassify`. |

Suite green at merge, validator ALL PASS [provenance: imported — Sana's figure from its post-merge run; I did not re-run it].

## The class the founder named <!-- pin -->

**Code that RECORDS a claim it never COMPUTED** [provenance: explicit_statement].
Named after `mark verified` was shown to succeed with zero checks run
[verified: ran `mark verified|reviewed|findings_triaged` in a virgin repo, exit 0
each, no work done]. Rule adopted: *there is no standalone "mark it done" verb —
whoever does the work writes the receipt, and the receipt carries the evidence.*
This contradicted `q-system/CLAUDE.md` rule 3 (enforcement requires executable
code), which is why it mattered.

## Open, nothing blocking them

- Most spillover items sit at the `minor` DEFAULT — untriaged, not assessed; only a handful block [verified: `prd_runner.py gates run`, this session]. Sana's call: triage needs a RULE (archived-source + fixed-shape bulk-triaged, the rest read), not a hand pass. Its own issue.
- **`sp-80a93612`** — Codex hit its usage limit mid-review, resets in a few days [provenance: imported — Sana]. The last rounds ran on the Opus fallback: same model family as Sana, correlated blind spots. Codex never saw `_spillover_lock`, `_print_reclassifications`, or the rank/degrade work. Re-run when credit returns.
- Minor items from Sana's review of the prd-os PR, none hand-cleared [provenance: imported — Sana; not independently counted].
- **Stale worktree** `.claude/worktrees/deletion-guard` — needs pruning. A
  delete, so founder-gated.

## Working agreement established this session <!-- pin -->

[provenance: explicit_statement — all four stated by the founder in-session]

- **Sana owns the build.** Engineering decisions route to Sana, never the
  founder. Founder authorizes publish / spend / delete only.
- **Do not stop at a boundary.** Repeatedly, an obstacle to ONE part was mistaken
  for an obstacle to the whole ("design-level", "blocked on primary checkout",
  "kipi check is blocked", "one thing left" against the open ledger). Each
  collapsed when pushed on.
- **Do not commit to a branch under active review.** One such push cost Sana a
  reviewer refusal and a wasted round.
- **Do not re-derive.** The severity plan I proposed already existed, approved, in `.prd-os/prds/prd-spillover-current-state*.md` [verified: read it]. Search that directory first.

## The lessons <!-- pin -->

**A test that passes proves nothing until you have watched it fail.** Observed
across two agents in one day [verified: each item below was reproduced by
mutation, not inferred]:
- An end-to-end test passed with the guard deleted (the instance was skipped
  earlier for an unrelated reason).
- An unknown-id test asserted only a nonzero exit — removing the guard made
  `dict(None)` raise TypeError, also nonzero, so it passed while the behaviour
  was a stack trace.
- A reason check was satisfied by argparse firing first, so deleting the check
  changed nothing.
- A tamper test changed a file's LENGTH, so a `hash != x OR bytes != y` guard
  passed on the byte half and the hash half never ran [provenance: imported].
- A mutation harness reported all-survived because an unquoted `-k` meant "no
  tests ran". A harness that cannot run the tests reports perfect survival.

**A membership set is not a scale** [provenance: imported — Sana]. It built a
severity rank from `NONBLOCKING + BLOCKING` assuming the tuples encoded order.
`blocker` is the first entry of its own tuple, so a demotion read as a raise.

**A writer with no reader is the same defect one level up** [provenance:
imported — Sana]. `reclassify` recorded `reclassified_from` and
`reclassify_reason` and nothing displayed them — the one action that can stop the
gate blocking appeared in no report.

**Components that survive attack enumerate their own limits.** `fable-discipline-lint`
(CATCHES/SKIPS/MISSES), `prd_map` ("facts-only"), the judgment compiler
("tamper-EVIDENT, not tamper-proof") [verified: probed each; my expectations were
wrong, not theirs]. Every component that failed claimed something in prose that
no code did.

## Counts

Tallies of defects fixed, false leads killed, and self-inflicted bugs caught are in the session transcript and the PR bodies [provenance: inferred — my own running count, never recomputed from a ledger; do not quote as measured].
