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
- One row per run is appended to `~/.config/kipi/usage-ledger.jsonl`
  (override: `KIPI_USAGE_LEDGER`). Machine-local, outside every repo.
- Nothing here can fail a run. A stdout that is not the expected JSON is passed
  through untouched and recorded as `parse_error`; a ledger that cannot be
  written is skipped. A meter that kills the job it meters is worse than none.
- No model call, no network. Pure functions over text, plus one append.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re

LEDGER_ENV = "KIPI_USAGE_LEDGER"
DEFAULT_LEDGER = os.path.join(os.path.expanduser("~"), ".config", "kipi", "usage-ledger.jsonl")

#: Appended to the argv by both wrappers. One constant, so a test that asserts
#: the flags reads them from here instead of restating them.
JSON_FLAGS = ("--output-format", "json")

#: A usage-limit refusal, as the CLI words it. Step 3 (ASK-2009) reads this to
#: keep a limit failure from being charged as an attempt. Matched on the result
#: and error text only; a prompt about rate limits does not trip it because the
#: prompt is not in the result.
_LIMIT_RE = re.compile(
    r"usage limit|rate[ _-]?limit|credits[ _]required|weekly limit|limit (?:has been )?reached"
    r"|out of (?:usage|credits)|resets? at", re.I)

_PER_MODEL_KEYS = ("inputTokens", "outputTokens", "cacheReadInputTokens",
                   "cacheCreationInputTokens", "costUSD")


def ledger_path() -> str:
    return os.environ.get(LEDGER_ENV) or DEFAULT_LEDGER


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def limit_text(doc: dict) -> str | None:
    """The first line of result/error text that reads like a usage limit, else None."""
    for key in ("result", "error", "message"):
        val = doc.get(key)
        if isinstance(val, str) and _LIMIT_RE.search(val):
            return val.strip().splitlines()[0][:200]
    return None


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


def finish(stdout: str, *, bot: str, job: str | None = None, model: str | None = None) -> tuple[str, dict]:
    """(text_for_the_caller, ledger_row) from the raw stdout of a json-format call.

    `text_for_the_caller` is byte-identical to what a plain `-p` call prints for
    the same result: the `result` string plus one trailing newline. If `stdout`
    is not a result document, it is returned untouched and the row says why, so
    a CLI that stops emitting this shape degrades to today's behaviour instead
    of breaking every bot at once.
    """
    try:
        doc = json.loads(stdout)
        if not isinstance(doc, dict) or doc.get("type") != "result":
            raise ValueError("not a result document")
    except (ValueError, TypeError) as exc:
        return stdout, {"ts": _now_iso(), "bot": bot, "job": job, "model": model,
                        "parse_error": f"{type(exc).__name__}: {str(exc)[:120]}",
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
