# Worked examples

Two real before/afters. The point of both: a check that can fail catches what a
"looks right" review ships.

---

## Example 1: the hook catching a live-data test

### The test someone writes (looks fine, ships)

```python
def test_promotion(self):
    db_path = "app/data/prod.db"          # the real database
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM entities")  # against production
```

A reviewer skims this and nods. It runs. It also mutates the live database every
time the suite runs. The damage shows up later, as missing rows nobody can explain.

### What the hook does

On the Edit/Write, the paired hook fires and blocks:

```
build-craft-lint: 1 test-isolation violation(s) in test_promotion.py:
  line 2: test names a live data path "app/data/prod.db"
Tests must use a temp copy, a tempfile, or :memory: ... Fix it, or add
# build-craft-lint-skip to bypass.
```

### The fix

```python
def test_promotion(self, tmp_path):
    conn = sqlite3.connect(str(tmp_path / "copy.db"))   # isolated
    conn.execute("DELETE FROM entities")
```

The hook stays silent. Note it caught the path even though it was assigned to a
variable first, not written inside `connect(...)`. It also stays quiet on
`:memory:`, fixtures, and an audit test that only names the path in an assertion.

---

## Example 2: the negative self-test catching the hook's own bug

This is the rule "verify against a copy with a negative self-test" applied to the
hook itself. It is the reason the hook is trustworthy.

### What looked done

The first version of the detector passed its own self-test (six cases: live path
blocked, `:memory:` allowed, skip-marker honored, and so on). Green. It looked
done.

### The failable check that broke it

Instead of trusting green, the next step was to run it against a real test in an
actual codebase, and to feed it a violation written the way that codebase actually
writes paths:

```python
db_path = "investigations/data/prod.db"   # path in a variable
sqlite3.connect(db_path)                   # not a literal inside connect()
```

The detector returned exit 0. It missed it. The first version only matched a
literal sitting directly inside `connect(...)`, so the variable form slipped
through, which is the form most real tests use.

### The fix, then the proof

The detector was rewritten to flag the path in any assignment or call context,
then re-verified two ways: the self-test grew to eleven cases (the new forms now
blocked), and a scan across a real 221-test suite returned zero false positives.

### Why it matters

The six-case green said "done." The check that could fail said "no, you miss the
common case." A model reviewing its own output would have answered "looks right"
and shipped the blind spot. The failable check is the entire difference.
