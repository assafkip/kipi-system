Closes ASK-291.

The direct shell write path into `.claude/` is now closed. Both guard scripts
landed in PR #64 and neither was wired anywhere; the arming proposal existed and
could not be applied. Both layers are now armed on **both** surfaces
(`.claude/settings.json` **and** `settings-template.json`) and both are proven to
fire by a reproducer, not by a grep.

## The three defects in the issue

**1. Layer 1 wedged agent worktrees (`sp-2b9372f6`).** `expand()` resolves every
bare argv token against cwd, so from a session in `.claude/worktrees/<name>/` the
literal word `commit` in `git commit` became `<cwd>/commit`, "inside .claude", and
was blocked. `hits_claude()` now skips a path whose first component under
`.claude/` is in `EXCLUDED_DIRS` — the same set Layer 2 refuses to watch. The
exclusion requires something *under* the scratch dir, so `.claude/worktrees`
itself stays protected. A new test pins `L1.EXCLUDED_DIRS == L2.EXCLUDED_DIRS`:
two layers disagreeing about what the protected set *is* is worse than either
bound alone.

**2. Layer 2 aimed at a matcher that cannot see Bash (`sp-b100a0e9`).**
Retargeted from the `Edit|Write` group to `Edit|Write|MultiEdit|Bash`, the only
PostToolUse group that sees a Bash tool call. `probe_tripwire2.sh` proves it
structurally: it parses settings.json, finds the group that *carries* the hook,
and asserts **that group's** matcher lists Bash. A grep for the filename passes on
the broken version; this cannot.

**3. Unappliable as written (`sp-42b92801`).** Both surfaces are now edited and
`requires.template_pairs` asserts the pair. Two further reasons v1 could never
apply, found by running it against a copy rather than reading it: `notes` is not
in the engine's `ALLOWED_PROPOSAL_KEYS`, and `template_pairs` is matched against
raw file *text*, where the command's quotes are JSON-escaped.

Anchors are no longer transcribed at all. `build_proposal.py` slices them
byte-exact out of the live files and refuses any that is not unique — both v1
anchor defects were transcription.

## What arming actually broke, and what it cost

The interesting half. Three separate false blocks on the **legitimate** path, each
found by running the armed guards rather than reasoning about them. All three are
the same acceptance criterion from the issue: a guard that blocks the legitimate
path too is a different outage.

- **The applier did not register its own writes.** The first live apply was
  auto-reverted one tool call later by the guard it had just armed
  (`SECURITY: unsanctioned .claude/ change … | reverted 1`), leaving the runtime
  unarmed while the unwatched template kept the change — the exact split state
  `settings-template-sync-check` calls red. The tripwire already exposed
  `--register` (its own docstring calls it "the sanctioned-apply hook"); nothing
  called it. Scoped to what the run wrote, never a blanket `--baseline`.
- **`git add` was treated as a write.** It writes the index, not the working
  tree, so the founder could arm the guards and then never commit the arming.
  `checkout`/`restore` stay blocked, pinned by the probe.
- **The statement/stage splitters were quote-blind.** A commit message describing
  the change (quoting the guard's own stderr, which begins `.claude/ wires every
  hook…`) was shredded into fake statements. Split is now quote-aware, and a
  token carrying a newline is a text payload rather than a path candidate. Named
  gap with Layer 2 as backstop; interpreter code strings and redirects match the
  raw segment and are unaffected, pinned by two new multi-line ATTACK cases.

## `kipi update` interaction — measured before rollout

Layer 2 auto-reverts and `kipi-update.sh:1367` rewrites `.claude/` from the
template on 23 machines. `probe_update_interaction.sh` phase 1 **confirms the
outage**: the next tool call reverts the update, silently, after the updater
already printed OK. Fixed with a post-write re-baseline — `kipi update`
propagates the skeleton's git HEAD, the same reviewed provenance the tripwire's
own `attributable()` already sanctions. Phase 3 holds the other end: a tamper
*after* the re-baseline is still caught and reverted.

## Evidence

Every reproducer carries a negative self-test (a case proving the harness can
fail). All were rebuilt in-repo — the originals were never committed.

| Command | Result |
|---|---|
| `python3 q-system/output/claude-changes/repro/probe_guard.py` | **22/22** (9 ATTACK still exit 2) |
| `bash q-system/output/claude-changes/repro/probe_tripwire2.sh` | **8/8** |
| `bash q-system/output/claude-changes/repro/probe_apply_on_copy.sh` | **8/8** |
| `bash q-system/output/claude-changes/repro/probe_update_interaction.sh` | **8/8** |
| `bash q-system/.q-system/scripts/test/test-claude-write-path.sh` | **83 passed, 0 failed** (was 78) |
| `bash q-system/.q-system/scripts/test/test-apply-claude-changes.sh` | **122 passed, 0 failed** |
| `python3 q-system/.q-system/scripts/settings-template-sync-check.py --check` | exit 0 |

Observed RED before green on both fixes: `probe_guard.py` 11/16 → 16/16 on the
worktrees wedge; `probe_tripwire2.sh` phase 1 failed on both surfaces before the
retarget; `probe_apply_on_copy.sh` phase 5 failed before the applier registered.

The apply is real, not simulated:

```
OK applied arm-claude-write-path-guards: 4 edit(s), 2 file(s),
hooks 39->41, gates held, tripwire updated
```

Both layers are live in this session: Layer 2 reverted the first (unregistered)
apply, and Layer 1 blocked `git add` and `git commit` until each false block was
fixed. The commits on this branch were made through the armed guards.

## Out of scope, respected

PR #68 (`sana/safe-replace-claude-changes`) and its `replace` capability are
untouched. The write route is not widened: this only turns on a guard that
already existed, plus the re-baseline calls that keep the sanctioned route
working.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
