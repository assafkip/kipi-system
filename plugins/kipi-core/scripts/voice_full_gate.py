#!/usr/bin/env python3
"""The fleet's ONE voice entry point: the full check, for any instance (ASK-4969).

    python3 voice_full_gate.py --surface linkedin draft.md     # or - for stdin
    from voice_full_gate import check; check(text, "linkedin").ok

Exit 0: every required part ran and no hard row fired. Exit 2: refused, with a JSON
verdict on stdout. Exit 64: bad arguments.

## It exposes the engine, it is not a third engine

The full check is `pipeline.gate_draft.evaluate` in the consulting repo, the same function
`gate_draft.verify` mints receipts from and `gate_draft --full` reports. This file runs
it in a child process, from the engine's own directory, and applies ONE rule to what it
returns. No band, threshold, floor or word list lives here. why a child process and not an
import: the fleet bans cross-repo imports, and chief already reaches the engine this way
(`cwd=` the consulting checkout); one shape for every caller.

why `evaluate` and not the `--full` CLI's printout: the CLI is a report for a person, and
parsing it is how chief's stdout re-parse drifted. `evaluate` returns the parts as data.
It is also the function the receipt is minted from, so this check and the mint cannot
disagree about what ran.

## The rule (ASK-4327 folded in)

why: the 2026-11-06 RCA (rca-x-drafts-shown-after-a-partial-voice-check) counted 33 drafts
shown as "checked" after a partial check. A part that ran 0 read like a clean part. So:
  - a hard row refuses (verdict REFUSE);
  - a required part with ran 0, an outage row, or NO parts at all refuses (verdict OUTAGE).
    ran 0 of 0 counts: a part that examined nothing did not check anything;
  - the engine absent, crashing, timing out or printing non-JSON refuses (OUTAGE). A gate
    that cannot run must not pass;
  - judgment notes never refuse (RULE-2026-11-04-C). They ride along for the writer.

## Where the engine and interpreter come from

`KIPI_VOICE_ENGINE_ROOT` (the directory holding `pipeline/`), else the consulting checkout.
`KIPI_VOICE_PYTHON`, else this interpreter. One resolver each, so the interpreter pin
(ASK-4969, a later step) changes one function.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# The part-count rule lives in the engine package, shared with the critic (ASK-5411).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voiceloop import part_runs  # noqa: E402

ENGINE_ENV = "KIPI_VOICE_ENGINE_ROOT"
PYTHON_ENV = "KIPI_VOICE_PYTHON"
# Measured 2026-11-18: one linkedin paragraph took 71 s end to end (LUAR plus 15 critic
# rows). Chief's voiceloop call uses 600 s. A run past this is an outage, never a pass.
DEFAULT_TIMEOUT_S = 600
EXIT_PASS, EXIT_REFUSE, EXIT_USAGE = 0, 2, 64
# The evaluate keys judge() reads. Absent means the engine's shape drifted: an OUTAGE.
REQUIRED_KEYS = ("hard", "notes", "parts", "outages")

# The child. It reads {"text", "surface", "source_text"} on stdin and prints evaluate's
# dict as ONE json line after a marker, so a library that prints to stdout cannot corrupt
# the result. The two cache defaults are gate_draft.main's own: without them the scorer's
# first call tries a download into a read-only home and fails on a fault unrelated to the
# draft (gate_draft.py main()).
_MARK = "@@VOICE_FULL_GATE_RESULT@@"
_CHILD = (
    "import json, os, sys\n"
    "sys.path.insert(0, os.getcwd())\n"
    "os.environ.setdefault('UV_CACHE_DIR', os.path.expanduser('~/.cache/kipi-luar/uv'))\n"
    "os.environ.setdefault('HF_HOME', os.path.expanduser('~/.cache/kipi-luar/hf'))\n"
    "req = json.loads(sys.stdin.read())\n"
    "from pipeline import gate_draft\n"
    "r = gate_draft.evaluate(req['text'], req['surface'], source_text=req.get('source_text'))\n"
    "sys.stdout.write('\\n' + %r + json.dumps(r, default=str) + '\\n')\n" % _MARK
)


@dataclass
class Verdict:
    verdict: str                      # PASS | REFUSE | OUTAGE
    surface: str
    reasons: list = field(default_factory=list)
    hard: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    parts: dict = field(default_factory=dict)
    outages: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict == "PASS"

    def to_json(self) -> str:
        d = asdict(self)
        d["ok"] = self.ok
        return json.dumps(d, indent=1)


def default_engine_root() -> Path:
    env = os.environ.get(ENGINE_ENV)
    if env:
        return Path(env).expanduser()
    return Path.home() / "projects" / "consulting" / "q-consult"


def default_python() -> str:
    return os.environ.get(PYTHON_ENV) or sys.executable


def judge(result: dict, surface: str) -> Verdict:
    """The one rule, applied to evaluate's dict. Pure, so every caller shares it."""
    hard = list(result.get("hard") or [])
    notes = list(result.get("notes") or [])
    parts = dict(result.get("parts") or {})
    outages = [list(o) for o in (result.get("outages") or [])]
    reasons = ["hard: %s" % h for h in hard]
    runs = part_runs.assess(parts)
    if runs.empty:
        reasons.append("no required part ran for surface %r: nothing was checked" % surface)
    reasons += ["part %s ran 0 of %s" % (n, of) for n, of in runs.zero]
    # PARTIAL is reported, not refused, here. why: a part's own owner decides whether its
    # partial run is an outage, and reports it as ran 0 or an outage row when it is (the
    # critic's quality wave does that under ASK-5411). Measured 2026-11-18: one live run had
    # critic at 8 of 15. Refusing every partial here would refuse on the critic's behalf.
    notes += ["partial: part %s ran %s of %s" % p for p in runs.partial]
    for o in outages:
        reasons.append("outage %s" % " ".join(str(x) for x in o))
    if hard:
        verdict = "REFUSE"
    elif reasons:
        verdict = "OUTAGE"
    else:
        verdict = "PASS"
    return Verdict(verdict, surface, reasons, hard, notes, parts, outages)


def _outage(surface: str, why: str) -> Verdict:
    return Verdict("OUTAGE", surface, ["engine: " + why])


def check(text: str, surface: str, *, source_text: str | None = None,
          engine_root: Path | str | None = None, python: str | None = None,
          timeout: float | None = None, env: dict | None = None) -> Verdict:
    """Run every required part for `surface` on `text`. Never raises for an engine fault:
    a fault is an OUTAGE verdict, so no caller can turn an exception into a pass."""
    root = Path(engine_root) if engine_root is not None else default_engine_root()
    if not (root / "pipeline" / "gate_draft.py").is_file():
        return _outage(surface, "no voice engine at %s (set %s)" % (root, ENGINE_ENV))
    payload = json.dumps({"text": text, "surface": surface, "source_text": source_text})
    try:
        # A new session so a timeout can kill the whole tree. why (round 1 review of #839,
        # the ASK-3515 scar in luar_env_backend._run_bounded): subprocess.run(timeout=)
        # kills only the direct child, and the engine's `uv run` grandchild survived
        # holding the uv cache lock.
        proc = subprocess.Popen([python or default_python(), "-c", _CHILD], cwd=str(root),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True,
                                env=env if env is not None else None)
    except OSError as exc:
        return _outage(surface, "could not start the interpreter (%s)" % exc)
    try:
        stdout, stderr = proc.communicate(payload, timeout=timeout or DEFAULT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.communicate()
        return _outage(surface, "timed out after %ss" % (timeout or DEFAULT_TIMEOUT_S))
    tail = (stderr or "").strip().splitlines()[-3:]
    if proc.returncode != 0:
        return _outage(surface, "exited %d: %s" % (proc.returncode, " | ".join(tail)[:400]))
    line = next((ln for ln in reversed(stdout.splitlines()) if ln.startswith(_MARK)), None)
    if line is None:
        return _outage(surface, "printed no result (%s)" % " | ".join(tail)[:300])
    try:
        result = json.loads(line[len(_MARK):])
    except ValueError as exc:
        return _outage(surface, "result is not JSON (%s)" % exc)
    if not isinstance(result, dict):
        return _outage(surface, "result is not an object")
    bad = _malformed(result)
    if bad:
        # why (Codex P2, #839): {"hard": 1} raised TypeError out of check(), so a caller got
        # an exception and the CLI a traceback with no verdict. A malformed result is an
        # engine fault, so it is an OUTAGE like any other.
        return _outage(surface, "result field(s) malformed: %s" % ", ".join(bad))
    return judge(result, surface)


def _malformed(result: dict) -> list:
    """Names of evaluate fields that are absent or have a shape judge() cannot read.

    why absent counts (round 1 review of #839): `result.get("hard") or []` read a key
    renamed upstream as "no hard rows fired", a silent PASS. gate_draft.verify itself does
    result["hard"] and fails loud on the same drift."""
    bad = [k for k in REQUIRED_KEYS if k not in result]
    bad += [k for k in ("hard", "notes") if k in result and not isinstance(result[k], list)]
    if "parts" in result and not isinstance(result["parts"], dict):
        bad.append("parts")
    outages = result.get("outages") or []
    if not isinstance(outages, list) or not all(isinstance(o, (list, tuple)) for o in outages):
        bad.append("outages")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="voice_full_gate",
                                 description="the full voice check for one draft")
    ap.add_argument("file", help="the draft, or - for stdin")
    ap.add_argument("--surface", required=True, help="the gated surface, e.g. linkedin, x, report")
    ap.add_argument("--source", help="the artifact the draft's figures come from")
    ap.add_argument("--engine-root", help="directory holding pipeline/ (default: %s or the "
                    "consulting checkout)" % ENGINE_ENV)
    ap.add_argument("--timeout", type=float, default=None)
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_PASS
    try:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        source = Path(args.source).read_text(encoding="utf-8") if args.source else None
    except (OSError, UnicodeDecodeError) as exc:
        print(_outage(args.surface, "cannot read input (%s)" % exc).to_json())
        return EXIT_REFUSE
    v = check(text, args.surface, source_text=source, engine_root=args.engine_root,
              timeout=args.timeout)
    print(v.to_json())
    return EXIT_PASS if v.ok else EXIT_REFUSE


if __name__ == "__main__":
    sys.exit(main())
