# ASK-1323 standard review (senior staff engineer)

Issue: Morning brief: the mail section reads the CRM ledger's needs-reply, not a model over Gmail snippets.
Worktree: /Users/assafkipnis/.config/kipi/worktrees/ask-1323 (detached, HEAD f8bcaf41).
Reviewer scope: read-only on the worktree and on the consulting ledger file; the only file written is this one.

## What changed (from `git status` and `git diff` in the worktree)

```
 M q-system/.q-system/scripts/morning-brief.py      (198 lines: +143/-115 across the two files)
 M q-system/.q-system/tests/test_morning_brief.py
?? q-system/.q-system/tests/test_morning_brief_mail.py   (new, 238 lines)
?? .prd-os/issues/ASK-1323.md                            (the spec itself)
```

The scratch diff at `.../scratchpad/ask-1323.diff` differs from `git diff` only by carrying the untracked new test file, so the two agree.

Hunks in morning-brief.py, in order: `import shlex`; `MAIL_TOOL` removed; Section 2 replaced (`MAIL_WINDOW_DAYS`, `MAIL_PROMPT`, the model-backed `collect_mail`, the group/collapse logic gone; `LEDGER_TIMEOUT_S`, `LOGIN_SHELL`, `LEDGER_RELATIVE`, `run_ledger`, `ledger_script`, `_mail_line`, the ledger-backed `collect_mail` added); the `SECTIONS` mail label loses its interpolated window. Nothing outside Section 2 changed except that label and the import. Scope discipline holds against the DoR's three files.

## Commands run and their results

1. The three suites the brief named:

```
$ python3 -m pytest q-system/.q-system/tests/test_morning_brief_mail.py \
    q-system/.q-system/tests/test_morning_brief.py \
    q-system/.q-system/tests/test_consulting_board.py -q -p no:cacheprovider
FAILED q-system/.q-system/tests/test_consulting_board.py::TestRound4::test_the_real_mail_producers_age_form_is_volatile
FAILED q-system/.q-system/tests/test_consulting_board.py::TestTwoThreadsAreNeverOneRow::test_two_indistinguishable_threads_become_one_row_that_SAYS_two
FAILED q-system/.q-system/tests/test_consulting_board.py::TestTwoThreadsAreNeverOneRow::test_a_real_thread_id_still_wins_and_stays_stable
FAILED q-system/.q-system/tests/test_consulting_board.py::TestTwoThreadsAreNeverOneRow::test_both_rows_reach_the_board
4 failed, 212 passed in 1.51s
```

The two files the spec's `required_checks` name are green (every failure is in `test_consulting_board.py`). The failing four all drive the OLD producer: `runner = lambda p, t: (json.dumps({"threads": [...]}), None)` and then `brief.collect_mail(None, runner)`, asserting the sender|subject fallback, the "2 threads, same sender and subject" collapse row, and `[2h]` age volatility. The new collector calls `runner(argv, timeout)` and parses a JSON list, so those fixtures parse as "not a list" and return `([], error)`, and the assertions fail on empty rows (`AssertionError: []` at test_consulting_board.py:712).

2. Is that file on a gate? `.verify-suites` at the repo root names `q-system/.q-system/tests` as a suite. `q-system/.q-system/verify.sh` reads that manifest for both `--staged` (lefthook pre-commit) and `--full`; `.github/workflows/verify.yml` runs `bash q-system/.q-system/verify.sh --full` on every pull_request. So the four failures stop the commit door and the merge door as the tree stands.

3. The property that matters most, demonstrated rather than argued. Scratch probe `.../scratchpad/ask1323_archive_property.py` loads the modified morning-brief.py with a fake `consulting_board` whose `consulting_root()` is a tmp dir holding a stub `ledger.py`, injects the ledger runner, and pushes the result through the REAL `consulting_board.buckets` (tmp tree from the suite's `_tree`) and the REAL `board_rows.paint` with `existing_rows` and `_request` replaced in-process. Existing pages carry `scope=inbox:Gmail` in Notes, exactly as `_properties` has always written Gmail rows.

```
_FALLBACK_KEY.match('mail:19ff4af34dbc0f56') -> None  (healthy is not withheld)
--- EXIT 1  ledger printed []
    collect_mail -> rows=[] err=None
    healthy_scopes=['card', 'card:alarm', 'gtm', 'inbox:Gmail', 'myside', 'week', 'week:gtm']
    paint counts: archived=1 kept=0        archive PATCHes: ['/pages/p0']
--- EXIT 2  ledger timed out
    collect_mail -> rows=[] err='ledger timed out after 60s'
    healthy_scopes=['card', 'card:alarm', 'gtm', 'myside', 'week', 'week:gtm']
    inbox rows=[('Gmail:error', 'inbox:Gmail')]
    paint counts: archived=0 kept=2        archive PATCHes: []
--- EXIT 3  ledger printed one row
    collect_mail -> rows=[('acme  Re: x  [since 2026-09-02]', 'mail:19ff4af34dbc0f56')] err=None
    healthy_scopes=[..., 'inbox:Gmail', ...]
    inbox rows=[('mail:19ff4af34dbc0f56', 'inbox:Gmail')]
    paint counts: archived=1 kept=0 updated=1   archive PATCHes: ['/pages/p0']   (p1, the live thread, PATCHed in place)
--- EXIT 2b ledger exit 1 (token refusal)      archived=0 kept=1
--- EXIT 2c one row lacks thread_id            err='a ledger row has no thread id; ...'  archived=0 kept=1
ALL PROBES PASSED
```

So: `([], None)` marks `inbox:Gmail` healthy and the stale model-era row is archived; `([], error)` leaves `inbox:Gmail` out of `healthy_scopes`, keeps every row, and paints the one `Gmail:error` alarm row. The SCOPE LABEL is unchanged: consulting_board.py is untouched by this diff, its loop is still keyed `("mail", "Gmail")` (lines 751 to 800), so new rows are written under `inbox:Gmail`, the same string the old rows carry in Notes, and the healthy set names that same string. The old rows will be archived on the first healthy run, which is the whole issue. `_FALLBACK_KEY` (`^[^|]+\|`) cannot match a `mail:<hex>` key, so healthy is never withheld for a ledger row.

4. The chokepoint, unfixtured (this is what the `collect_all` tests in test_morning_brief.py actually hit on this machine):

```
$ PYTEST_CURRENT_TEST=probe python3 - <<EOF ... m.ledger_script(); m.collect_mail(None) ... EOF
ledger_script -> /Users/assafkipnis/projects/consulting/q-consult/email-watch/ledger.py | None
collect_mail(None) under pytest -> ([], 'run_ledger refused under pytest; inject a runner')
LEDGER_TIMEOUT_S = 60  FIXED_BUDGET_S = 240.0  COLLECT_BUDGET_S = 20.0
KIPI_CONSULTING_ROOT=unset
```

The real ledger is located (a read-only `is_file()` on the founder's instance path) and `run_ledger` refuses before any subprocess. No test in either file can reach the live Notion ledger. On a machine without the instance the same call returns `consulting ledger not found ...`; both are the error exit, and no engine test asserts on the mail error text via `collect_all` (lines 775, 795, 843 either monkeypatch the collector or assert on their own injected error), so the suite is machine-independent.

5. The login-shell claims, measured (only set/unset is revealed):

```
$ env -i /bin/zsh -c    'test -n "$NOTION_TOKEN_ASK" && echo SET || echo UNSET'   -> SET
$ env -i /bin/zsh -l -c 'test -n "$NOTION_TOKEN_ASK" && echo SET || echo UNSET'   -> SET
$ grep -l NOTION_TOKEN_ASK ~/.zshenv ~/.zprofile ~/.zshrc ~/.zlogin              -> ~/.zshenv, ~/.zshrc
$ head -1 /Users/assafkipnis/projects/consulting/q-consult/pipeline/crm-run.sh    -> #!/bin/zsh -l
$ env -i HOME=.. USER=.. /bin/zsh -l -c 'exec /bin/echo "[]"' | od -c            -> exactly "[ ] \n"
$ env -i HOME=.. USER=.. /bin/zsh -l -c 'echo shell=$$; exec /bin/sh -c "echo child=\$\$"'  -> shell=68252 child=68252
```

The comment's measurement ("bare env + zsh -l prints []") reproduces. `exec` does what the code relies on: the ledger process IS the shell's pid, so `subprocess.run(timeout=)` kills python, not an orphaning zsh. Nothing in the login profile writes to stdout, so the JSON parse is not at risk from a profile echo. One nuance is filed as a minor below.

6. Static checks:
   - `grep -rn "MAIL_TOOL\|MAIL_PROMPT\|MAIL_WINDOW_DAYS\|MAIL_ROW_CAP"` over the worktree (excluding .git): only the new test's tuple naming them as gone.
   - `awk '/# Section 2/,/# Section 3/'` of morning-brief.py grepped for `search_threads|run_claude|MAIL_`: none. The only "Gmail" mentions in the section are the Row docstring ("the Gmail thread id") and the history sentence ("used to ask a model to search Gmail").
   - `grep "(30d)\|(48h)\|Mail needing an answer"`: the label survives only at morning-brief.py:567 without a window; no other file asserted the old label.
   - `grep sys.path` in morning-brief.py: none.
   - The RCA the comment cites exists: `/Users/assafkipnis/projects/consulting/q-system/output/rca/rca-crm-evidence-invisible-2026-08-18.md`.
   - Ledger row shape (read from `read_ledger`, ledger.py:1672): `thread_id`, `client`, `last_from`, `subject`, `needs_reply_since` are all real keys; `cmd_needs_reply --json` prints `json.dumps(rows, indent=2)`, a bare list, filtered to `status == needs_reply`, not ignored, not parked past today. The token refusal (ledger.py:61) is `raise SystemExit("NOTION_TOKEN_ASK is not set. Refusing to run. ...")`, which is exit 1 with that line on stderr, so `run_ledger` would report `ledger exit 1: NOTION_TOKEN_ASK is not set...`, the exact shape the parametrised test uses.

## Code review of the two exits and the subprocess call

- `collect_mail`: `ledger_script()` error, runner error, non-JSON stdout, JSON that is not a list, and any entry that is not a dict or lacks `thread_id` all return `([], <error>)`; only a parsed list with a thread id on every entry returns `(rows, None)`. Every failure lands on the keep-the-board exit. Correct, and fail-closed on the half-list case (one bad row refuses the whole read rather than archiving the good rows' neighbours), which the comment and `test_one_bad_row_fails_the_whole_read` both state.
- `run_ledger`: refuses under pytest first; `shlex.quote` on every argv element; `exec` prefix; `/bin/zsh -l -c`; `capture_output`, `text`, `timeout`. `TimeoutExpired` and `OSError` are the only exceptions caught. A non-zero exit reports the last non-empty line of stderr (else stdout), truncated to 140 chars. `subprocess.run` with `capture_output=True` and no explicit `stdin` inherits stdin; the ledger CLI does not read stdin for `needs-reply`, so unlike `run_claude` this is not a hazard.
- Timeout vs guard: `LEDGER_TIMEOUT_S` (60) is well under `FIXED_BUDGET_S` (240) and under the guard used in `collect_hourly`, so the subprocess timeout fires first and the section error names the ledger. There is no test pinning `LEDGER_TIMEOUT_S < FIXED_BUDGET_S` (nit 4).
- Row key: `mail:<thread_id>` is the key consulting_board always received for an id-bearing model row, so a thread still needing him keeps its Notion page (probe EXIT 3: `updated=1`, no archive of p1).
- Callers: `collect_hourly` (line 749) and `collect_all` (line 786) both call `collect_mail(now)` with no runner, so production takes `run_ledger`. The `--inbox-only` branch of `main` (lines 858 to 895) has no hunk in `git diff`; its behaviour (print `[mail] COULD NOT READ: ...` or `[mail] N row(s)`, return 1 on a mail error) is covered by the existing `test_morning_brief.py` cases at lines 1043 and 1056, which stub `collect_hourly` with `{"mail": ([], None)}` and `{"mail": ([], "gmail down")}` and passed in the run above.

## The new comment block, sentence by sentence, against test_morning_brief_mail.py

Each row names the pytest case in `q-system/.q-system/tests/test_morning_brief_mail.py` (or `test_morning_brief.py`) that checks the sentence, or says the sentence is dated history that no test can check and is labelled as such in the comment.

| Sentence | pytest case, or dated history |
|---|---|
| The section used to ask a model for "a real person wrote and the founder has not replied" | History (dated). The old prompt is in the diff's minus lines. |
| The ledger dropped direction-only on 2026-08-18, RCA named | History; RCA file exists at the cited name. |
| 2026-09-06: ten rows on his Inbox view while `needs-reply --json` printed `[]` | Marked measured history. Not testable here by design. |
| The 30-day window went with the prompt; the label carries none | `test_the_model_read_is_gone_from_the_mail_section` (`"d)" not in label`; `MAIL_WINDOW_DAYS` absent) |
| The brief does not import the ledger; `test_the_brief_holds_no_ledger_import` keeps it so | That test (regex on import lines) |
| Subprocess under a LOGIN shell, same as crm-run.sh, because launchd is bare and the token is in the profile | `test_run_ledger_goes_through_the_login_shell` pins `("/bin/zsh","-l","-c")` and the `exec` string; crm-run.sh shebang verified `#!/bin/zsh -l`. Mechanism nuance: minor 2. |
| Measured 2026-09-06: bare env + zsh -l prints `[]`; bare env alone prints the refusal | Measured history; reproduced above (set/unset). |
| `([], None)` = nothing needs him, clear stale rows | Collector side: `test_an_empty_ledger_answer_is_empty_and_healthy`. Board side: only the generic consulting_board/board_rows tests, plus my probe. No committed test couples the new collector to `healthy_scopes` (see blocker 1: the four tests that used to do that coupling are the ones now red). |
| Every failure shape returns `([], error)`: no instance, non-zero exit, timeout, non-JSON, not a list, no thread id | `test_every_unreadable_shape_keeps_the_board` (7 cases), `test_a_missing_ledger_script_is_an_error_not_an_empty_section`, `test_no_consulting_board_sibling_is_an_error`, `test_run_ledger_reports_a_nonzero_exit_with_its_last_line` |
| "prints COULD NOT READ and leaves the board exactly as it was" | `_section` is unchanged; board side per the probe. |

Test isolation: the `instance` / `mail_instance` fixtures swap `_optional_module` for a `_FakeBoard` rooted at `tmp_path`; the shell test deletes `PYTEST_CURRENT_TEST` and replaces `brief.subprocess.run`, so no process is spawned; `test_run_ledger_refuses_under_pytest` asserts the chokepoint. No fixture names a live path.

## Findings

### 1. BLOCKER. Four tests in `q-system/.q-system/tests/test_consulting_board.py` are red on the merge gate.
File: q-system/.q-system/tests/test_consulting_board.py, lines 521 to 535 and 676 to 721.
Evidence: the pytest result line above (`4 failed, 212 passed`); `.verify-suites` names this directory; verify.yml runs `verify.sh --full` on pull_request and lefthook runs `--staged` at commit. The four tests exercise the producer that this change deletes (model-shaped runner, `{"threads": [...]}` payload, sender|subject fallback, the "2 threads" collapse row, `[2h]` age volatility). None of those behaviours exist any more: the ledger always supplies `thread_id`, and the rendered line carries `[since YYYY-MM-DD]`, not an age. They are not detecting a regression in the new code; they are asserting the old producer's shape.
Suggested fix: rewrite them against the ledger shape rather than shimming the old runner signature. `TestRound4::test_the_real_mail_producers_age_form_is_volatile` becomes "two ledger answers for one thread with different `needs_reply_since` / subject render differently and hash to one board id" (the drag-stability property it was written for, still true). `TestTwoThreadsAreNeverOneRow` collapses to one case: "two ledger rows with different thread ids reach the board as two rows with two keys", plus a class docstring note that the id-less branch was retired with the model read on 2026-09-06 (ASK-1323). This is also the natural home for the coupling the comment claims and nothing yet pins: `sources={"mail": ([], None)}` puts `inbox:Gmail` in `healthy_scopes`; `sources={"mail": ([], "ledger timed out")}` does not and yields exactly one `Gmail:error` row. Note: the spec's `allowed_files` lists `q-system/.q-system/scripts/test/` and bare `board_rows.py`, but not `q-system/.q-system/tests/test_consulting_board.py`, so this needs an issue-amend before the fix can land inside the DSSE flow.

### 2. MINOR. The login-shell comment states the right measurement with the wrong mechanism; the failure it would hide is fail-safe but permanent.
File: q-system/.q-system/scripts/morning-brief.py, lines 235 to 239 and 248 to 250.
Evidence: `env -i /bin/zsh -c` (no `-l`) already sees the token; `grep -l` finds the export in `~/.zshenv` (sourced by every zsh) and `~/.zshrc` (never sourced by a non-interactive `zsh -l -c`). So `-l` is not what carries the token today; `.zshenv` is. The consulting CLAUDE.md says the managed blocks live in `~/.zshrc`. If the export is ever consolidated there, `zsh -l -c` will not see it, `run_ledger` returns `ledger exit 1: NOTION_TOKEN_ASK is not set`, the section reads COULD NOT READ every morning and the board is kept forever (safe, but the issue's outcome silently stops).
Suggested fix: one sentence in the comment naming the real file: "the export must live in ~/.zshenv or ~/.zprofile; ~/.zshrc is not sourced by a non-interactive login shell, so a token that lives only there is invisible here and to crm-run.sh alike." No code change.

### 3. MINOR. Three in-scope comments still describe mail as a `claude -p` call.
File: q-system/.q-system/scripts/morning-brief.py, lines 39 to 51 (module docstring "Why two `claude -p` calls and not one": "Calendar and Gmail live behind the claude_ai_* connectors ... each section gets its own call"), lines 613 to 616 (`FIXED_BUDGET_S`: "Calendar and mail shell `claude -p` under CLAUDE_TIMEOUT, so the thread bound sits one minute above it"), lines 776 to 780 (`collect_all` docstring: "calendar and mail shell `claude -p` under CLAUDE_TIMEOUT, and the first live dry-run ... showed mail alone needs more than 20s").
Evidence: after this diff only calendar shells `claude -p`; mail shells the ledger under `LEDGER_TIMEOUT_S` (60) inside the same 240s guard. `test_the_model_read_is_gone_from_the_mail_section` deliberately scopes its grep to Section 2, so these are not caught, by design. The `FIXED_BUDGET_S` line is the one that matters: it is the guard's own justification and it is now wrong about one of the two collectors it bounds.
Suggested fix: rewrite the three sentences: the module docstring keeps the "why two calls" history as dated history and says calendar is the one remaining `claude -p` call; `FIXED_BUDGET_S` says "calendar shells `claude -p` under CLAUDE_TIMEOUT and mail shells the ledger under LEDGER_TIMEOUT_S; the bound sits above both".

### 4. NIT. No pin that `LEDGER_TIMEOUT_S` stays below the guard budget.
File: q-system/.q-system/scripts/morning-brief.py, line 247.
Evidence: `KIPI_BRIEF_LEDGER_TIMEOUT` is env-overridable; a value above 240 makes the guard fire first, the section error becomes the guard's `mail timed out (240.0s)` instead of the ledger's, and the abandoned subprocess keeps running (read-only, harmless). test_consulting_board already pins the analogous `board_rows.BUDGET_S < COLLECT_BUDGET_S`.
Suggested fix: one assertion in test_morning_brief_mail.py: `assert brief.LEDGER_TIMEOUT_S < brief.FIXED_BUDGET_S`.

### 5. NIT. Two small test-side shapes.
File: q-system/.q-system/tests/test_morning_brief_mail.py, line 69 and line 238.
Evidence: `stem.rstrip(".py")` strips a character SET, not a suffix (it happens to work for "consulting_board.py" because "d" is not in the set); `_optional_module` already accepts both spellings, so `stem.endswith("consulting_board") or stem.endswith("consulting_board.py")` says what is meant. Line 238's `assert "sys.path" not in src or "q-consult" not in src` is strict in effect (any `sys.path` mention fails, because "q-consult" is now in the source via `LEDGER_RELATIVE`), but the disjunction reads as a loophole; `assert "sys.path" not in src` is the check being made.
Suggested fix: as described; no behaviour change.

## Notes (outside the DoR's Files line; not findings)

- consulting_board.py lines 114 to 116 and 763 to 770 still explain `_FALLBACK_KEY` as "when the model returned no id". After this change no producer emits a `|` key; the guard is dead-but-harmless defence. Worth a one-line note when that file is next touched, not a change here.
- The engine tests that call `collect_all` (test_morning_brief.py lines 726 to 938) now reach the real `consulting_board.consulting_root()` and `is_file()` the founder's instance path before the chokepoint refuses. Read-only, no live data read, and the suite is machine-independent because the assertions never read the mail error text. Mentioned only so nobody later reads that stat as a live-path breach.
- `ledger_script()` executes consulting_board.py once per call and the registry executes it again for "Your book"; two `exec_module` calls per run of a module with no import-time I/O. Cost is negligible; a shared loader would be an unrelated refactor.

## Verdict

request-changes. The design is right and the property the issue exists for is demonstrated end to end (empty answer archives inside `inbox:Gmail`, unreadable keeps everything, the scope label is unchanged so the model-era rows will clear on the first healthy run). What stops it is finding 1: four tests in the same suite directory now assert a producer that no longer exists, `.verify-suites` puts that directory on both the commit and the merge gate, and the rewrite is also where the missing collector-to-board coupling test belongs. Findings 2 and 3 are prose that should ride the same commit; 4 and 5 are optional.
