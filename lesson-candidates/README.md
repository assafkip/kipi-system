# lesson-candidates/ — the HELD queue + auto-learn ledger (skeleton-only, NOT fanned)

The cross-instance learning loop is autonomous: `lessons-daily.sh` (launchd, daily 06:00) distills
every instance's new RCA into a HOW-only lesson, runs it through the fail-closed client-data gate
(`lessons_scrub.py`), publishes the clean ones to `q-system/lessons/`, propagates to the fleet via
`kipi update`, and Slacks a summary. The founder does nothing on the happy path.

This directory holds the two things that must stay skeleton-side:

- `held-<hash>.md` — a lesson the gate could NOT clear (deterministic scrub left a client-data
  signal, OR the LLM semantic pass flagged a residual real entity). It was NOT published. Read it,
  scrub by hand and move to `q-system/lessons/` if worth keeping, or delete. These are the only
  human-in-the-loop items, and they are the SAFE ones (held, never leaked).
- `.processed.json` — the ledger of source RCAs already seen, so each learning is processed once
  (idempotent daily runs).

Why here and not in q-system/: this dir is at the repo ROOT, so `kipi update` never fans it to
instances. Held lessons + provenance stay skeleton-only by construction.

Manual one-shot: `kipi lessons-run`. Preview without writing: `python3
q-system/.q-system/scripts/lessons-distill.py --dry`.
