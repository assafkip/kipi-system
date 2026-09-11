#!/usr/bin/env python3
"""Run the LUAR embedding in the DECLARED environment, from an interpreter that
does not have it (sp-d912cc82).

## The problem this solves

`gate_post.py` runs under the repo interpreter (homebrew python 3.14). torch
publishes no wheels for 3.14, so `TransformersBackend._load()` raises, the gate's
failure contract turns that into `authorship: null`, and the metric reads as
permanently broken. Before this module the only way to get a number was to
hand-type

    uv run --python 3.12 --with torch --with transformers --with numpy --with einops ...

which is a dependency declaration that exists only in somebody's shell history.
That is the same class as a lazy import that works on one machine: the thing that
makes it run is not in the repo.

## The shape

One subprocess, one JSON exchange, one declared requirements file:

    parent (repo interpreter, no torch)
      -> uv run --python 3.12 --with-requirements requirements-authorship.txt
           python3 -m voiceloop.luar_env_backend --worker
      -> child (declared env, has torch) imports luar_scorer.TransformersBackend

THE CHILD RUNS THE SAME `TransformersBackend` THIS REPO ALREADY HAD. That is the
load-bearing part, not an implementation detail. The scorer contract pins
`max_length`/`truncation` to exactly one site and `backend.encode` to exactly one
caller; a worker that re-implemented tokenization would satisfy both detectors
(they read luar_scorer.py) while silently computing a different number in the one
path a human actually runs. Crossing a process boundary must not fork the
contract, so the worker imports it instead of restating it.

## Why this file holds BOTH sides of the protocol

The spawner and the worker are one file on purpose. They agree on a wire format,
and a wire format split across two files drifts the first time one side gains a
key. There is no import cycle risk: the worker half only runs under `--worker`.

## What is deliberately NOT here

No caching, no warm pool, no batching. A `gate_post.py` run pays one model load
(~20s warm). That is a human-in-the-loop command run a few times a day, and the
daily posting lane never reaches this file at all because `drift_report`'s
`authorship` default is False. Optimizing an unmeasured cost would add state to
a path whose whole value is that it has none.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(HERE, "requirements-authorship.txt")

#: What the child is told to run. Derived from THIS module's own dotted name, so a
#: move takes it along; see the comment at the `-m` in `encode_via_declared_env`.
WORKER_MODULE = __name__ if "." in __name__ else f"voiceloop.{__name__}"

# THE INTERPRETER PIN. It cannot live in requirements-authorship.txt (a
# requirements file has no way to say it), and it is not cosmetic: the repo
# interpreter is 3.14 and torch has no 3.14 wheels, so an unpinned `uv run` would
# inherit 3.14 and fail to resolve. Held equal to the comment in the requirements
# file by test_luar_env_backend.py, because two files stating one fact is how the
# fact goes stale on one of them.
PYTHON_PIN = "3.12"

# A cold run downloads ~2GB of wheels; a warm one is a cache hit plus the model
# load. Generous on purpose -- the failure this cap exists for is a hang, not
# slowness, and a cap that fires on an ordinary cold start would make the metric
# look broken on exactly the machine that needed it most.
TIMEOUT_SECONDS = 900


def _uv_available():
    from shutil import which
    return which("uv") is not None


def _child_env(package_parent):
    """The child's environment: PYTHONPATH so it can find the package, and no
    pytest marker.

    PYTHONPATH is REQUIRED, not belt-and-braces. `uv run python3 <abs path>` puts
    the SCRIPT's own directory on sys.path[0] -- here that is `pipeline/` itself,
    not its parent -- so the sibling `luar_scorer` import raised
    `ModuleNotFoundError` on the first working run,
    with cwd already correct. cwd is not a sys.path entry for a script invocation,
    and assuming it was cost one round of this loop.

    PYTEST_CURRENT_TEST is stripped because the child imports luar_scorer, and a
    suite-detection chokepoint keyed on that variable would read the worker as a
    test and refuse the real work.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (f"{package_parent}{os.pathsep}{existing}"
                         if existing else package_parent)
    return env


def encode_via_declared_env(documents):
    """Vectors for `documents`, computed in the declared environment.

    Raises `ScorerUnavailable` for every failure mode, because the caller
    (`voicefp_gate._advisory_authorship`) turns exactly that into the additive
    null. A subprocess gives this function more ways to fail than an in-process
    call has -- uv missing, resolution failure, a non-zero exit, unparseable
    stdout, a wrong-length reply -- and every one of them has to arrive at the
    caller as the same "no number this run", or the failure contract that the
    other issues pinned stops holding on the one path a human runs.
    """
    from .luar_scorer import ScorerUnavailable

    if not _uv_available():
        raise ScorerUnavailable(
            "uv is not on PATH, so the declared authorship environment "
            f"({os.path.basename(REQUIREMENTS)}) cannot be built")
    if not os.path.isfile(REQUIREMENTS):
        raise ScorerUnavailable(f"missing requirements file: {REQUIREMENTS}")

    # `-m <this module>`, NOT a path to this file. Handing python3 a script path
    # puts that script's OWN directory on sys.path[0] -- the package dir -- so
    # every module sitting next to this one shadows a top-level package of the
    # same name for the whole child process. That is not hypothetical: it is what
    # produced round 3's `attempted relative import with no known parent package`
    # from inside the transformers import, a message that names nothing in this
    # repo. `-m` gives the worker a real package context and leaves the package
    # dir off sys.path entirely, which retires the shadowing class rather than
    # dodging one instance of it.
    #
    # THE NAME IS DERIVED, never typed (2026-09-06). It was the literal
    # "pipeline.luar_env_backend" and the module moved to `voiceloop` in extraction
    # slice 12e. Nothing caught it: every test here mocks `subprocess.run`, so the
    # string was never resolved by an interpreter. It failed only in the child, as
    # `ModuleNotFoundError: No module named 'pipeline'`, which `encode_via_declared_env`
    # correctly turns into ScorerUnavailable and `_advisory_authorship` correctly
    # turns into a null score -- so the authorship number the founder asked to
    # always be computed was silently absent on every run, at exit 0, with the
    # reason sitting in a sidecar nobody reads. `__name__` cannot go stale.
    out_fd, out_path = tempfile.mkstemp(prefix="luar-vectors-", suffix=".json")
    os.close(out_fd)
    cmd = ["uv", "run", "--python", PYTHON_PIN,
           "--with-requirements", REQUIREMENTS,
           "python3", "-m", WORKER_MODULE, "--worker",
           "--out", out_path]
    # cwd is the PARENT of the package dir so the worker's sibling import resolves
    # the same package this process is running, not a copy that happens to be on
    # the child's sys.path.
    cwd = os.path.dirname(HERE)
    try:
        proc = subprocess.run(
            cmd, input=json.dumps({"documents": list(documents)}),
            capture_output=True, text=True,
            timeout=TIMEOUT_SECONDS, cwd=cwd,
            # The child must not inherit a pytest marker: luar_scorer is imported
            # there, and a suite-detection chokepoint keyed on PYTEST_CURRENT_TEST
            # would read the worker as a test and refuse the real work.
            env=_child_env(cwd))
    except subprocess.TimeoutExpired as exc:
        raise ScorerUnavailable(
            f"declared-env embedding timed out after {TIMEOUT_SECONDS}s") from exc
    except Exception as exc:                              # noqa: BLE001
        raise ScorerUnavailable(f"could not run uv: {exc}") from exc

    # The result file is the ONLY data channel. Read it once, delete it once,
    # and judge the run by what it holds -- stdout is prose from whatever the
    # model's remote code felt like printing.
    try:
        with open(out_path) as fh:
            payload = json.load(fh)
    except Exception:                                     # noqa: BLE001
        payload = None
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass

    if proc.returncode != 0 or payload is None or "error" in (payload or {}):
        # THE WORKER'S OWN MESSAGE FIRST, stderr only as a fallback. The worker
        # writes its failure into the result file and ALSO exits non-zero, so a
        # parent that reads only stderr throws away the one message written for
        # it. That is exactly what the first live run of this file did:
        # `declared-env embedding failed (exit 1): no stderr`, which named the
        # transport and hid the cause. Two halves of one protocol drifted despite
        # sitting in one file, which is why the fallback order is explicit here.
        detail = str((payload or {}).get("error") or "")
        if not detail:
            tail = (proc.stderr or "").strip().splitlines()
            detail = " | ".join(tail[-3:]) or "no output on stdout or stderr"
        raise ScorerUnavailable(
            f"declared-env embedding failed (exit {proc.returncode}): {detail}")
    vectors = payload.get("vectors")
    if not isinstance(vectors, list):
        raise ScorerUnavailable("declared-env worker returned no vectors")
    return vectors


class UvEnvBackend:
    """A `luar_scorer` backend whose `encode` happens in another process.

    Satisfies the same duck type as `TransformersBackend`: an `encode(documents)`
    returning one vector per document, and a `model_id` that rides into the
    emitted record. `model_id` deliberately reports the MODEL, not the transport,
    so a stored score is comparable with one computed in-process -- the number is
    the same computation either way, and recording the transport here would make
    two identical measurements look like two different instruments.
    """

    def __init__(self, model_id=None):
        from .luar_scorer import MODEL_ID
        self.model_id = model_id or MODEL_ID

    def encode(self, documents):
        return encode_via_declared_env(documents)


def _worker_main(argv):
    """Run INSIDE the declared environment. stdin -> a FILE, never stdout.

    STDOUT IS NOT A DATA CHANNEL HERE, and that is the whole point of the `--out`
    argument. `AutoModel.from_pretrained(trust_remote_code=True)` prints a
    multi-line custom-code notice to STDOUT, so the first version of this worker
    handed the parent 11717 bytes of prose with the JSON somewhere inside it and
    the parent reported `unparseable output` -- an error that describes the
    symptom and names nothing about the cause. Any library on this path may print
    at any time; the answer is not to silence them one at a time but to stop
    sharing a channel with them.

    Errors are written to the same file AND reported by a non-zero exit, so the
    parent never has to distinguish "crashed" from "answered with a failure".
    """
    out_path = argv[argv.index("--out") + 1] if "--out" in argv else None
    if not out_path:
        return 2
    try:
        # RELATIVE, like every other import of a sibling in this file. This was
        # `from pipeline.luar_scorer import ...` and it is the SECOND stale spelling
        # slice 12e left behind; fixing the `-m` name is what exposed it, because
        # until then the child died before reaching this line. The worker runs as
        # `-m voiceloop.luar_env_backend`, so it has a real package context and a
        # relative import cannot go stale on the next move.
        from .luar_scorer import TransformersBackend
        request = json.load(sys.stdin)
        vectors = TransformersBackend().encode(request["documents"])
        payload, code = {"vectors": vectors}, 0
    except Exception as exc:                              # noqa: BLE001
        payload, code = {"error": f"{type(exc).__name__}: {exc}"}, 1
    with open(out_path, "w") as fh:
        json.dump(payload, fh)
    return code


if __name__ == "__main__":
    sys.exit(_worker_main(sys.argv[1:]) if "--worker" in sys.argv[1:] else 2)
