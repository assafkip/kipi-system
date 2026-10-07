"""gate_proof -- prove a model-calling wrapper is metered and gated by RUNNING it.

why this exists (ASK-2540, RCA token-burn-recurs-after-gate, root cause #1). A
wrapper was counted "gated" because its source calls `model_gate.check`. The
check sat below an early `return runner(prompt)` that the real caller always
took, so live calls skipped both the gate and the usage ledger for days while
every source scan said gated. Reading source cannot see an early return on the
path a caller actually takes. This module watches one real call instead.

    verdict = prove(lambda claude_bin: my_wrapper("hi", claude_bin),
                    target="voiceloop.prompt_render:run_model")
    assert verdict.ok, verdict.reasons      # or: assert_gated(...)

What one `prove()` does:
  * writes a stub `claude` into a temp dir. It records its argv and prints a
    `--output-format json` result document carrying usage and a cost MARKER
    unique to this proof (plain text when the json flag is absent, like the CLI);
  * seals PATH: the stub dir first, and every PATH entry holding a real
    `claude` dropped, so a wrapper that shells `claude` by name reaches the stub;
  * points the usage ledger (KIPI_USAGE_LEDGER), the gate ledger
    (KIPI_MODEL_GATE_DIR, KIPI_MODEL_GATE_MARKER_DIR) and the alert sender
    (KIPI_NOTIFY) at that temp dir, and lifts PYTEST_CURRENT_TEST for the one
    call, since run_model refuses to shell anything while it is set;
  * calls `call(stub_path)` ONCE, then restores every variable it touched.

The verdict is green only when ALL of these hold:
  1. the stub ran exactly once (zero means the wrapper never reached a binary,
     or shelled a hardcoded path the stub cannot intercept: a real spend);
  2. exactly one usage-ledger row exists, of kind "run", and its cost equals
     this proof's marker, so the row came from THIS call's output;
  3. exactly one model_gate "call" row exists (one admitted decision);
  4. when `target` is given, that function's code was entered during the call.
     `target` is also how the fleet check (model-wrapper-runtime-proof-check.py)
     discovers which wrapper a test proves, so the label is checked at runtime
     and cannot name a function the test never drove.

`live_bin=` skips the stub and drives a real binary (the one-time runtime proof
the RCA asks for). It refuses under pytest: a suite never spends a real call.
"""
from __future__ import annotations

import contextlib
import importlib
import json
import os
import random
import shutil
import sys
import tempfile
from dataclasses import dataclass, field

#: The env vars a proof redirects. Restored exactly afterwards, absent ones removed.
# CHIEF_JOB/CHIEF_BOT re-key the gate and the ledger in a bot's env (PR #525 review);
# OPENCODE sends run_model down a provider the claude stub cannot see; an API key
# or base URL would let an SDK wrapper reach the billed API from a test.
_REDIRECTED = ("PATH", "KIPI_USAGE_LEDGER", "KIPI_MODEL_GATE_DIR", "KIPI_MODEL_GATE_MARKER_DIR",
               "KIPI_NOTIFY", "PYTEST_CURRENT_TEST", "KIPI_MODEL_GATE_PER_JOB",
               "KIPI_MODEL_GATE_FLEET", "KIPI_MODEL_GATE_MODE", "KIPI_MODEL_ITEM",
               "CHIEF_JOB", "CHIEF_BOT", "OPENCODE", "OPENCODE_MODEL",
               "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL")
#: Every model binary a wrapper might shell. Each is stubbed and dropped from PATH,
#: so a proof can never spend: a non-claude stub records the call and fails.
SEALED_BINARIES = ("claude", "codex", "opencode")
#: Set by model-wrapper-runtime-proof-check.py when it runs the proof tests. Never
#: defaulted: a receipt only exists where the check asked for one.
RECEIPTS_ENV = "KIPI_GATE_PROOF_RECEIPTS"
_DEAD_URL = "http://127.0.0.1:9"  # discard port: an SDK call fails fast, never spends

_STUB = r'''#!{python}
import json, os, sys
with open({log!r}, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd()}}) + "\n")
if "--output-format" in sys.argv and "json" in sys.argv:
    model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "claude-stub"
    print(json.dumps({{
        "type": "result", "subtype": "success", "is_error": False,
        "duration_ms": 900, "duration_api_ms": 850, "num_turns": 1,
        "result": "pong", "session_id": "gate-proof-stub",
        "total_cost_usd": {cost!r},
        "usage": {{"input_tokens": 10, "cache_creation_input_tokens": 0,
                   "cache_read_input_tokens": 0, "output_tokens": 2}},
        "modelUsage": {{model: {{"inputTokens": 10, "outputTokens": 2,
                                  "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0,
                                  "costUSD": {cost!r}}}}}}}))
else:
    print("pong")
'''

_OTHER = '''#!{python}
import json, os, sys
with open({log!r}, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({{"binary": {name!r}, "argv": sys.argv[1:]}}) + "\\n")
sys.stderr.write("gate_proof: {name} is sealed during a proof\\n")
sys.exit(97)
'''


@dataclass
class Verdict:
    ok: bool
    reasons: list = field(default_factory=list)
    stub_calls: list = field(default_factory=list)   # [{"argv": [...], "cwd": ...}]
    ledger_rows: list = field(default_factory=list)
    gate_rows: list = field(default_factory=list)
    target: str | None = None
    target_entered: bool | None = None
    result: object = None
    error: str | None = None
    live: bool = False

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "result"}


def _resolve(target: str):
    """`pkg.mod:qualname` -> the function's code object, unwrapped."""
    mod_name, _, qual = target.partition(":")
    if not qual:
        raise ValueError(f"target must be 'module:qualname', got {target!r}")
    mod = sys.modules.get(mod_name) or importlib.import_module(mod_name)
    obj = mod
    for part in qual.split("."):
        obj = getattr(obj, part)
    obj = getattr(obj, "__func__", obj)
    while hasattr(obj, "__wrapped__"):
        obj = obj.__wrapped__
    return obj.__code__


def _sealed_path(stub_dir: str) -> str:
    # why drop whole directories: with only a prepend, a wrapper that resolves the
    # binary some other way (shutil.which after reordering, a second lookup) still
    # reaches the real tool and spends. The cost: every other tool in a dropped
    # directory (a package manager's bin) is unreachable during the proof. Directories
    # with no model binary, the system ones holding git and sh, are kept.
    keep = [d for d in os.environ.get("PATH", "").split(os.pathsep)
            if d and not any(os.path.exists(os.path.join(d, b)) for b in SEALED_BINARIES)]
    return os.pathsep.join([stub_dir, *keep])


@contextlib.contextmanager
def _env(values: dict):
    saved = {k: os.environ.get(k) for k in _REDIRECTED}
    try:
        for k in _REDIRECTED:
            os.environ.pop(k, None)
        for k, v in values.items():
            os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _rows(path: str) -> list:
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    out.append({"_torn": line[:120]})
    except OSError:
        pass
    return out


def prove(call, *, target: str | None = None, live_bin: str | None = None,
          workdir: str | None = None) -> Verdict:
    """Drive ONE call through `call(claude_bin)` and judge what it left behind."""
    if live_bin and "pytest" in sys.modules:
        raise RuntimeError("gate_proof: live_bin is refused under pytest; a suite never spends a real call")
    receipts = os.environ.get(RECEIPTS_ENV)
    owned = workdir is None
    work = workdir or tempfile.mkdtemp(prefix="gate-proof-")
    try:
        v = _prove(call, target, live_bin, work, receipts)
    finally:
        if owned:
            shutil.rmtree(work, ignore_errors=True)
    return v


def _prove(call, target, live_bin, work, receipts) -> Verdict:
    stub_dir = os.path.join(work, "bin")
    os.makedirs(stub_dir, exist_ok=True)
    log = os.path.join(work, "stub-calls.jsonl")
    ledger = os.path.join(work, "usage-ledger.jsonl")
    gate = os.path.join(work, "model-gate")
    notify = os.path.join(work, "notify.sh")
    with open(notify, "w") as fh:  # a proof never files a real ticket
        fh.write('#!/bin/sh\necho "$1" >> "$(dirname "$0")/notified.txt"\n')
    os.chmod(notify, 0o755)
    # A cost no real call or other proof produces, so the ledger row can be tied to
    # THIS stub's output and not to a stray row or a failure row with no cost.
    marker = round(0.01 + random.random() / 1000, 9)
    stub = os.path.join(stub_dir, "claude")
    with open(stub, "w") as fh:
        fh.write(_STUB.format(python=sys.executable, log=log, cost=marker))
    os.chmod(stub, 0o755)
    other_log = os.path.join(work, "other-provider-calls.jsonl")
    for name in SEALED_BINARIES[1:]:
        path = os.path.join(stub_dir, name)
        with open(path, "w") as fh:
            fh.write(_OTHER.format(python=sys.executable, log=other_log, name=name))
        os.chmod(path, 0o755)

    code = _resolve(target) if target else None
    entered = []

    def _profile(frame, event, arg):
        if event == "call" and frame.f_code is code:
            entered.append(True)

    v = Verdict(ok=False, target=target, live=bool(live_bin))
    env = {"KIPI_USAGE_LEDGER": ledger, "KIPI_MODEL_GATE_DIR": gate,
           "KIPI_MODEL_GATE_MARKER_DIR": work, "KIPI_NOTIFY": notify,
           "PATH": _sealed_path(stub_dir), "ANTHROPIC_BASE_URL": _DEAD_URL}
    with _env(env):
        prev = sys.getprofile()
        if code is not None:
            sys.setprofile(_profile)
        try:
            v.result = call(live_bin or stub)
        except Exception as exc:  # noqa: BLE001  the verdict carries it, never raises past here
            v.error = f"{type(exc).__name__}: {exc}"
        finally:
            sys.setprofile(prev)

    v.stub_calls = _rows(log)
    v.ledger_rows = _rows(ledger)
    v.gate_rows = [r for name in sorted(os.listdir(gate)) if name.endswith(".jsonl")
                   for r in _rows(os.path.join(gate, name))] if os.path.isdir(gate) else []
    calls = [r for r in v.gate_rows if r.get("kind") == "call"]
    others = _rows(other_log)
    if others:
        v.reasons.append(f"a non-claude provider was invoked ({others[0].get('binary')}); "
                         "this helper proves claude wrappers only")
    if v.error:
        v.reasons.append(f"the call raised {v.error}")
    if not live_bin and len(v.stub_calls) != 1:
        v.reasons.append(f"stub claude ran {len(v.stub_calls)} times, expected 1 "
                         "(0: the wrapper never shelled a binary, or used a path the stub cannot reach)")
    if len(v.ledger_rows) != 1:
        v.reasons.append(f"usage ledger has {len(v.ledger_rows)} rows, expected 1")
    else:
        row = v.ledger_rows[0]
        if row.get("kind") != "run":
            v.reasons.append(f"ledger row kind is {row.get('kind')!r}, expected 'run'")
        if not live_bin and row.get("total_cost_usd") != marker:
            v.reasons.append(f"ledger row cost {row.get('total_cost_usd')!r} is not this proof's "
                             f"marker {marker}: the row did not come from this call's output")
        if live_bin and not row.get("total_cost_usd"):
            v.reasons.append("live ledger row carries no cost")
    if len(calls) != 1:
        v.reasons.append(f"model gate recorded {len(calls)} admitted calls, expected 1")
    if code is not None:
        v.target_entered = bool(entered)
        if not entered:
            v.reasons.append(f"target {target} was never entered during the call")
    v.ok = not v.reasons
    if receipts and code is not None and not live_bin:
        # The fleet check counts a wrapper proven only from a green receipt naming
        # the exact file, so a skipped, unreachable or inverted test proves nothing.
        try:
            with open(receipts, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"target": target, "file": os.path.realpath(code.co_filename),
                                     "qualname": target.partition(":")[2], "ok": v.ok,
                                     "reasons": v.reasons}) + "\n")
        except OSError as exc:
            v.reasons.append(f"receipt not written: {exc}")
            v.ok = False
    return v


def assert_gated(call, *, target: str | None = None, workdir: str | None = None) -> Verdict:
    """prove(), raising AssertionError with every reason when the call is not gated."""
    v = prove(call, target=target, workdir=workdir)
    if not v.ok:
        raise AssertionError("not runtime-gated: " + "; ".join(v.reasons))
    return v
