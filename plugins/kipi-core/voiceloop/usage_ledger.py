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

    Token totals are summed across `modelUsage` (which includes subagents; the
    top-level `usage` block does not, per the CLI docs), so a run that spawned
    subagents is charged in full to the bot that started it.
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
    else:
        # No result document: stdout may be a partial generated post, which is prose
        # and never a refusal. Only stderr is read (round 3).
        row["limit_text"] = _limit_in(stderr)
    return row


def _is_json(stdout: str | None) -> bool:
    """True when stdout is json-mode output, whole or truncated.

    Under --output-format json the CLI prints only JSON objects, so anything
    that opens with a brace and holds no result document is a failed or cut
    json-mode call, never prose (round 7: a truncated document with exit 0 was
    being handed back as the post).
    """
    return bool(stdout) and stdout.lstrip().startswith("{")


def _result_document(stdout: str | None) -> dict | None:
    """The CLI's result document, whole or embedded after stray leading text."""
    if not stdout:
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
    while pos >= 0 and tries < 50:
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
        row = failure_row("parse_error", bot=bot, job=job, model=model)
        row.update({"kind": "parse_error", "subtype": "parse_error", "is_error": False,
                    "parse_error": "no result document in stdout",
                    "stdout_bytes": len(stdout or "")})
        # JSON that is not a result document means the CLI ran in json mode and
        # produced no result: a failed call, not prose (round 6). Only stdout that
        # is not JSON at all is handed back as text, the way a plain call prints it.
        return (None if _is_json(stdout) else stdout), row
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
    """Append one row. True if written. Never raises: the run is not the ledger's to fail."""
    target = path or ledger_path()
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


def rejected_flag(stderr: str | None) -> bool:
    """True when the CLI refused `--output-format` itself (an older binary)."""
    s = stderr or ""
    return "--output-format" in s and ("unknown" in s.lower() or "unrecognized" in s.lower()
                                       or "error:" in s.lower())
