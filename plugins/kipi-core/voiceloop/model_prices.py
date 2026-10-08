"""List prices per model, so a meter that sees only token counts can state a cost (ASK-2541).

WHY THIS EXISTS. A headless `claude -p --output-format json` call reports its own
`total_cost_usd`, so the usage ledger never needed a price table. An Agent-tool
subagent does not: its transcript carries token counts per assistant turn and no
cost. On 2026-10-06 the day's biggest spender was one such agent (57 Opus turns,
about 10.3M cache-read tokens) and the ledger had no row for it at all.

WHERE THE NUMBERS COME FROM. Anthropic first-party API list prices, as printed in
the Claude API reference bundled with Claude Code (its "Current Models" table,
cached 2026-09-25, and its prompt-caching "Economics" paragraph):

- input and output per million tokens: the model table, verbatim.
- cache READ: 0.1x input, except the models whose read price is printed on its
  own (Opus 5.5 $0.20, Sonnet 5.5 $0.20, Fable 5.1 $0.25, Fable 5 $1.00).
- cache WRITE: 1.25x input for the 5-minute TTL, 2x input for the 1-hour TTL.

This is the API-EQUIVALENT cost. The fleet runs on a subscription, so no invoice
carries these dollars; they are the same basis `total_cost_usd` uses, which keeps
an agent row comparable with a headless-call row in one ledger.

An unknown model is priced as None, never 0. A zero reads as "free", and a model
that shipped after this table would then vanish from every spend total.
"""
from __future__ import annotations

#: Per million tokens: (input, output, cache_read or None for the 0.1x default).
_LIST = {
    "claude-fable-5-1": (10.00, 50.00, 0.25),
    "claude-fable-5": (10.00, 50.00, 1.00),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, None),
    "claude-opus-4-8": (5.00, 25.00, None),
    "claude-opus-4-7": (5.00, 25.00, None),
    "claude-opus-4-6": (5.00, 25.00, None),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-sonnet-5": (2.00, 10.00, None),
    "claude-sonnet-4-6": (3.00, 15.00, None),
    "claude-haiku-4-5": (1.00, 5.00, None),
}

CACHE_WRITE_5M = 1.25
CACHE_WRITE_1H = 2.0
CACHE_READ_DEFAULT = 0.1
SOURCE = "anthropic-api-list-price-2026-09-25"


def _base(model: str | None) -> str | None:
    """`claude-opus-5-5[1m]` and dated ids price as their base id."""
    if not model:
        return None
    m = model.split("[", 1)[0].strip()
    if m in _LIST:
        return m
    # A dated suffix (`-20260401`) is the same model at the same price.
    head, _, tail = m.rpartition("-")
    if tail.isdigit() and len(tail) == 8 and head in _LIST:
        return head
    return None


def rates(model: str | None) -> dict | None:
    """USD per single token for each usage bucket, or None for an unpriced model."""
    key = _base(model)
    if key is None:
        return None
    inp, out, read = _LIST[key]
    per = 1_000_000.0
    return {
        "input": inp / per,
        "output": out / per,
        "cache_read": (read if read is not None else inp * CACHE_READ_DEFAULT) / per,
        "cache_write_5m": inp * CACHE_WRITE_5M / per,
        "cache_write_1h": inp * CACHE_WRITE_1H / per,
    }


def cost(model: str | None, *, fresh_in: int = 0, out: int = 0, cache_read: int = 0,
         cache_write_5m: int = 0, cache_write_1h: int = 0) -> float | None:
    """API-equivalent USD for one model's token totals; None when the model is unpriced."""
    r = rates(model)
    if r is None:
        return None
    return (fresh_in * r["input"] + out * r["output"] + cache_read * r["cache_read"]
            + cache_write_5m * r["cache_write_5m"] + cache_write_1h * r["cache_write_1h"])
