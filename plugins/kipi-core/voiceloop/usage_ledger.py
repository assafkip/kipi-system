"""Per-run usage ledger for every headless `claude -p` call (ASK-2008).

The fleet runs on one Claude subscription. Until this file existed nothing
recorded which bot spent what: on 2026-09-12 the weekly limit hit, every job
went dark, and the attempts ledger charged 23 issues as TERMINAL for it. The
founder's fear, verbatim: a bot "keeps creating tickets for the sake of creating
tickets and then it worked for a week and killed my tokens." A cap needs a meter
first. This is the meter.

How it works, and what it promises to callers:

- The wrapper adds `--output-format json` to the call. `finish()` turns that
  JSON back into EXACTLY the text a plain `-p` call printed (`result` plus the
  trailing newline; measured 2026-09-22, both forms captured in the test
  fixture), so no caller sees a different byte.
- One row per run, the failures included, is appended to
  `~/.config/kipi/usage-ledger.jsonl` (override: `KIPI_USAGE_LEDGER`).
  Machine-local, outside every repo. A call that returned nothing to its caller
  (timeout, non-zero exit, refusal) still leaves a `failure_row`, because a
  blackout that leaves no rows reads as an idle fleet (PR #410 review).
- Nothing here can fail a run. A stdout that is not the expected JSON is
  handed back as the plain prose a `-p` call would have printed and recorded
  as `parse_error`; a ledger that cannot be written is skipped. A meter that
  kills the job it meters is worse than none.
- No model call, no network. Pure functions over text, plus one append.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
import tempfile

LEDGER_ENV = "KIPI_USAGE_LEDGER"
#: Every row carries these two, whatever its shape, so a consumer can tell a
#: charged row from a failure row from a parse error without guessing keys.
SCHEMA = 1
PRODUCER = "voiceloop.usage_ledger"
_WARNED: list[str] = []
DEFAULT_LEDGER = os.path.join(os.path.expanduser("~"), ".config", "kipi", "usage-ledger.jsonl")

#: Appended to the argv by both wrappers. The tests PIN the literal rather than
#: reading this name: a test that compares the subject to itself passes when the
#: flag is mutated to "text" and the meter becomes a permanent no-op.
JSON_FLAGS = ("--output-format", "json")

#: A usage-limit refusal, as the CLI words it. Step 3 (ASK-2009) reads this to
#: keep a limit failure from being charged as an attempt. Matched ONLY on the text
#: of a call the CLI itself marked failed (`is_error`, an error subtype, a non-zero
#: exit, a timeout). Never on a successful result: in voiceloop the result IS the
#: generated post, and rate limits are a subject the founder writes about, so a
#: clean charged row was being flagged as a refusal (PR #410 review).
_LIMIT_RE = re.compile(
    r"usage limit|rate[ _-]?limit|credits[ _]required|weekly limit|limit (?:has been )?reached"
    r"|out of (?:usage|credits)", re.I)

_PER_MODEL_KEYS = ("inputTokens", "outputTokens", "cacheReadInputTokens",
                   "cacheCreationInputTokens", "costUSD")


def ledger_path() -> str:
    return os.environ.get(LEDGER_ENV) or DEFAULT_LEDGER


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _failed(doc: dict) -> bool:
    return bool(doc.get("is_error")) or str(doc.get("subtype") or "").startswith("error")


def _limit_in(*texts) -> str | None:
    for val in texts:
        if isinstance(val, str) and _LIMIT_RE.search(val):
            return val.strip().splitlines()[0][:200]
    return None


def limit_text(doc: dict) -> str | None:
    """The first line of a FAILED call's text that reads like a usage limit, else None.

    A successful call never yields one, whatever its result says (see _LIMIT_RE).
    """
    if not _failed(doc):
        return None
    return _limit_in(doc.get("result"), doc.get("error"), doc.get("message"))


def row_from(doc: dict, *, bot: str, job: str | None = None, model: str | None = None) -> dict:
    """One ledger row from a `--output-format json` result document.

    A document the CLI marked failed (is_error, or an error subtype) is a
    "failure" row, the same kind a timeout or a non-zero exit gets, so a query
    keyed on kind counts every refusal once (chief PR #34 round 1: the metered
    lane wrote "run" for the same refusal the own-format lane wrote "failure").
    Its usage and cost are kept: the tokens were spent.
    """
    row = _row_from(doc, bot=bot, job=job, model=model)
    if _failed(doc):
        row["kind"] = "failure"
    return row


def _row_from(doc: dict, *, bot: str, job: str | None = None, model: str | None = None) -> dict:
    """One ledger row from a `--output-format json` result document.

    Token totals are summed across `modelUsage`, every model the run reports,
    so a run is charged in full to the bot that started it. Whether that block
    folds subagent tokens in is NOT pinned here (round 9 minor 2): no captured
    run spawned one. The verbose capture reports `subagent_stats` as its own
    key, which is the fixture to extend when a subagent run is captured.
    """
    per_model: dict[str, dict] = {}
    usage = doc.get("modelUsage")
    for name, m in (usage.items() if isinstance(usage, dict) else ()):
        if isinstance(m, dict):
            per_model[name] = {k: m.get(k, 0) for k in _PER_MODEL_KEYS}
    # Empty modelUsage means the CLI reported nothing, not that nothing was spent:
    # a limit refusal still costs the request. Unknown is None, never 0.
    def total(key):
        vals = [m.get(key) for m in per_model.values()]
        nums = [v for v in vals if isinstance(v, (int, float))]
        return sum(nums) if nums else None
    fresh, cache_read, cache_create = (total("inputTokens"), total("cacheReadInputTokens"),
                                       total("cacheCreationInputTokens"))
    # tokens_in is everything the request CARRIED (fresh + cache read + cache
    # write), which is what a context-size cap reads. Cost weights them very
    # differently (round 7: 3,991x fresh on the fixture), so the three parts are
    # stored beside it and total_cost_usd stays the spend number.
    parts = [v for v in (fresh, cache_read, cache_create) if v is not None]
    tokens_in = sum(parts) if parts else None
    tokens_out = total("outputTokens")
    return {
        "schema": SCHEMA, "producer": PRODUCER, "kind": "run",
        "tokens_fresh_in": fresh, "tokens_cache_read": cache_read, "tokens_cache_create": cache_create,
        "ts": _now_iso(),
        "bot": bot,
        "job": job,
        "model": model,
        "subtype": doc.get("subtype"),
        "is_error": bool(doc.get("is_error")),
        "num_turns": doc.get("num_turns"),
        "total_cost_usd": doc.get("total_cost_usd"),
        "duration_ms": doc.get("duration_ms"),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "model_usage": per_model,
        "limit_text": limit_text(doc),
        "session_id": doc.get("session_id"),
    }


def _text(v) -> str | None:
    """subprocess.TimeoutExpired carries bytes even under text=True; a row is text."""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


def failure_row(kind: str, *, bot: str, job: str | None = None, model: str | None = None,
                stdout: str | None = None, stderr: str | None = None, ok: bool = False) -> dict:
    """The row for a call that returned nothing to its caller.

    A timeout, a non-zero exit and a limit refusal all burn tokens the caller never
    sees. Without this row a blackout reads as an idle fleet. If the CLI managed to
    print a result document before failing, its usage is kept; otherwise tokens are
    None (unknown), never 0 (known to be nothing).
    """
    stdout, stderr = _text(stdout), _text(stderr)
    # `ok` marks a call that succeeded for its caller but could not be metered (an
    # unmetered provider, a plain-call fallback): kind "unmetered", not a failure,
    # so a failure-rate over this ledger stays honest (PR #410 round 3).
    row = {"schema": SCHEMA, "producer": PRODUCER, "kind": "unmetered" if ok else "failure",
           "ts": _now_iso(), "bot": bot, "job": job, "model": model,
           "subtype": ("unmetered:" if ok else "failed:") + kind, "is_error": not ok, "num_turns": None,
           "total_cost_usd": None, "duration_ms": None, "tokens_in": None,
           "tokens_fresh_in": None, "tokens_cache_read": None, "tokens_cache_create": None,
           "tokens_out": None, "model_usage": {}, "limit_text": None, "session_id": None}
    doc = _result_document(stdout)
    if doc is not None:
        row.update({k: v for k, v in row_from(doc, bot=bot, job=job, model=model).items()
                    if k not in ("ts", "subtype", "is_error", "kind")})
        # limit_text() keeps its guard: a document the CLI called a success is a
        # generated post, never a refusal, even when the call then timed out
        # (PR #410 round 2). Only stderr is read unguarded, and stderr is never prose.
        row["limit_text"] = limit_text(doc) or _limit_in(stderr)
        # A CAPPED RUN KEEPS THE CLI'S OWN WORD FOR THE STOP (ASK-2011). Both cap
        # hits exit non-zero with an empty stderr and a whole result document on
        # stdout, so they land on the wrapper's generic exit arm and the merge
        # above would file them as `failed:exit 1` -- indistinguishable from a
        # crash, and unreadable by the Step 4 brake, which counts cap hits.
        cap = cap_subtype_of(doc)
        if cap:
            row["subtype"] = cap
    else:
        # No result document: stdout may be a partial generated post, which is prose
        # and never a refusal. Only stderr is read (round 3).
        row["limit_text"] = _limit_in(stderr)
    return row


_ARRAY_OPEN = re.compile(r"^\s*\[\s*\{")


def _is_json(stdout: str | None) -> bool:
    """True when stdout is json-mode output, whole or truncated.

    Under --output-format json the CLI prints only JSON objects, so anything
    that opens with a brace and holds no result document is a failed or cut
    json-mode call, never prose (round 7: a truncated document with exit 0 was
    being handed back as the post).
    """
    # `[{` is the --verbose array form (round 9): json mode all the same. A bare
    # `[` is not: a degraded-path post may open with one ("[Draft] ...", PR #413
    # round 2), and prose must never be dropped and charged as an error.
    return bool(stdout) and (stdout.lstrip().startswith("{") or _ARRAY_OPEN.match(stdout) is not None)


#: How many `{` the in-place scan tries before giving up. A module constant so a
#: test can set it to 0 and prove the array branch is the one finding a result
#: (PR #413 round 4: redaction cut the fixture under the cap and the mutant
#: went green).
BRACE_SCAN_CAP = 50


def _result_document(stdout: str | None) -> dict | None:
    """The CLI's result document, whole or embedded after stray leading text."""
    if not stdout:
        return None
    # Whole-text first: the plain document, or the --verbose ARRAY of events whose
    # last element is the result. The array form was invisible to the scans below
    # (round 9 minor 1): its result sits past the 50th brace, behind the init
    # event, so a --verbose call's post came back as prose.
    try:
        whole = json.loads(stdout)
    except ValueError:
        whole = None
    if isinstance(whole, dict) and whole.get("type") == "result":
        return whole
    if isinstance(whole, list):
        for item in reversed(whole):
            if isinstance(item, dict) and item.get("type") == "result":
                return item
        return None
    # The CLI may print other JSON objects (an init event) or stray lines before the
    # result. Every line is tried on its own, then the whole text from each `{`.
    decoder = json.JSONDecoder()
    for ln in stdout.splitlines():
        ln = ln.lstrip()
        if not ln.startswith("{"):
            continue
        try:
            doc, _ = decoder.raw_decode(ln)
        except ValueError:
            continue
        if isinstance(doc, dict) and doc.get("type") == "result":
            return doc
    # A pretty-printed document spans lines: decode from each brace IN PLACE
    # (raw_decode takes an index; no suffix copies, round 3 measured 548 MB of them).
    pos, tries = stdout.find("{"), 0
    while pos >= 0 and tries < BRACE_SCAN_CAP:
        try:
            doc, _ = decoder.raw_decode(stdout, pos)
        except ValueError:
            doc = None
        if isinstance(doc, dict) and doc.get("type") == "result":
            return doc
        pos, tries = stdout.find("{", pos + 1), tries + 1
    return None


def plain_text(stdout: str | None) -> str | None:
    """Best-effort prose from a json-format stdout when metering itself failed."""
    try:
        doc = _result_document(stdout)
        if doc is None:
            return stdout
        if _failed(doc):
            return None
        text = doc.get("result")
        return (text if isinstance(text, str) else "") + "\n"
    except Exception:  # noqa: BLE001
        return stdout


def finish(stdout: str, *, bot: str, job: str | None = None,
           model: str | None = None) -> tuple[str | None, dict]:
    """(text_for_the_caller, ledger_row) from the raw stdout of a json-format call.

    `text_for_the_caller` is byte-identical to what a plain `-p` call prints for
    the same result: the `result` string plus one trailing newline. If `stdout`
    is not a result document, the caller gets the plain prose a `-p` call would
    have printed: the document's `result` when one can be found inside the
    output (a warning line printed before it, say), else the output as it is.
    The row says why, so a CLI that stops emitting this shape degrades to
    today's behaviour instead of breaking every bot at once.
    """
    doc = _result_document(stdout)
    if doc is None:
        # JSON that is not a result document means the CLI ran in json mode and
        # produced no result: a failed call, not prose (round 6). Only stdout that
        # is not JSON at all is handed back as text, the way a plain call prints it.
        text = None if _is_json(stdout) else stdout
        row = failure_row("parse_error", bot=bot, job=job, model=model)
        # is_error follows what the CALLER got: nothing is an error, prose is not (round 8)
        row.update({"kind": "parse_error", "subtype": "parse_error", "is_error": text is None,
                    "parse_error": "no result document in stdout",
                    "stdout_bytes": len(stdout or "")})
        return text, row
    row = row_from(doc, bot=bot, job=job, model=model)
    if _failed(doc):
        # The CLI answered with an error document (a usage-limit refusal, most
        # often) and exit 0. Its text is not a post; the caller gets None, the
        # same as any other failed call (PR #410 round 4).
        return None, row
    text = doc.get("result")
    text = (text if isinstance(text, str) else "") + "\n"
    return text, row


def append(row: dict, path: str | None = None) -> bool:
    """Append one row. True if written. Never raises: the run is not the ledger's to fail.

    UNDER PYTEST THE DEFAULT LEDGER IS REFUSED. On 2026-09-22 a deployment's
    test suite faked the model call but not the ledger, and every run left
    rows in the live ~/.config/kipi/usage-ledger.jsonl: 125 parse_error rows
    by evening, all with 2-byte stdout, indistinguishable from a metered bot
    that had stopped parsing. The same refusal run_model makes for a live
    model call applies to a live ledger write: inside a test, a row goes to
    the path the test named (KIPI_USAGE_LEDGER, or `path=`) or nowhere, and
    stderr says so once.
    """
    explicit = path or os.environ.get(LEDGER_ENV)
    if os.environ.get("PYTEST_CURRENT_TEST") and not explicit:
        if "pytest" not in _WARNED:
            _WARNED.append("pytest")
            sys.stderr.write("usage_ledger: refusing to write the live ledger from inside a test; "
                             "set KIPI_USAGE_LEDGER (or pass path=) to a temp file\n")
        return False
    target = explicit or ledger_path()
    try:
        parent = os.path.dirname(target)
        if parent:  # a bare filename lives in the cwd; makedirs("") raises
            os.makedirs(parent, exist_ok=True)
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        return True
    except (OSError, TypeError, ValueError) as exc:
        # Never raise, but never silent either: one line per process on stderr, so
        # a meter that has stopped metering is visible in the job's err log.
        if target not in _WARNED:
            _WARNED.append(target)
            sys.stderr.write(f"usage_ledger: cannot append to {target}: {exc}\n")
        return False


def read(path: str | None = None) -> list[dict]:
    """Every row, in file order; a torn line is skipped, never fatal."""
    target = path or ledger_path()
    rows: list[dict] = []
    try:
        with open(target, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return rows
    return rows


# ---------------------------------------------------------------- per-run caps
#: How a capped run names itself. MEASURED against the live CLI on 2026-09-29,
#: not read off a doc: `plugins/kipi-core/voiceloop/tests/fixtures/
#: claude-p-cap-hits-capture.json`, regenerated by `capture_cap_hits.py` beside
#: it. `--max-turns` exhausted -> subtype "error_max_turns"; `--max-budget-usd`
#: exhausted -> "error_max_budget_usd". Both: is_error true, exit 1, EMPTY stderr,
#: a whole result document on stdout, and a real total_cost_usd (the tokens up to
#: the cap were spent).
CAP_SUBTYPE_PREFIX = "error_max_"
#: The flag names. `--max-budget-usd` is documented in `claude --help`;
#: `--max-turns` is accepted and undocumented there, which is why the fixture
#: rather than the help text is this module's evidence that both work.
TURNS_FLAG = "--max-turns"
BUDGET_FLAG = "--max-budget-usd"
#: Overrides, and the ONLY way a caller changes a cap without a sizing pass.
TURNS_ENV = "KIPI_MAX_TURNS"
BUDGET_ENV = "KIPI_MAX_BUDGET_USD"
CAPS_ENV = "KIPI_USAGE_CAPS"
DEFAULT_CAPS = os.path.join(os.path.expanduser("~"), ".config", "kipi", "usage-caps.json")
#: FLOORS, and they are not decoration. 3x a median is a ratio, so a bot whose
#: median run is one cheap turn would be sized into a cap that kills every real
#: run it makes. A cap below these is a cap that meters nothing but breakage.
MIN_TURNS = 8
MIN_BUDGET_USD = 0.50
#: The multiplier the DoR names. A run at 3x its own bot's median is not a long
#: run, it is a run that stopped converging.
CAP_FACTOR = 3
#: How many charged rows a bot needs before its median is allowed to become a cap.
#: MEASURED against this fleet's own ledger (PR #469 review, 64 charged runs over
#: 2026-09-23..28): sizing `radar` off its first 5 rows produces a cap that kills
#: 25 of its 45 real runs, and off all 45 rows a cap that kills 1. A median from a
#: handful of samples is not a measurement, and a bot sized from one is worse off
#: than a bot left alone -- so a bot under this many rows is OMITTED from the caps
#: file and runs uncapped until the ledger can actually answer for it.
MIN_SIZING_RUNS = 20
#: How far back `cap_hits` looks. The Step 4 brake pauses a bot on 3 hits inside
#: this window; the count lives here because the ledger is the only witness.
CAP_WINDOW_HOURS = 24
CAP_HITS_TO_PAUSE = 3


def caps_path() -> str:
    return os.environ.get(CAPS_ENV) or DEFAULT_CAPS


def cap_subtype_of(doc: dict) -> str | None:
    """The CLI's cap subtype for this result document, else None."""
    sub = str(doc.get("subtype") or "")
    return sub if sub.startswith(CAP_SUBTYPE_PREFIX) else None


def is_cap_hit(row: dict) -> bool:
    """True when this ledger row is a run the wrapper's own cap stopped."""
    return str(row.get("subtype") or "").startswith(CAP_SUBTYPE_PREFIX)


def _median(values: list) -> float | None:
    nums = sorted(v for v in values if isinstance(v, (int, float)))
    if not nums:
        return None
    mid = len(nums) // 2
    return float(nums[mid]) if len(nums) % 2 else (nums[mid - 1] + nums[mid]) / 2.0


def size_caps(rows: list[dict], *, factor: int = CAP_FACTOR,
              min_runs: int = MIN_SIZING_RUNS) -> dict:
    """`{bot: {"turns": int, "budget_usd": float, "runs": int}}` at `factor`x each median.

    Sized from CHARGED rows only (kind "run"): a failure row carries no num_turns
    and a parse_error carries no cost, so counting them drags every median toward
    None and the bot inherits the floor it did not earn. A bot under the floors
    gets the floors, and `runs` says how many rows the number came from.

    A bot with fewer than `min_runs` charged rows is OMITTED, not floored. `runs`
    used to be written and read by nothing (PR #469 review), which let a median
    from three rows ship at full force as though it were measured; an omitted bot
    gets no flags at all from `cap_args` and keeps running the way it does today.
    """
    by_bot: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("kind") != "run":
            continue
        by_bot.setdefault(str(row.get("bot") or "unknown"), []).append(row)
    out = {}
    for bot, bot_rows in by_bot.items():
        if len(bot_rows) < min_runs:
            continue
        turns = _median([r.get("num_turns") for r in bot_rows])
        cost = _median([r.get("total_cost_usd") for r in bot_rows])
        out[bot] = {
            "turns": max(MIN_TURNS, int(-(-(turns or 0) * factor // 1))),
            "budget_usd": max(MIN_BUDGET_USD, round((cost or 0.0) * factor, 4)),
            "runs": len(bot_rows),
        }
    return out


def write_caps(path: str | None = None, *, rows: list[dict] | None = None,
               factor: int = CAP_FACTOR, min_runs: int = MIN_SIZING_RUNS) -> dict:
    """Size every bot's caps from the ledger and write them where `caps_for` reads.

    THE OTHER HALF OF THE CAP. `caps_for` deliberately never scans the ledger, so
    with nothing writing this file it does not exist, every lookup takes the
    except branch, and every bot in the fleet runs on MIN_TURNS / MIN_BUDGET_USD
    forever. A floor is not "3x this bot's median" -- it is the number a bot gets
    when nobody measured it. `size_caps` computed the median and reached no run
    until this pass persisted it.

    SINGLE WRITER, and the write is atomic. Two of these racing (the daily job and
    a hand run) could otherwise leave a truncated document, which `caps_for` reads
    as broken and answers with no cap at all.

    The temp file gets a UNIQUE name in the target's own directory. A fixed
    `target + ".tmp"` is a path BOTH racers open, so the second `os.replace` finds
    it already renamed away and raises FileNotFoundError out of this function,
    dropping that writer's whole sizing pass (PR #469 review, reproduced with two
    threads). Same directory so the rename stays on one filesystem and stays atomic.
    """
    sized = size_caps(read() if rows is None else rows, factor=factor, min_runs=min_runs)
    target = path or caps_path()
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent or ".", prefix=os.path.basename(target) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(sized, fh, indent=1, sort_keys=True)
        os.replace(tmp, target)
    except BaseException:
        # A failed write must not leave its temp file behind to accumulate next to
        # the caps file forever.
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return sized


def sized_caps_for(bot: str) -> dict | None:
    """This bot's entry in the sized caps file, or None when it has none.

    THE PER-CALL PATH NEVER SCANS THE LEDGER. That file grows without bound and
    `run_model` is on the hot path of every bot in the fleet, so sizing is a
    separate pass (`size_caps` over `read()`, written to `caps_path()`) and the
    wrapper reads one small document. A missing or malformed file is None, never
    an exception: a cap that cannot be read must not stop the run.
    """
    try:
        with open(caps_path(), encoding="utf-8") as fh:
            entry = json.load(fh).get(bot)
        return entry if isinstance(entry, dict) else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def caps_for(bot: str) -> tuple[int, float]:
    """`(turns, budget_usd)` for this bot: env override, else the sized file, else floors.

    The floors are what a SIZED bot cannot go below, never a cap handed to a bot
    nobody measured -- `cap_args` is what decides whether this bot is capped at all.
    """
    env_turns, env_budget = os.environ.get(TURNS_ENV), os.environ.get(BUDGET_ENV)
    sized = sized_caps_for(bot) or {}
    turns, budget = MIN_TURNS, MIN_BUDGET_USD
    try:
        turns = max(MIN_TURNS, int(sized.get("turns", MIN_TURNS)))
        budget = max(MIN_BUDGET_USD, float(sized.get("budget_usd", MIN_BUDGET_USD)))
    except (ValueError, TypeError):
        turns, budget = MIN_TURNS, MIN_BUDGET_USD
    # The override is read LAST and is not floored: a caller naming a cap has a
    # reason (a test, a deliberately tiny probe run), and silently raising it to
    # the floor would make that caller's number a lie.
    try:
        if env_turns:
            turns = int(env_turns)
        if env_budget:
            budget = float(env_budget)
    except ValueError:
        pass
    return turns, budget


def cap_args(bot: str) -> list[str]:
    """The two flags for this bot's caps, or NO FLAGS when nobody has sized it.

    AN UNSIZED BOT RUNS UNCAPPED. This used to hand every bot the floors the
    moment the caps file was absent, and the caps file is absent until the sizing
    pass runs. Measured against this fleet's own ledger (PR #469 review, 64
    charged runs): the floors kill 49 of those 64 runs, the sized caps kill 1. A
    fleet that ships before its first sizing pass would have failed 3 runs in 4,
    burned full cost on each, and then been paused by the Step 4 brake for hitting
    a cap nobody chose.

    So the floors are a LOWER BOUND ON A MEASURED NUMBER, not a default. No sized
    entry and no explicit override means the argv carries neither flag and the
    call is exactly the call this wrapper made before ASK-2011.
    """
    if sized_caps_for(bot) is None and not (
            os.environ.get(TURNS_ENV) or os.environ.get(BUDGET_ENV)):
        return []
    turns, budget = caps_for(bot)
    return [TURNS_FLAG, str(turns), BUDGET_FLAG, str(budget)]


#: Flags the wrapper ADDS and must be able to take back out, each with whether it
#: carries a value. Derived by the fallback rather than restated there, so a flag
#: added above cannot be forgotten in the strip.
#:
#: `JSON_FLAGS` is a flag and ITS VALUE (`--output-format json`), not two flags.
#: Registering both names as valueless flags is what let the strip drop any argv
#: element equal to the bare word `json` (PR #469 review); registering the flag as
#: value-carrying removes the pair positionally, so only its own value goes.
_ADDED_FLAGS = {TURNS_FLAG: True, BUDGET_FLAG: True, JSON_FLAGS[0]: True}


def without_added_flags(argv: list[str]) -> list[str]:
    """`argv` with every flag this module adds removed, VALUES INCLUDED.

    Only a token starting with `--` can BE a flag here. `JSON_FLAGS` contributes
    the bare word `json` as its own entry, so a name-only match strips any argv
    element equal to `json` -- including a prompt whose entire text is that word,
    leaving `-p` bare on the fallback call (PR #469 review).
    """
    out, skip = [], False
    for arg in argv:
        if skip:
            skip = False
            continue
        if arg.startswith("--") and arg in _ADDED_FLAGS:
            skip = _ADDED_FLAGS[arg]
            continue
        out.append(arg)
    return out


def cap_hits(bot: str, *, rows: list[dict] | None = None,
             hours: int = CAP_WINDOW_HOURS, now: _dt.datetime | None = None) -> int:
    """How many of this bot's runs a cap stopped inside the window.

    The Step 4 brake (ASK-2010) reads this: `cap_hits(bot) >= CAP_HITS_TO_PAUSE`
    is a bot that is not converging, which is a different condition from a bot
    that is over its usage share. A row whose ts cannot be parsed is not counted;
    an unreadable timestamp is not evidence of a hit inside the window.
    """
    rows = read() if rows is None else rows
    now = now or _dt.datetime.now(_dt.timezone.utc)
    floor = now - _dt.timedelta(hours=hours)
    hits = 0
    for row in rows:
        if row.get("bot") != bot or not is_cap_hit(row):
            continue
        try:
            ts = _dt.datetime.strptime(str(row.get("ts")), "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=_dt.timezone.utc)
        except (ValueError, TypeError):
            continue
        if ts >= floor:
            hits += 1
    return hits


def rejected_flag(stderr: str | None) -> bool:
    """True when the CLI refused one of the flags the wrapper adds (an older binary).

    `--max-turns` and `--max-budget-usd` joined the list with ASK-2011 and the
    reason is the blast radius: this wrapper is every voiceloop caller's only
    model call, so a binary that does not know a flag WE add fails every run in
    the fleet at once. `--max-turns` is undocumented in `claude --help` on the
    2026-09-29 binary, which is exactly the kind of flag a future build drops.
    The fallback strips all of them and the run still happens, uncapped, with a
    row that says so.
    """
    s = stderr or ""
    named = any(f in s for f in ("--output-format", TURNS_FLAG, BUDGET_FLAG))
    return named and ("unknown" in s.lower() or "unrecognized" in s.lower()
                      or "error:" in s.lower())


def _cli(argv: list[str] | None = None) -> int:
    """`python3 -m voiceloop.usage_ledger size-caps` -- the sizing pass's entry point.

    A module-level function with no caller is a cap nobody ever sizes, which is
    how the floors become permanent (`wiring-check.md`: text in a file is not
    wired). This is the caller, and it prints what it wrote so a cron row is
    readable rather than silent.
    """
    import argparse
    ap = argparse.ArgumentParser(prog="voiceloop.usage_ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("size-caps", help="write per-bot caps at CAP_FACTOR x each median")
    sc.add_argument("--factor", type=int, default=CAP_FACTOR)
    sc.add_argument("--min-runs", type=int, default=MIN_SIZING_RUNS,
                    help="charged rows a bot needs before its median becomes a cap")
    sc.add_argument("--out", default=None, help="defaults to caps_path()")
    args = ap.parse_args(argv)
    sized = write_caps(args.out, factor=args.factor, min_runs=args.min_runs)
    target = args.out or caps_path()
    for bot in sorted(sized):
        row = sized[bot]
        print(f"{bot}: turns={row['turns']} budget_usd={row['budget_usd']} "
              f"from {row['runs']} run(s)")
    if not sized:
        # Not an error: either the fleet has not run yet, or no bot has reached
        # min_runs. Worth printing, because the file just written is empty and an
        # empty file means every bot runs UNCAPPED -- which is the safe state, not
        # a broken one, and is the opposite of what the floors used to do here.
        print(f"no bot has {args.min_runs}+ charged rows; {target} written empty "
              f"(every bot runs uncapped until one does)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
