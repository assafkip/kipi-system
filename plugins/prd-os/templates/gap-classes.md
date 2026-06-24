# Recurring gap classes

Defect shapes that repeatedly ship past review on features that scale or touch
sensitive data. Each is a PATTERN, not a one-off: the rule generalizes, the
catch is how to verify it next time. The PRD-review rubric checks a PRD's design
against these; the diff-review (kipi-dsse adversarial review) checks a diff for
them; the fable-discipline checklist is how you build so you don't introduce
them. Same list, three moments.

This list is general by construction. It carries no product specifics. Add a
class when a real defect recurs across more than one feature.

## Scaling / persistence

1. **In-memory cap is not a disk or IO bound.** A new append-only store ships
   compaction AND a bounded read in the SAME change. A memory cap bounds memory,
   not the file and not read cost.
   Catch: "what bounds the file, and what does a read cost at 10,000 records?"

2. **Filter before the expensive per-item work, not after.** Apply search/filter
   to the cheap key set before enrichment, so cost scales with the filtered set,
   not the whole catalog.

3. **Extend, do not reshape.** Add capability with new params (default off) and
   new data in a header or new field. Do not break an existing response body that
   has consumers. Backward compatibility is a feature.

4. **Persistence is a no-op if the data path is ephemeral.** A persistence
   feature is not done until the path is on a durable mount in the deploy target.
   Catch: verify the deploy (volume/mount), not just the code.

5. **Copying an existing pattern inherits its latent flaws.** A new feature built
   on an existing pattern carries that pattern's bugs at higher volume. Confirm
   the pattern you copy is actually safe at the new scale.

6. **Bound before you consume, on boot too.** Compaction must run before the
   boot-time whole-file read, or a restart still pays the unbounded read once.

## Security

7. **The redaction boundary is not the response boundary.** Anything that
   augments or mutates the payload AFTER the redaction point re-adds what the
   boundary removed. Redact at the egress edge, or make every post-serializer
   mutation idempotently re-redact.

8. **A UI/view hide is not an access-control block.** Enforce state (archived,
   retired, blocked) at the ACTION endpoint, on every reachable path (direct API,
   CLI, replay), not only the happy-path list view.

9. **A gate fails CLOSED; a filter may fail OPEN.** The same check has opposite
   correct failure modes: a launch/action gate must refuse when it cannot verify
   (e.g. corrupt store -> 503); a list filter may return empty. Do not reuse one
   helper for both.

10. **Classify exposure by recipient and necessity before masking.** "Leak" vs
    "by design" depends on who receives it (authorized?) and whether the workflow
    needs it. A security fix that breaks the core function is not a fix. Lock the
    boundary that matters (passive / persisted / log surfaces carry no raw
    identifier; the authorized active view may), not every appearance of a value.

11. **What you persist outlives the request.** Persist a redacted, whitelisted,
    JSON-safe projection, never the raw in-memory object. Writing raw makes PII
    durable on the volume and in any future export.

12. **Hiding state must not bury an open obligation.** Before you hide or suppress
    a thing, ask whether hiding it also hides work someone still owes (pending
    review, an SLA). If yes, block the hide while the work is open; do not hide
    the work.

## Correctness / concurrency

13. **A new flag/field must reach EVERY reader of that store.** Readers that go
    through a canonical/replay view inherit it for free; raw readers must each be
    patched. Enumerate them and ask "what else reads this?" until the answer is
    nothing.

14. **Overloading an existing field poisons its existing consumers.** Reusing a
    field for a new purpose changes its meaning for everything that already reads
    it. Audit every reader of that field.

15. **Check-then-mutate on shared state is not atomic.** Put check + mutate under
    one lock. For file compaction, use a SEPARATE stable lock file, not a lock on
    the file you are about to replace. Keep a consistent lock-acquisition order.
    Guard shared counters.
    Catch: write the N-thread reproducer first; it fails loudly before the lock.

16. **A liveness/health endpoint must never 500 on one bad data row.** Health
    paths are best-effort and per-line tolerant. Skip the bad line, keep serving.

17. **Single-source the version/identity and lock it with a test.** One source of
    truth for the release version; everything else derives from it; a test asserts
    they match so they cannot drift again.

18. **Global mutations leak across tests.** Anything that mutates process-global
    state (env via a dotenv load, module globals) needs symmetric setup AND
    teardown isolation (snapshot/restore, or clear both ends). monkeypatch does
    not undo a direct `os.environ` write.

## Cross-cutting (the meta-classes)

19. **A cross-cutting invariant needs an explicit written scope, or it never
    converges.** When a state must be honored "everywhere," write down what
    "everywhere" IS and IS NOT. An unbounded "hide/honor it everywhere" expands
    one surface per round forever. The boundary is the deliverable.

20. **A guard test must enumerate its targets from the system.** A test that
    protects a cross-cutting property derives its targets by introspecting routes
    / registries, with carve-outs as an explicit, verified allowlist. A
    hand-maintained list omits the surface that leaks. Then a new surface is
    covered the moment it exists, and an unclassified one fails loudly.

21. **If a bug class recurs, fix the STRUCTURE, not the next instance.** When the
    same class reappears across rounds, stop patching instances. Scope the
    invariant (19) and make the guard self-enumerating (20). Convergence comes
    from changing the fix, not from running more rounds.

## Wiring / completeness

22. **A field/state written but never read is dead wiring.** A new model field,
    config key, or return value that is populated but has no non-test consumer
    ships a write-only artifact: an audit trail nothing displays, a dead
    override interface, an unused column. The producer's own references (the
    field set BY NAME at construction) mask it from a name search; only an
    attribute/subscript READ outside tests counts as a consumer. Dynamic access
    (`getattr(obj, f"...")`) and serialization (`model_dump`) defeat a literal
    grep, so this is a REVIEW lens, not a deterministic gate (RCA 2026-06-24:
    two write-only fields shipped in one PRD, each "tested" only by a test that
    asserted it was written).
    Catch: for each field / key / return value added in the diff, name the
    production code that READS it and where it is SURFACED. If the only reader is
    a test, it is dead — consume it, surface it, or delete it. The deterministic
    sibling (every created allowed_file is git-tracked) is enforced at issue
    close by the wiring contract; this judgment half is the review's job.
