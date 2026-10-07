"""Meter the two spenders the usage ledger could not see: PR reviews and Agent-tool runs (ASK-2541).

THE SCAR, 2026-10-06. The founder asked what was eating his usage. The ledger
showed $54 of background jobs. It did not show 35 PR reviews that day, and it did
not show the day's biggest spender: one orchestrated agent that ran 57 Opus turns
and re-read about 10.3M cached tokens. A meter that misses the biggest spenders
reads as coverage, and the spend it hides is the spend nobody can cap.

Two entry points, both writing through `usage_ledger.append` (the ledger's ONE
writer; this module never opens the ledger file itself):

    python3 usage_meter.py review --raw F --out F [--stderr F] --rc N --item R#N --model M
        One `claude -p --output-format json` review run. Writes the text a plain
        `-p` call would have printed to --out (so the verdict reader is unchanged)
        and appends one ledger row.

    python3 usage_meter.py subagent-stop        (SubagentStop hook, payload on stdin)
        Sums the subagent transcript's usage per assistant turn and appends one
        row per Agent run, priced from model_prices.

FAIL-OPEN, AND NEVER SILENT. Nothing here can fail a review or block an agent:
every path exits 0. A failure to meter is appended to a named log
(`KIPI_USAGE_METER_LOG`, default ~/.config/kipi/logs/usage-meter.log) with the
reason, because a meter that stops metering without a trace reads as an idle fleet.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

LOG_ENV = "KIPI_USAGE_METER_LOG"
STATE_ENV = "KIPI_AGENT_METER_STATE"
PRODUCER = "voiceloop.usage_meter"


def _home(*parts: str) -> str:
    return os.path.join(os.path.expanduser("~"), ".config", "kipi", *parts)


def log_path() -> str:
    return os.environ.get(LOG_ENV) or _home("logs", "usage-meter.log")


def log(reason: str) -> None:
    """One line to the named meter log. Never raises."""
    try:
        target = log_path()
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(f"{ts} {reason}\n")
    except Exception:  # noqa: BLE001 -- the log is the last resort; stderr is the one after it
        try:
            sys.stderr.write(f"usage_meter: {reason}\n")
        except Exception:  # noqa: BLE001
            pass


def _read(path: str | None) -> str:
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# review: one pr-review-agent.sh model run
# ---------------------------------------------------------------------------

def review_text(raw: str) -> str:
    """What the review file must hold, from json-mode stdout.

    A success document becomes exactly the text a plain `-p` call prints, so the
    FINDINGS reader downstream sees the bytes it always saw. Anything else (an
    error document, a cut stream, prose from a stub) is kept AS IT IS: a usage-limit
    refusal must still be readable by is_environmental, and dropping it would turn
    "the runner is down" into "the review said nothing".
    """
    from usage_ledger import _result_document, finish  # local import: a broken ledger must not break the text
    text, _row = finish(raw, bot="pr-review")
    if text is not None:
        return text
    doc = _result_document(raw)
    if isinstance(doc, dict):
        # An error document (a usage-limit refusal, most often) must reach
        # is_environmental as the plain line the CLI would have printed, not as a
        # JSON blob: as JSON, an outage became a failing required status instead of
        # exit 9 (PR #528 review, major).
        parts = [doc.get(k) for k in ("result", "error", "message")]
        plain = "\n".join(p for p in parts if isinstance(p, str) and p.strip())
        if plain:
            return plain + "\n"
    return raw


def meter_review(raw_path: str, out_path: str, *, stderr_path: str | None, rc: int,
                 item: str, model: str | None) -> None:
    raw = _read(raw_path)
    err = _read(stderr_path)
    # The text first, and on its own: if anything below fails, the review survives.
    try:
        text = review_text(raw)
    except Exception as exc:  # noqa: BLE001
        log(f"review {item}: could not convert json output ({type(exc).__name__}: {exc}); review kept raw")
        text = raw
    # stderr first, then the answer: the FINDINGS block stays the trailing block,
    # which is where the usability check reads it.
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(err + text)
    try:
        import usage_ledger as ul
        if rc == 0:
            _text, row = ul.finish(raw, bot="pr-review", job="pr-review", model=model)
        else:
            kind = "timeout" if rc in (124, 137, 143) else f"exit_{rc}"
            row = ul.failure_row(kind, bot="pr-review", job="pr-review", model=model,
                                 stdout=raw, stderr=err)
        row["item"] = item
        row["rc"] = rc
        if row.get("kind") == "parse_error":
            log(f"review {item}: no result document in the model's stdout ({len(raw)} bytes, rc={rc}); "
                "a parse_error row was written")
        if not ul.append(row):
            log(f"review {item}: ledger append refused or failed ({ul.ledger_path()})")
    except Exception as exc:  # noqa: BLE001
        log(f"review {item}: metering failed ({type(exc).__name__}: {exc}); the review itself is unaffected")


# ---------------------------------------------------------------------------
# subagent-stop: one Agent-tool run
# ---------------------------------------------------------------------------

def _turns(transcript_path: str) -> list[dict]:
    """One entry per distinct assistant API response, with its FINAL usage.

    The transcript writes one record per content block, and each repeats the
    message's usage; the early copies carry a partial output count (measured on a
    real transcript: 19 assistant records, 12 distinct message ids, 7 ids whose
    copies disagree on output_tokens). Summing records would charge one turn
    several times, so turns are keyed by message id and the copy with the largest
    output count wins.
    """
    best: dict[str, dict] = {}
    order: list[str] = []
    with open(transcript_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue  # a torn line is skipped, never fatal
            if not isinstance(rec, dict) or rec.get("type") != "assistant":
                continue
            msg = rec.get("message")
            if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
                continue
            key = msg.get("id") or rec.get("requestId") or rec.get("uuid")
            if not key:
                continue
            usage = msg["usage"]
            prev = best.get(key)
            if prev is None:
                order.append(key)
            if prev is None or (usage.get("output_tokens") or 0) >= (prev["usage"].get("output_tokens") or 0):
                best[key] = {"id": key, "model": msg.get("model"), "usage": usage}
    return [best[k] for k in order]


def _n(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def agent_row(turns: list[dict], *, agent_id: str, agent_type: str | None,
              session_id: str | None) -> dict:
    import model_prices
    import usage_ledger as ul
    per_model: dict[str, dict] = {}
    unpriced: list[str] = []
    for t in turns:
        u = t["usage"]
        name = t.get("model") or "unknown"
        if name == "<synthetic>":
            continue  # a harness-written placeholder turn, not an API call
        cc = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
        w1h = _n(cc.get("ephemeral_1h_input_tokens"))
        w_all = _n(u.get("cache_creation_input_tokens"))
        w5m = max(w_all - w1h, 0)  # no TTL breakdown means the 5-minute default
        m = per_model.setdefault(name, {"inputTokens": 0, "outputTokens": 0, "cacheReadInputTokens": 0,
                                        "cacheCreationInputTokens": 0, "_w5m": 0, "_w1h": 0, "turns": 0})
        m["inputTokens"] += _n(u.get("input_tokens"))
        m["outputTokens"] += _n(u.get("output_tokens"))
        m["cacheReadInputTokens"] += _n(u.get("cache_read_input_tokens"))
        m["cacheCreationInputTokens"] += w_all
        m["_w5m"] += w5m
        m["_w1h"] += w1h
        m["turns"] += 1
    total_cost = 0.0
    for name, m in per_model.items():
        c = model_prices.cost(name, fresh_in=m["inputTokens"], out=m["outputTokens"],
                              cache_read=m["cacheReadInputTokens"], cache_write_5m=m.pop("_w5m"),
                              cache_write_1h=m.pop("_w1h"))
        m["costUSD"] = None if c is None else round(c, 6)
        if c is None:
            unpriced.append(name)
        else:
            total_cost += c

    def tot(k):
        return sum(m[k] for m in per_model.values()) if per_model else None
    fresh, read, create, out = (tot("inputTokens"), tot("cacheReadInputTokens"),
                                tot("cacheCreationInputTokens"), tot("outputTokens"))
    models = sorted(per_model)
    return {
        "schema": ul.SCHEMA, "producer": PRODUCER, "kind": "agent",
        "ts": ul._now_iso(), "bot": "agent", "job": agent_type or "agent",
        "model": models[0] if len(models) == 1 else ",".join(models) or None,
        "subtype": "subagent_stop", "is_error": False,
        "num_turns": sum(m["turns"] for m in per_model.values()),
        # Unknown is None, never 0: a run on an unpriced model must not read as free.
        "total_cost_usd": None if unpriced else round(total_cost, 6),
        "cost_basis": model_prices.SOURCE, "unpriced_models": unpriced,
        "duration_ms": None,
        "tokens_fresh_in": fresh, "tokens_cache_read": read, "tokens_cache_create": create,
        "tokens_in": (fresh + read + create) if per_model else None, "tokens_out": out,
        "model_usage": per_model, "limit_text": None,
        "session_id": session_id, "agent_id": agent_id, "item": agent_id,
    }


_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _state_file(agent_id: str) -> str | None:
    root = os.environ.get(STATE_ENV)
    if not root:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return None  # a test never writes the live state dir
        root = _home("agent-meter")
    return os.path.join(root, _SAFE.sub("_", agent_id) + ".json")


def _metered(path: str | None) -> set[str]:
    if not path:
        return set()
    try:
        with open(path, encoding="utf-8") as fh:
            ids = json.load(fh).get("metered_ids", [])
        return {i for i in ids if isinstance(i, str)}
    except (OSError, ValueError, AttributeError):
        return set()


def _save_metered(path: str | None, ids: set[str]) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"metered_ids": sorted(ids)}, fh)
    os.replace(tmp, path)


def meter_subagent(payload: dict) -> dict | None:
    """Append one ledger row for this Agent run; return it (None when there was nothing new).

    A subagent can stop more than once: a SubagentStop hook that exits 2 sends it
    back for another turn, and SendMessage resumes it under the same agent_id.
    Each stop meters only the turns no earlier stop already charged, so a
    re-stopped agent is never billed twice.
    """
    agent_id = str(payload.get("agent_id") or "")
    path = payload.get("agent_transcript_path")
    if not path and agent_id and payload.get("transcript_path"):
        # Older payloads: the subagent file sits beside the parent session's transcript.
        base = os.path.splitext(payload["transcript_path"])[0]
        path = os.path.join(base, "subagents", f"agent-{agent_id}.jsonl")
    if not path or not os.path.isfile(path):
        log(f"subagent-stop {agent_id or '?'}: no readable agent transcript ({path!r}); no row written")
        return None
    turns = _turns(path)
    state = _state_file(agent_id or path)
    done = _metered(state)
    new = [t for t in turns if t["id"] not in done]
    # A harness placeholder turn is not an API call; a stop that added only those
    # would write a zero-turn, zero-cost row (PR #528 review, minor).
    if not [t for t in new if t.get("model") != "<synthetic>"]:
        return None
    import usage_ledger as ul
    row = agent_row(new, agent_id=agent_id, agent_type=payload.get("agent_type"),
                    session_id=payload.get("session_id"))
    if row["unpriced_models"]:
        log(f"subagent-stop {agent_id}: no price for {row['unpriced_models']}; cost left unknown")
    if ul.append(row):
        # Append first, then state: a lost state write re-charges on the next
        # stop (visible, logged); the reverse order would drop a row silently.
        try:
            _save_metered(state, done | {t["id"] for t in new})
        except OSError as exc:
            log(f"subagent-stop {agent_id}: state write failed ({exc}); the next stop may re-charge these turns")
    else:
        log(f"subagent-stop {agent_id}: ledger append refused or failed ({ul.ledger_path()})")
    return row


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["review"]:
            import argparse
            ap = argparse.ArgumentParser(description="meter one review run")
            ap.add_argument("--raw", required=True)
            ap.add_argument("--out", required=True)
            ap.add_argument("--stderr")
            ap.add_argument("--rc", type=int, default=0)
            ap.add_argument("--item", default="")
            ap.add_argument("--model")
            a = ap.parse_args(argv[1:])
            meter_review(a.raw, a.out, stderr_path=a.stderr, rc=a.rc, item=a.item, model=a.model)
            return 0
        if argv[:1] == ["subagent-stop"]:
            try:
                payload = json.loads(sys.stdin.read() or "{}")
            except ValueError as exc:
                log(f"subagent-stop: payload is not JSON ({exc}); no row written")
                return 0
            if isinstance(payload, dict):
                meter_subagent(payload)
            return 0
        log(f"unknown usage_meter invocation: {argv!r}")
    except Exception as exc:  # noqa: BLE001 -- the contract is exit 0, always
        log(f"usage_meter {argv[:1]}: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
