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

LEDGER_ENV = "KIPI_USAGE_LEDGER"
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
    for name, m in (doc.get("modelUsage") or {}).items():
        if isinstance(m, dict):
            per_model[name] = {k: m.get(k, 0) for k in _PER_MODEL_KEYS}
    tokens_in = sum(m["inputTokens"] + m["cacheReadInputTokens"] + m["cacheCreationInputTokens"]
                    for m in per_model.values())
    tokens_out = sum(m["outputTokens"] for m in per_model.values())
    return {
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


def failure_row(kind: str, *, bot: str, job: str | None = None, model: str | None = None,
                stdout: str | None = None, stderr: str | None = None) -> dict:
    """The row for a call that returned nothing to its caller.

    A timeout, a non-zero exit and a limit refusal all burn tokens the caller never
    sees. Without this row a blackout reads as an idle fleet. If the CLI managed to
    print a result document before failing, its usage is kept; otherwise tokens are
    None (unknown), never 0 (known to be nothing).
    """
    row = {"ts": _now_iso(), "bot": bot, "job": job, "model": model,
           "subtype": f"failed:{kind}", "is_error": True, "num_turns": None,
           "total_cost_usd": None, "duration_ms": None, "tokens_in": None,
           "tokens_out": None, "model_usage": {}, "limit_text": None, "session_id": None}
    doc = _result_document(stdout)
    if doc is not None:
        row.update({k: v for k, v in row_from(doc, bot=bot, job=job, model=model).items()
                    if k not in ("ts", "subtype", "is_error")})
        row["limit_text"] = _limit_in(doc.get("result"), doc.get("error"), stderr)
    else:
        row["limit_text"] = _limit_in(stdout, stderr)
    return row


def _result_document(stdout: str | None) -> dict | None:
    """The CLI's result document, whole or embedded after stray leading text."""
    if not stdout:
        return None
    for start in (0, stdout.find("{")):
        if start < 0:
            continue
        try:
            doc = json.loads(stdout[start:])
        except ValueError:
            continue
        if isinstance(doc, dict) and doc.get("type") == "result":
            return doc
    return None


def finish(stdout: str, *, bot: str, job: str | None = None, model: str | None = None) -> tuple[str, dict]:
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
        return stdout, {"ts": _now_iso(), "bot": bot, "job": job, "model": model,
                        "parse_error": "no result document in stdout",
                        "stdout_bytes": len(stdout or "")}
    text = doc.get("result")
    text = (text if isinstance(text, str) else "") + "\n"
    return text, row_from(doc, bot=bot, job=job, model=model)


def append(row: dict, path: str | None = None) -> bool:
    """Append one row. True if written. Never raises: the run is not the ledger's to fail."""
    target = path or ledger_path()
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        return True
    except (OSError, TypeError, ValueError):
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
