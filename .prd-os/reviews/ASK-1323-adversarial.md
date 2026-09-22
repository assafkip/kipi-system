# ASK-1323 adversarial review

Reviewer: Claude (adversarial), 2026-09-06. Worktree: `/Users/assafkipnis/.config/kipi/worktrees/ask-1323` (detached, HEAD f8bcaf41 + the working-tree diff). Nothing committed, no tracked file edited. Throwaway drivers under `scratchpad/adv/`.

## VERDICT: request-changes

One blocker, three minors, three nits. The change itself does what the DoR says on every path I could drive. What stops it landing is a red suite in the same tests directory that the DoR's `required_checks` do not run: `test_consulting_board.py` still drives `collect_mail` with the model-era `{"threads": [...]}` runner and 4 of its tests fail against the new collector, two of them asserting the sender|subject collapse this diff deliberately removed. The file is outside the diff and outside `allowed_files`, but the change cannot land green without it, which the brief says is a blocker even when the fix is elsewhere.

## What I ran, and what came back

### Suites (as instructed)

```
python3 -m pytest q-system/.q-system/tests/test_morning_brief_mail.py q-system/.q-system/tests/test_morning_brief.py q-system/.q-system/tests/test_consulting_board.py -q -p no:cacheprovider
  -> 4 failed, 212 passed in 1.48s
  FAILED test_consulting_board.py::TestRound4::test_the_real_mail_producers_age_form_is_volatile
  FAILED test_consulting_board.py::TestTwoThreadsAreNeverOneRow::test_two_indistinguishable_threads_become_one_row_that_SAYS_two
  FAILED test_consulting_board.py::TestTwoThreadsAreNeverOneRow::test_a_real_thread_id_still_wins_and_stays_stable
  FAILED test_consulting_board.py::TestTwoThreadsAreNeverOneRow::test_both_rows_reach_the_board
q-system/.q-system/tests/test_board_rows.py            -> does not exist; skipped and saying so
test_morning_brief_mail.py alone                       -> 18 passed
test_morning_brief.py alone (KIPI_CONSULTING_ROOT=/nonexistent too) -> 63 passed
KIPI_CONSULTING_ROOT=/nonexistent test_consulting_board.py -> 4 failed, 131 passed
   (same 4; the assertion text changes from "ledger JSON is not a list" to
    "consulting ledger not found at /nonexistent/... (set KIPI_CONSULTING_ROOT)")
```

The DoR's two `required_checks` are green. The repo's suite is not.

### Attack 1: will the ten stale Gmail rows actually be archived on the first healthy run?

Driver `adv/attack1_healthy_scope.py`: loads the worktree's `consulting_board.py`, `morning-brief.py`, `board_rows.py`, calls `consulting_board.buckets(NOW, sources, _paths(tmp))` with a tmp root (every card file absent, so `card_error` is set and the inbox loop still runs).

```
empty healthy   inbox:Gmail healthy? True   inbox rows=0
error           inbox:Gmail healthy? False  inbox rows=1   (the COULD NOT READ row)
absent key      inbox:Gmail healthy? False  inbox rows=0
new rows        keys: ['mail:19ff4af34dbc0f56'] healthy? True  scope on row: inbox:Gmail
_FALLBACK_KEY matches a hex thread id?             False
_FALLBACK_KEY matches an OLD sender|subject key?   True
old row scope read back: 'inbox:Gmail' -> in healthy set: True
```

Trace: `buckets()` line 752 `if not got: continue` sees the 2-tuple `([], None)` as truthy, `err` is None, `any(_FALLBACK_KEY.match(...) for r in [])` is False, so `healthy.add("inbox:Gmail")` runs on an EMPTY answer. New rows and old rows both carry `scope=inbox:Gmail` (the label lives in consulting_board, which the diff does not touch), `board_rows._scope_of` reads it back off Notes, and `paint()` line 597 archives an old page whose id is not in `wanted` and whose scope is in `healthy`. A thread that still needs him keeps its row because the key is the same Gmail thread id the old prompt was asked to copy verbatim. Result: the Outcome is achievable by this diff. Two observations outside the diff: (a) board_rows must be ON (token file present) for any archive to happen; (b) `launchctl list` shows `com.kipi.morning-brief` installed and `com.kipi.morning-inbox` NOT installed, so "the next healthy run" is 07:00 via `~/.config/kipi/bin/morning-brief-run.sh`, which fast-forwards `~/projects/kipi-system-main` to origin/main and execs `/usr/bin/python3 morning-brief.py`. That is another reason the red suite is a blocker: the code reaches production only through origin/main.

### Attack 2: the login shell, quoting, exec, timeout, token

```
env -i HOME=$HOME USER=$USER LOGNAME=$USER PATH=/usr/bin:/bin /bin/zsh -l -c 'echo "token:${NOTION_TOKEN_ASK:+set}"'   -> token:set
env -i ...                                                     /bin/zsh -c    'echo "token:${NOTION_TOKEN_ASK:+set}"'   -> token:set   (so it comes from ~/.zshenv, not a login-only file)
env -i ... /usr/bin/python3 ledger.py needs-reply --json (no shell at all)  -> exit 1, stdout 0 bytes, stderr "NOTION_TOKEN_ASK is not set. Refusing to run. ..."
env -i ... /bin/zsh -l -c 'exec /usr/bin/python3 -c "...write(\"X\")"' | xxd -> exactly 0x58; the login shell writes nothing to stdout or stderr
```

Driver `adv/attack2_shell.py` (outside pytest so `run_ledger` is not refused), script at `.../it's a dir/with space/led ger.py`:

```
quoting err: None
argv round-trip: True ['needs-reply', '--json', 'a b', "it's", 'say "hi"', '$HOME']   ($HOME NOT expanded)
token visible inside the child: True
child ppid == this pid (exec replaced zsh): True  pid 91883 ppid 91881 me 91881
timeout err: ledger timed out after 1s (1.0s)
child still alive after timeout? False
under env -i, token reaches the ledger child: True
nonzero: None | ledger exit 1: NOTION_TOKEN_ASK is not set. Refusing to run.   (last stderr line survives)
```

`exec` works: zsh is replaced, so `subprocess.run`'s timeout kills the ledger itself and leaves no orphan. Passes.

### Attack 3: can anything precede the JSON on stdout?

- `ledger.py` lines 80-1672 (every helper on the `needs-reply` path: `load_config`, `notion_token`, `_notion_request`, `_http`, `query_all`, `read_ledger`): `awk 'NR>=80 && NR<=1672 && /print\(|sys.stdout|warnings\./'` -> no matches. `load_config` is `open` + `json.load`. `notion_token()` raises `SystemExit(str)`, which is exit 1 to stderr, i.e. the non-zero branch.
- `cmd_needs_reply` with `--json` prints exactly one `json.dumps(rows, indent=2)` and returns. `main` returns `args.func(args) or 0`.
- Real CLI, read-only, under the launchd shape: `env -i HOME USER LOGNAME PATH=/usr/bin:/bin /bin/zsh -l -c "exec /usr/bin/python3 .../ledger.py needs-reply --json"` -> exit 0, stdout 3 bytes, first byte `[`, last non-whitespace byte `]`, `json.loads` ok (list, 0 rows), stderr 0 bytes. Row content was not printed.
- Encoding: `json.dumps` default `ensure_ascii=True`, so a non-ASCII subject cannot produce a non-ASCII byte for the parent's locale decode under a bare env. Passes.

### Attack 4: the interpreter

- `morning-brief-run.sh` execs `/usr/bin/python3`, which is 3.9.6. Homebrew `python3` on PATH is 3.14.6; either becomes `sys.executable`.
- `/usr/bin/python3 ledger.py needs-reply --help` -> exit 0 (module imports and argparse under 3.9, no network).
- `/usr/bin/python3 -c "from zoneinfo import ZoneInfo; print(ZoneInfo('America/Los_Angeles'))"` -> `America/Los_Angeles`.
- `ledger.py` header: "stdlib only, on purpose". Nested imports (`slackio`, `sales_rules`) sit in other subcommands. `sys.executable` is correct. Passes.

### Attack 5: timeouts

`LEDGER_TIMEOUT_S=60 < FIXED_BUDGET_S=240.0`: the subprocess fires first and returns `([], "ledger timed out after 60s")`; the guard's backstop returns `([], "mail timed out (240.0s)")`. Neither loses the string. With `KIPI_BRIEF_LEDGER_TIMEOUT=600` the order inverts (measured: `subprocess fires first: False`), the guard abandons the daemon thread at 240s and the ledger child runs on until 600s. Nothing pins the pair, unlike `BUDGET_S < COLLECT_BUDGET_S` which test_consulting_board pins. Minor.

### Attack 6: the tests

- New file: `instance` fixture builds everything under `tmp_path`; `run_ledger` refuses under pytest and `test_run_ledger_refuses_under_pytest` asserts it. `Path.is_file` spy across the whole run: zero stats under `~/projects/consulting` from `test_morning_brief_mail.py` or `test_morning_brief.py`.
- `monkeypatch.delenv("PYTEST_CURRENT_TEST")` in the two `run_ledger` tests: ordered runs `[login_shell, nonzero_exit, refuses]` -> 3 passed and `[refuses, login_shell, refuses]` -> passed; no leak.
- Wrong-reason check: `test_mail_collector_reports_a_ledger_failure` asserts `"timed out" in error` where the runner itself returned "ledger timed out", so it proves pass-through only, which is what the docstring claims; acceptable. `test_the_model_read_is_gone_from_the_mail_section` uses `"d)" not in label`, a substring check that would also fire on "(unread)"; nit.
- The spy DID catch live-path stats: 5 `is_file` calls on `/Users/assafkipnis/projects/consulting/q-consult/email-watch/ledger.py` from the 4 failing `test_consulting_board.py` tests (they call `brief.collect_mail` with no sibling swap, so `ledger_script()` resolves `consulting_root()` to the founder's real checkout). Their failure text is machine-dependent (see the two runs above).
- `swapped()` uses `stem.rstrip(".py")`, a character-set strip; it happens to work for "consulting_board.py" because 'd' is not in the set. Nit.

### Attack 7: old-code residue

- Scripts: `grep -rn 'MAIL_PROMPT\|MAIL_TOOL\|MAIL_WINDOW_DAYS\|age_hours' q-system/.q-system/scripts/` -> nothing. `search_threads`/`run_claude` absent from the Section 2 slice (pinned by the new test). SECTIONS label is `"Mail needing an answer"`.
- Tests: `test_consulting_board.py` lines 527-528, 678-680, 699-701, 707-709, 715-717 still build `{"threads": [...]}` payloads with `from`/`age_hours` (the 4 failures).
- Docs inside the diff's own file that now contradict the code: line 39 "Why two `claude -p` calls and not one" (there is one), line 613 "Calendar and mail shell `claude -p` under CLAUDE_TIMEOUT" (the FIXED_BUDGET_S derivation), lines 776-778 "calendar and mail shell `claude -p` ... mail alone needs more than 20s". The file's own rule: "A number written twice is a number that will disagree." Minor.

### Attack 8: `--inbox-only` and `--dry-run`

Driver `adv/attack8_main_paths.py` (every collector stubbed, `_optional_module` -> None, `route_engineering` stubbed):

```
--inbox-only             healthy empty  exit=0  ['[mail] 0 row(s)']
--inbox-only             two rows       exit=0  ['[mail] 2 row(s)']
--inbox-only             error          exit=1  ['[mail] COULD NOT READ: ledger exit 1: NOTION_TOKEN_ASK is not set']
--inbox-only --dry-run   (same three)   exit=0/0/1, same lines
--dry-run                all three      exit=0  ['*Mail needing an answer*', '[dry-run] nothing sent, no receipt written']
```

Unchanged contract: `--inbox-only` is 1 only on a mail/groupme/board error, `--dry-run` returns 0 before `degraded` is consulted. Passes. Note the ledger IS executed under `--dry-run` (a read-only Notion query), the same class of side effect the old `claude -p` call had.

## Findings

### F1 (blocker) `q-system/.q-system/tests/test_consulting_board.py` lines 520-533 and 668-719: four tests drive the model-era producer and fail against the new collector

`TestRound4::test_the_real_mail_producers_age_form_is_volatile`, `TestTwoThreadsAreNeverOneRow::{test_two_indistinguishable_threads_become_one_row_that_SAYS_two, test_a_real_thread_id_still_wins_and_stays_stable, test_both_rows_reach_the_board}` call `brief.collect_mail(None, lambda p, t: (json.dumps({"threads": [...]}), None))`. The new collector parses a JSON list, so the dict answers "ledger JSON is not a list" and every assertion fails (4 failed, 212 passed; same 4 under `KIPI_CONSULTING_ROOT=/nonexistent`). Two of them assert the sender|subject collapse into "N threads, same sender and subject", which this diff removes on purpose (the ledger always carries a thread id), so they cannot be patched to the new shape; they have to be replaced by the statement that now holds (one row per ledger row, key = `mail:<thread_id>`, a row without an id fails the whole read, which `test_morning_brief_mail.py` already pins). The other two can be re-pointed at a ledger-shaped runner with the `instance`-style sibling swap. As they stand they also stat the founder's live `~/projects/consulting/.../ledger.py` (5 stats measured). The DoR's `required_checks` do not run this file, so the author's gate is green while the repo suite is red; `morning-brief-run.sh` only ever runs origin/main, so nothing here reaches the 07:00 job until this is fixed. Suggested fix: rewrite the four against the ledger contract (or delete the two collapse tests with a note pointing at `test_rows_are_the_ledgers_rows_keyed_by_thread_id` and `test_one_bad_row_fails_the_whole_read`), and add `python3 -m pytest q-system/.q-system/tests/test_consulting_board.py -q` to the issue's `required_checks`.

### F2 (minor) `q-system/.q-system/scripts/morning-brief.py` lines 39-52, 613, 776-778: three doc blocks still say mail shells `claude -p`

The module docstring's "Why two `claude -p` calls and not one", the `FIXED_BUDGET_S` derivation comment, and `collect_all`'s docstring all describe the mail section as a `claude -p` call under `CLAUDE_TIMEOUT`. After this diff the mail bound is `LEDGER_TIMEOUT_S`, and `FIXED_BUDGET_S = CLAUDE_TIMEOUT + 60` is now justified by calendar alone. Shown by `grep -n "claude -p\|Calendar and mail\|mail shell" morning-brief.py`. Suggested fix: reword the three to name calendar as the one remaining model call and `LEDGER_TIMEOUT_S` as mail's own bound.

### F3 (minor) `q-system/.q-system/scripts/morning-brief.py` line 247: `LEDGER_TIMEOUT_S` is env-tunable above `FIXED_BUDGET_S` with no pin

`KIPI_BRIEF_LEDGER_TIMEOUT=600` makes `LEDGER_TIMEOUT_S < FIXED_BUDGET_S` False (measured). Then `_guarded` abandons the mail thread at 240s and reports "mail timed out", while the ledger child keeps running to 600s; the section's error string is intact but the "subprocess fires first" property the FIXED_BUDGET_S comment relies on is silently gone. Suggested fix: `LEDGER_TIMEOUT_S = min(int(env), int(FIXED_BUDGET_S) - 1)` or a test in `test_morning_brief_mail.py` asserting `brief.LEDGER_TIMEOUT_S < brief.FIXED_BUDGET_S`, mirroring the `BUDGET_S < COLLECT_BUDGET_S` pin.

### F4 (nit) `q-system/.q-system/scripts/morning-brief.py` lines 232-236: the login-shell rationale names the wrong file

"bare env + `zsh -l` prints `[]`; bare env alone prints the refusal" is true as measured, but the token is exported by `~/.zshenv` (set under `zsh -c` and `zsh -l -c` alike under `env -i`), so `-l` is not what carries it. Harmless, and matching `crm-run.sh`'s `#!/bin/zsh -l` is a fine reason to keep it. Suggested fix: say ".zshenv, which every zsh reads" so the next person who reorganises the dotfiles (enrich-run.sh records that happening twice in one day) knows which file the job depends on.

### F5 (nit) `q-system/.q-system/tests/test_morning_brief_mail.py` line 62: `stem.rstrip(".py")` is a character-set strip

Works for "consulting_board.py" only because 'd' is outside the set. Suggested fix: `stem[:-3] if stem.endswith(".py") else stem`, or reuse `_optional_module`'s own normalisation.

### F6 (nit) `q-system/.q-system/tests/test_morning_brief_mail.py` line 224: `"d)" not in section[1]`

A two-character substring stands in for "carries a day window". Suggested fix: `assert not re.search(r"\(\d+d\)", section[1])`.

### Observation, no finding

A ledger row with `status == needs_reply` and an empty Thread ID title (the `seed-registry-rows` subcommand creates blank rows) fails the whole read with "a ledger row has no thread id" until the Notion row is fixed. That is the documented fail-closed choice ("half a list would archive the other half's rows"), and the refusal names itself in the brief; recorded here only so the first time it fires nobody diagnoses it as a shell problem.

## Verdict

request-changes. F1 is the only blocker: the diff's own contract holds on every path driven above, and the ten stale rows will be archived on the first healthy 07:00 paint once it is on origin/main, but four tests in the same directory are red against it and the DoR's checks do not run them.
