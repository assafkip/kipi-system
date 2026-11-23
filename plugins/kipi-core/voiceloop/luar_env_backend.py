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

import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

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

#: Bound on BUILDING the env once (resolve + wheels), and on waiting for the one
#: process that is building it. Measured 2026-10-30: a cold build was 66s, exit 0.
#: 300s is 4x that; past it the build is hung, not slow.
BUILD_TIMEOUT_SECONDS = int(os.environ.get("KIPI_LUAR_ENV_BUILD_TIMEOUT", "300"))

#: Set by verify.sh to a per-run directory. Its presence means "share the build
#: verdict (ok or failed) across every pytest worker of this run".
STATE_DIR_ENV = "KIPI_LUAR_ENV_STATE_DIR"

#: Every failure of the env step carries this name, so a red test names its cause
#: instead of reading as a model or scorer defect.
ENV_ERROR_NAME = "LUAR_ENV_UNAVAILABLE"

_IN_PROCESS_OK = set()

#: Env keys this process took on the reuse path, past the build floor. Their
#: worker runs with HF_HUB_OFFLINE=1 so a model fetch cannot happen under the
#: floor that reuse skipped (PR #872 review, minor 2).
_REUSED = set()

#: LUAR gets its OWN caches on the internal disk (ASK-3515, measured 2026-10-30).
#: The fleet-wide UV_CACHE_DIR / HF_HOME point at /Volumes/Storage, where a file
#: open costs about 160 ms against 0.75 ms on the internal disk (20 opens: 3.28s
#: vs 0.015s). Importing torch + transformers touches thousands of small files, so
#: one worker took 80s to 300s+ and 10 to 25 concurrent workers thrashed the volume
#: until nothing finished. Scoped to this child only: the fleet env is untouched.
MIN_FREE_BYTES = int(float(os.environ.get("KIPI_LUAR_MIN_FREE_GB", "5")) * 1024 ** 3)
MODEL_DIR = "models--rrivera1849--LUAR-MUD"

#: Bound on the offline reuse probe. Measured 2026-11-23 on the built env:
#: `uv run --offline ... -c pass` took 0.11s. 60s is far past slow; it is hung.
OFFLINE_CHECK_TIMEOUT_SECONDS = int(os.environ.get("KIPI_LUAR_OFFLINE_CHECK_TIMEOUT", "60"))

#: Hard floor for REUSE. Reuse downloads nothing (--offline) and needs a completed
#: env already on disk, but uv may still write metadata or clones; under 1 GB the
#: machine is too close to the 2026-10-30 disk-full event to run anything here.
REUSE_MIN_FREE_BYTES = int(float(os.environ.get("KIPI_LUAR_REUSE_MIN_FREE_GB", "1")) * 1024 ** 3)


def _cache_root():
    return os.environ.get("KIPI_LUAR_CACHE_DIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "kipi-luar")


def _local_cache_env():
    root = _cache_root()
    return {"UV_CACHE_DIR": os.path.join(root, "uv"),
            "HF_HOME": os.path.join(root, "hf")}


def _seed_hf_model(dest_hf):
    """Copy the LUAR-MUD snapshot from the fleet HF cache once; never re-download.

    A missing source is not an error here: the worker then downloads as it did
    before, and the build/worker bounds still apply.
    """
    dst = os.path.join(dest_hf, "hub", MODEL_DIR)
    if os.path.isdir(dst):
        return
    src_home = os.environ.get("KIPI_LUAR_SEED_HF") or os.environ.get("HF_HOME") or \
        os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
    src = os.path.join(src_home, "hub", MODEL_DIR)
    if not os.path.isdir(src) or os.path.realpath(src_home) == os.path.realpath(dest_hf):
        return
    os.makedirs(os.path.join(dest_hf, "hub"), exist_ok=True)
    tmp = dst + f".part{os.getpid()}"
    shutil.copytree(src, tmp, symlinks=True)
    os.replace(tmp, dst)


def _env_key():
    h = hashlib.sha256()
    h.update(PYTHON_PIN.encode())
    try:
        with open(REQUIREMENTS, "rb") as fh:
            h.update(fh.read())
    except OSError:
        pass
    return h.hexdigest()[:16]


def _run_bounded(cmd, cwd, env, timeout):
    """Run `cmd`; on timeout kill its whole process group and return (None, "").

    Scar (ASK-3515, 2026-10-30): `subprocess.run(timeout=)` kills only the direct
    child. `uv run` spawns python under it, so a timed-out run left descendants
    holding the uv cache lock at 0% CPU. A new session lets killpg take the lot.
    """
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        _, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.communicate()
        return None, ""
    return proc.returncode, err or ""


def ensure_declared_env():
    """Build (or verify) the uv env ONCE, bounded, and fail fast when it cannot be.

    ASK-3515 scar, 2026-10-30: after a disk-full event every xdist worker ran its
    own `uv run --with-requirements ...`; 30 workers sat at 0% CPU, wrote 81 empty
    luar-vectors files, and two commits hung 54 and 77 minutes. One builder under
    a lock, a bounded build, and a shared verdict make the other workers either
    reuse the env or fail at once with a NAMED error. Never a silent skip.
    """
    from .luar_scorer import ScorerUnavailable
    key = _env_key()
    if key in _IN_PROCESS_OK:
        return
    state_dir = os.environ.get(STATE_DIR_ENV)
    lock_dir = state_dir or os.path.join(
        os.environ.get("TMPDIR") or "/tmp", f"kipi-luar-env-{os.getuid()}")
    os.makedirs(lock_dir, exist_ok=True)
    marker = os.path.join(lock_dir, f"verdict-{key}.json") if state_dir else None

    def verdict():
        if not marker:
            return None
        try:
            with open(marker) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def fail(detail):
        raise ScorerUnavailable(f"{ENV_ERROR_NAME}: {detail}")

    deadline = time.monotonic() + BUILD_TIMEOUT_SECONDS
    lock_fh = open(os.path.join(lock_dir, f"build-{key}.lock"), "w")
    try:
        while True:
            try:
                fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                v = verdict()
                if v and v.get("status") == "failed":
                    fail(v.get("detail", "an earlier build in this run failed"))
                if time.monotonic() >= deadline:
                    fail(f"waited {BUILD_TIMEOUT_SECONDS}s for another process "
                         "to build the env")
                time.sleep(0.2)
        v = verdict()
        if v and v.get("status") == "ok":
            _IN_PROCESS_OK.add(key)
            return
        if v and v.get("status") == "failed":
            fail(v.get("detail", "an earlier build in this run failed"))
        cache = _local_cache_env()
        cwd = os.path.dirname(HERE)
        reusable, why_not = _built_env_reusable(cache, cwd)
        if reusable:
            _record(marker, {"status": "ok"})
            _IN_PROCESS_OK.add(key)
            _REUSED.add(key)
            return
        os.makedirs(cache["UV_CACHE_DIR"], exist_ok=True)
        free = shutil.disk_usage(cache["UV_CACHE_DIR"]).free
        if free < MIN_FREE_BYTES:
            # Never build or seed into a nearly full disk: it hit 313 MiB free on
            # 2026-10-30 and the half-written torch install is what followed.
            fail(f"internal disk has {free // 2**20} MiB free, need "
                 f"{MIN_FREE_BYTES // 2**20} MiB before building the LUAR env"
                 + (f"; {why_not}" if why_not else ""))
        try:
            _seed_hf_model(cache["HF_HOME"])
        except OSError as exc:
            fail(f"could not seed the LUAR model into {cache['HF_HOME']}: {exc}")
        cmd = ["uv", "run", "--python", PYTHON_PIN,
               "--with-requirements", REQUIREMENTS, "python3", "-c", "pass"]
        try:
            rc, err = _run_bounded(cmd, cwd, _child_env(cwd), BUILD_TIMEOUT_SECONDS)
        except OSError as exc:
            rc, err = -1, str(exc)
        if rc == 0:
            result = {"status": "ok"}
        elif rc is None:
            result = {"status": "failed",
                      "detail": f"env build timed out after {BUILD_TIMEOUT_SECONDS}s"}
        else:
            tail = " | ".join(err.strip().splitlines()[-3:]) or "no stderr"
            result = {"status": "failed",
                      "detail": f"env build failed (exit {rc}): {tail}"}
        _record(marker, result)
        if result["status"] != "ok":
            fail(result["detail"])
        _IN_PROCESS_OK.add(key)
    finally:
        lock_fh.close()


def _record(marker, result):
    if not marker:
        return
    tmp = marker + f".{os.getpid()}"
    with open(tmp, "w") as fh:
        json.dump(result, fh)
    os.replace(tmp, marker)


def _model_snapshot_complete(hf_home):
    """A snapshot with config and weights that resolve, and no half-downloaded blob.

    PR #872 review (P2): a bare model dir is what an interrupted download leaves,
    and the worker's from_pretrained would then resume the download under the floor.
    """
    root = os.path.join(hf_home, "hub", MODEL_DIR)
    blobs = os.path.join(root, "blobs")
    if os.path.isdir(blobs) and any(n.endswith(".incomplete") for n in os.listdir(blobs)):
        return False
    snaps = os.path.join(root, "snapshots")
    if not os.path.isdir(snaps):
        return False
    for snap in os.listdir(snaps):
        d = os.path.join(snaps, snap)
        has_cfg = any(os.path.isfile(os.path.join(d, n)) for n in ("config.json", "config.py"))
        has_w = any(os.path.isfile(os.path.join(d, n))
                    for n in ("model.safetensors", "pytorch_model.bin"))
        if has_cfg and has_w:
            return True
    return False


def _env_installed(uv_dir):
    """A uv `--with` env that already holds torch and transformers.

    PR #872 review (P1): `--offline` only disables the network; with wheels cached
    but the env evicted, uv would re-install gigabytes before the floor ran. So
    reuse needs the finished env on disk, read without running uv.
    """
    envs = os.path.join(uv_dir, "environments-v2")
    if not os.path.isdir(envs):
        return False
    # Measured 2026-11-23 (uv on this Mac): environments-v2/<key>/<key2> is a
    # symlink into archive-v0/<id>, which is the venv. Both depths are read.
    candidates = []
    for name in os.listdir(envs):
        top = os.path.join(envs, name)
        candidates.append(top)
        if os.path.isdir(top):
            candidates.extend(os.path.join(top, c) for c in os.listdir(top))
    for env in candidates:
        lib = os.path.join(env, "lib")
        if not os.path.isdir(lib):
            continue
        for py in os.listdir(lib):
            sp = os.path.join(lib, py, "site-packages")
            if all(os.path.isdir(os.path.join(sp, m)) for m in ("torch", "transformers")):
                return True
    return False


def _built_env_reusable(cache, cwd):
    """True when the env and model are already on disk and resolve offline.

    ASK-5577 scar, 2026-11-23: the free-disk floor ran in every new process, so
    at 4086 MiB free every CRM "Draft comment" failed with LUAR_ENV_UNAVAILABLE
    while a built 4.4 GB env sat in ~/.cache/kipi-luar. The floor exists to stop
    a BUILD or SEED into a full disk; reusing what is built writes nothing big.
    The env and the model are proven on disk first, without running uv; only
    then does a bounded `--offline` probe confirm uv resolves to them, so a
    probe that would need a download fails and the floor applies as before.

    Returns (reusable, why_not). why_not is "" when nothing was there to reuse,
    so a refusal names a failed probe instead of reading as plain low disk
    (PR #872 review, minor 1).
    """
    uv_dir = cache["UV_CACHE_DIR"]
    if not _model_snapshot_complete(cache["HF_HOME"]) or not _env_installed(uv_dir):
        return False, ""
    free = shutil.disk_usage(uv_dir).free
    if free < REUSE_MIN_FREE_BYTES:
        return False, (f"reuse refused too: {free // 2**20} MiB free, reuse needs "
                       f"{REUSE_MIN_FREE_BYTES // 2**20} MiB")
    cmd = ["uv", "run", "--offline", "--python", PYTHON_PIN,
           "--with-requirements", REQUIREMENTS, "python3", "-c", "pass"]
    try:
        rc, err = _run_bounded(cmd, cwd, _child_env(cwd), OFFLINE_CHECK_TIMEOUT_SECONDS)
    except OSError as exc:
        return False, f"offline reuse check could not run: {exc}"
    if rc == 0:
        return True, ""
    if rc is None:
        return False, f"offline reuse check timed out after {OFFLINE_CHECK_TIMEOUT_SECONDS}s"
    tail = " | ".join(err.strip().splitlines()[-2:]) or "no stderr"
    return False, f"offline reuse check failed (exit {rc}): {tail}"


def _worker_env(cwd):
    env = _child_env(cwd)
    if _env_key() in _REUSED:
        env["HF_HUB_OFFLINE"] = "1"
    return env


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
    env.update(_local_cache_env())
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (f"{package_parent}{os.pathsep}{existing}"
                         if existing else package_parent)
    return env


def encode_via_declared_env(documents, windowed_text=None, windowed_texts=None):
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

    if windowed_texts is not None and not list(windowed_texts):
        raise ScorerUnavailable("encode_windowed_many needs at least one text")
    if not _uv_available():
        raise ScorerUnavailable(
            "uv is not on PATH, so the declared authorship environment "
            f"({os.path.basename(REQUIREMENTS)}) cannot be built")
    if not os.path.isfile(REQUIREMENTS):
        raise ScorerUnavailable(f"missing requirements file: {REQUIREMENTS}")

    ensure_declared_env()

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
            cmd, input=json.dumps(_request(documents, windowed_text, windowed_texts)),
            capture_output=True, text=True,
            timeout=TIMEOUT_SECONDS, cwd=cwd,
            # The child must not inherit a pytest marker: luar_scorer is imported
            # there, and a suite-detection chokepoint keyed on PYTEST_CURRENT_TEST
            # would read the worker as a test and refuse the real work.
            env=_worker_env(cwd))
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
    if windowed_texts is not None:
        _check_many(payload, vectors, windowed_texts, documents)
        return payload
    if windowed_text is not None:
        if not isinstance(payload.get("window_vectors"), list):
            raise ScorerUnavailable("declared-env worker returned no windows")
        return payload
    return vectors


def _check_many(payload, vectors, texts, documents):
    """The batch reply crosses a process boundary, so each text's entry gets the
    same re-plan the single-text path gets in score(). Scar: a head-only window
    list labelled windowed-512 reads 1,200 tokens on 504 and reports share 1.0
    (PR #837); the first cut of this batch path checked only the list length, and
    a [{}, None, 7] reply passed (PR #869 review)."""
    from .luar_scorer import ScorerUnavailable, WINDOW_TOKENS, plan_windows
    per_text = payload.get("per_text")
    if not isinstance(per_text, list) or len(per_text) != len(texts):
        raise ScorerUnavailable("declared-env worker returned no per-text windows")
    if len(vectors) != len(documents):
        raise ScorerUnavailable("declared-env worker returned the wrong vector count")
    for i, rec in enumerate(per_text):
        try:
            planned = len(plan_windows(int(rec["tokens"]), WINDOW_TOKENS))
            ok = (len(rec["window_vectors"]) == planned
                  and 0.0 <= float(rec["share_read"]) <= 1.0)
        except (KeyError, TypeError, ValueError):
            ok = False
        if not ok:
            raise ScorerUnavailable(
                f"declared-env worker returned a malformed window list for text #{i}")


def _request(documents, windowed_text, windowed_texts=None):
    # ONE child per score (ASK-5358): the draft's windows are cut and embedded in
    # the same process that embeds the exemplars, so the 319MB load is not paid
    # twice to read a long draft.
    req = {"documents": list(documents)}
    if windowed_text is not None:
        req["windowed_text"] = windowed_text
    if windowed_texts is not None:
        # ASK-5540: N drafts, one child, so the model load is paid once.
        req["windowed_texts"] = list(windowed_texts)
    return req


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

    def encode_windowed(self, text, documents):
        return encode_via_declared_env(documents, windowed_text=text)

    def encode_windowed_many(self, texts, documents):
        return encode_via_declared_env(documents, windowed_texts=list(texts))


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
        backend = TransformersBackend()
        if "windowed_texts" in request:
            payload = backend.encode_windowed_many(request["windowed_texts"],
                                                   request["documents"])
        elif "windowed_text" in request:
            payload = backend.encode_windowed(request["windowed_text"],
                                              request["documents"])
        else:
            payload = {"vectors": backend.encode(request["documents"])}
        code = 0
    except Exception as exc:                              # noqa: BLE001
        payload, code = {"error": f"{type(exc).__name__}: {exc}"}, 1
    with open(out_path, "w") as fh:
        json.dump(payload, fh)
    return code


if __name__ == "__main__" and "--ensure" in sys.argv[1:]:
    try:
        ensure_declared_env()
        sys.exit(0)
    except Exception as _exc:                             # noqa: BLE001
        print(_exc, file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    sys.exit(_worker_main(sys.argv[1:]) if "--worker" in sys.argv[1:] else 2)
