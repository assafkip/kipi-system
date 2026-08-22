#!/usr/bin/env python3
"""evidence_ledger: the durable store of verified facts, and the single writer to it.

WHY (RCA rca-conclusions-before-evidence-2026-07-28): six conclusions were delivered
in settled language and reversed later in the same session by evidence available from
the first minute. One reached a client email draft. Measurements survived
recomputation; inferences did not. This module stores only the survivors, and it
cannot store anything else: a row without a `command` and a `result` is refused, so an
inference cannot be written in the shape of a measurement.

Lesson applied: "store the evidence, derive the conclusions". `system-map.md` and any
client-facing draft become DERIVED views of this file, not independent prose.

HONEST BOUNDARY (stated so this is not theater): this module guarantees that a stored
row records a command and its output. It does NOT verify the command was actually run,
that its output was transcribed faithfully, or that the claim follows from the result.
Those are behavioral. What it removes is the ability to be ambiguous about which kind
of statement you are making.

Layout: `<instance-root>/canonical/evidence.jsonl`, append-only JSONL, one verified
fact per line:
  {claim_id, claim, source, command, result, verified_at}

CLI:
  python3 evidence_ledger.py add --claim C --source S --command CMD --result R
  python3 evidence_ledger.py list [--json]
  python3 evidence_ledger.py check          # exit 2 if any row is malformed
  python3 evidence_ledger.py resolve FILE   # exit 2 if a number/quote does not trace

stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_FIELDS = ("claim_id", "claim", "source", "command", "result", "verified_at")

# A number a client would act on. Single digits are list markers and ordinals far more
# often than claims, so the floor is 2 significant digits. Stated hole, not a silent one.
NUM_RE = re.compile(r"(?<![\w.$])(\d[\d,]*\.?\d*)(?![\w])")
MIN_SIGNIFICANT_DIGITS = 2

# A date is not a measurement a client acts on, and treating it as one made the gate
# unusable (sp-f551ef30, ASK-232): `zach-info-request.md` blocked on ['13','2026'],
# both of which fell out of a date. The only ways past that are to invent ledger rows
# for calendar facts or to bypass the gate -- each worse than the gate not firing.
#
# Two shapes are dropped before the number scan:
#   ISO dates   2026-07-28   removed whole, so 07 and 28 never become "numbers"
#   bare years  1900..2100   a standalone year is a date, not a count
# `13` in "13 workflows" is NOT a date and stays gated. That is the line this draws.
#
# HONEST BOUNDARY: a real measurement that happens to be a 4-digit number in
# 1900..2100 ("2026 orders shipped") is exempted and will pass unbacked. Declared
# hole, not a silent one -- the alternative blocks every draft that names a year.
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
YEAR_MIN, YEAR_MAX = 1900, 2100


def _is_year(norm: str) -> bool:
    return len(norm) == 4 and norm.isdigit() and YEAR_MIN <= int(norm) <= YEAR_MAX

# A quoted span long enough to be an attribution rather than a turn of phrase.
SPAN_RE = re.compile(r"[\"“]([^\"”\n]{3,300})[\"”]")
MIN_SPAN_WORDS = 4


class LedgerError(Exception):
    """A write that would put an unverifiable row in the ledger."""


# --------------------------------------------------------------------------- paths

class ResolutionError(Exception):
    """The canonical root is ambiguous or contradicted. Refuse rather than guess."""


def _registry_path(repo: Path) -> Path:
    """The fleet registry. Skeleton-local, which is the only copy that exists.

    NOT ~/.kipi-system/instance-registry.json -- paths.py:188 points there and that
    file does not exist on this machine or any other (sp-b2c21bdc, measured
    2026-08-22). Fleet root convention matches verify-alert-wiring.sh:16.
    """
    env = os.environ.get("KIPI_EVIDENCE_REGISTRY")
    if env:
        return Path(env)
    local = repo / "instance-registry.json"
    if local.is_file():
        return local
    fleet = Path(os.environ.get("KIPI_FLEET_ROOT") or (Path.home() / "projects"))
    return fleet / "kipi-system" / "instance-registry.json"


def _registry_q_dir(repo: Path) -> tuple[str | None, bool]:
    """(instance_q_dir, found) for this repo, read from the registry.

    found=False means the repo is not a registered instance at all, which is a
    different thing from a registered instance whose q_dir is null.
    """
    reg = _registry_path(repo)
    if not reg.is_file():
        return None, False
    try:
        data = json.loads(reg.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ResolutionError(f"registry {reg} is unreadable: {exc}")
    target = repo.resolve()
    for entry in data.get("instances", []):
        try:
            if Path(entry.get("path", "")).resolve() == target:
                return entry.get("instance_q_dir"), True
        except Exception:
            continue
    skel = data.get("skeleton") or {}
    skel_path = skel.get("path") if isinstance(skel, dict) else None
    if skel_path:
        try:
            if Path(skel_path).resolve() == target:
                return "q-system", True
        except Exception:
            pass
    return None, False


def _named_canonical_dirs(repo: Path) -> list[Path]:
    """Filesystem evidence: named q-* domain dirs that actually hold canonical/."""
    return [p for p in sorted(repo.glob("q-*"))
            if p.is_dir() and p.name != "q-system" and (p / "canonical").is_dir()]


def instance_root(repo=None, strict: bool = True,
                  allow_unregistered: bool = False) -> Path:
    """The dir holding this instance's canonical/ content. FAILS CLOSED.

    WHY (scar, measured 2026-08-22 across all 25 registered instances):

      The previous body was `named[0] if named else repo/"q-system"` -- a pure glob
      with no registry and no cross-check. It could not be wrong out loud. Three
      measured failure modes, each of which it answered confidently:

        * 6 of 25 instances: registry says instance_q_dir=null while a real named
          domain dir holding canonical/ exists on disk. Two authorities disagreeing
          on a quarter of the fleet is a defect, not a design. (PRD said 4 of 20;
          re-measured at HEAD it is 6 of 25 -- the count decayed, the defect did not.)
        * 3 of 25: resolve to a directory with NO canonical/ at all, and the caller
          gets a path to a tree that is not there.
        * Two named q-* dirs both holding canonical/: sorted()[0] silently wins.
          ZERO instances hit this today, so it is covered by a synthetic fixture,
          not by a fleet instance -- the hazard is in the code regardless.

      Registry is authority; the filesystem is a cross-check that RAISES on
      mismatch. strict=False restores the old guessing behaviour and exists only
      for callers that must degrade rather than refuse; it is not the default
      because a silently wrong canonical path is the whole reason this PRD exists.

    `allow_unregistered` is the NARROW middle ground, and the distinction is the
    hazard, not the caller's convenience:

      WRITE callers (ledger_path -> add/append) keep the default and REFUSE. Codex
      flagged the real danger as an unattended run from a stray clone APPENDING
      evidence against the wrong tree; that stays refused.

      READ-ONLY callers that must keep running (system_manifest.health, whose own
      docstring promises it never raises because a Stop hook depends on it) pass
      allow_unregistered=True. They still get the AMBIGUITY and no-canonical
      refusals, so this never restores the sorted()[0] guess between two candidate
      domain dirs -- it only permits the single-tree repo that has exactly one
      possible answer.

    SCAR 2026-08-22: the first version of this guard refused on `not registered`
    unconditionally. That is a coarser rule than the hazard, and it broke 11 tests
    in test_grounding_manifest_health.py plus, worse, made the grounding Stop hook
    emit "the manifest is unreadable" on a HEALTHY manifest -- a live false alarm
    on every turn, which is exactly the fleet-wide wedge health() was written to
    avoid. Blast radius was measured for the paths.py resolver and not for this
    one; that asymmetry is the actual defect.
    """
    repo = Path(repo or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    named = _named_canonical_dirs(repo)

    if not strict:
        return named[0] if named else repo / "q-system"

    if len(named) > 1:
        raise ResolutionError(
            f"{repo}: {len(named)} named q-* dirs hold canonical/ "
            f"({', '.join(p.name for p in named)}). Refusing to let sorted()[0] pick. "
            f"Set instance_q_dir in the registry to disambiguate."
        )

    q_dir, registered = _registry_q_dir(repo)
    fs_pick = named[0].name if named else None

    # An UNREGISTERED repo has no mapping, and strict mode must not invent one.
    # SCAR (Codex review of PR #240, major): the `else` arm below fell through to
    # repo/"q-system" for ANY unregistered checkout whose q-system/ happened to hold
    # canonical/, and returned it as authoritative -- measured from an isolated review
    # tree as registered=False, resolved=<tree>/q-system. That is the exact defect
    # class this resolver exists to remove: guess quietly rather than refuse out loud.
    # Refused here, at the one place that knows, so both downstream arms are covered
    # rather than patching the q-system arm alone.
    # _registry_q_dir already resolves the SKELETON row (returns "q-system", True), so
    # kipi-system itself stays registered and this does not refuse the skeleton.
    if not registered and not allow_unregistered:
        raise ResolutionError(
            f"{repo}: not a registered instance and not the skeleton. Refusing to "
            f"resolve a canonical root by guessing. Add it to the registry, pass "
            f"allow_unregistered=True if you are a READ-ONLY caller that must "
            f"degrade, or strict=False for the full legacy guess."
        )

    if registered and q_dir:
        if fs_pick and fs_pick != q_dir:
            raise ResolutionError(
                f"{repo}: registry says instance_q_dir={q_dir!r} but the filesystem "
                f"shows {fs_pick!r} holding canonical/. Refusing to guess which is right."
            )
        root = repo / q_dir
    elif fs_pick:
        if registered:
            raise ResolutionError(
                f"{repo}: {fs_pick!r} holds canonical/ but the registry records "
                f"instance_q_dir=null. Fill it in so the two agree; refusing to "
                f"let the glob silently outvote the registry."
            )
        root = named[0]
    else:
        root = repo / "q-system"

    if not (root / "canonical").is_dir():
        raise ResolutionError(
            f"{repo}: resolved canonical root {root} has no canonical/ subdirectory. "
            f"There is no canonical tree here; refusing to return a path to nothing."
        )
    return root


def audit_instance_roots(registry=None) -> list[dict]:
    """Enumerate how every registered instance resolves, so no caller hand-maintains
    a list of affected instance names. This repo is PUBLIC; names stay local."""
    reg = Path(registry) if registry else _registry_path(Path.cwd())
    data = json.loads(reg.read_text(encoding="utf-8"))
    rows = []
    for entry in data.get("instances", []):
        name, path = entry.get("name"), Path(entry.get("path", ""))
        row = {"name": name, "path": str(path), "registry_q_dir": entry.get("instance_q_dir")}
        if not path.is_dir():
            row.update(status="absent", resolved=None, detail="path not on disk")
            rows.append(row)
            continue
        row["filesystem_q_dir"] = (_named_canonical_dirs(path)[0].name
                                   if _named_canonical_dirs(path) else None)
        try:
            row.update(status="ok", resolved=str(instance_root(path)), detail="")
        except ResolutionError as exc:
            row.update(status="REFUSED", resolved=None, detail=str(exc))
        rows.append(row)
    return rows


def ledger_path(repo=None, allow_unregistered: bool = True) -> Path:
    """Where the evidence ledger lives.

    Permissive BY DEFAULT, and that is deliberate. `read`, `check` and
    `has_ledger` all come through here, so a refusal on this accessor refuses
    every READER -- which is how one guard took out the grounding Stop hook and
    the client-output evidence gate in a single change (2026-08-22).

    The write path opts INTO the refusal explicitly; see append_row.
    """
    return instance_root(repo, allow_unregistered=allow_unregistered) / "canonical" / "evidence.jsonl"


# ---------------------------------------------------------------------- read/write

def read(repo=None) -> list[dict]:
    """Every row, in insertion order. A missing ledger is empty, not an error."""
    path = ledger_path(repo)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue  # `check` reports it; `read` stays usable
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def make_claim_id(claim: str, source: str, command: str) -> str:
    digest = hashlib.sha256(f"{claim}\x00{source}\x00{command}".encode()).hexdigest()
    return f"ev-{digest[:10]}"


def _validate(row: dict) -> list[str]:
    errs = []
    for field in REQUIRED_FIELDS:
        if not str(row.get(field, "")).strip():
            errs.append(f"missing or empty `{field}`")
    return errs


def append_row(repo, row: dict) -> dict:
    """The single write path. Every field required; claim_id unique; append only."""
    # THE REFUSAL LIVES HERE, at the single write path, not on the shared resolver.
    # Codex's hazard was an unattended run APPENDING evidence against the wrong
    # canonical tree -- a property of the OPERATION, not of the repository. Guarding
    # the repository instead swept in every read-only caller; two rounds of
    # per-caller opt-ins later, the surface was the problem, not the callers.
    path = ledger_path(repo, allow_unregistered=False)

    errs = _validate(row)
    if errs:
        raise LedgerError(
            "refusing to write an unverifiable evidence row: " + "; ".join(errs) +
            ". A claim with no command and no result is an inference, not a "
            "measurement -- record it as {{UNVERIFIED}} prose instead."
        )
    existing = {r.get("claim_id") for r in read(repo)}
    if row["claim_id"] in existing:
        raise LedgerError(
            f"claim_id {row['claim_id']} is already in the ledger. The ledger is "
            "append-only and single-writer; re-verifying a claim means adding a row "
            "with a new command, not rewriting the old one."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def add(repo=None, *, claim: str, source: str, command: str, result: str,
        verified_at: str | None = None) -> dict:
    """Build and append a row. claim_id derives from content, so it is reproducible."""
    row = {
        "claim_id": make_claim_id(claim, source, command),
        "claim": claim,
        "source": source,
        "command": command,
        "result": result,
        "verified_at": verified_at or datetime.now(timezone.utc)
                                             .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return append_row(repo, row)


def check(repo=None) -> list[str]:
    """Standing validator over the whole file. Returns human-readable problems."""
    path = ledger_path(repo)
    if not path.exists():
        return []
    problems, seen = [], set()
    for n, line in enumerate(path.read_text(encoding="utf-8",
                                            errors="ignore").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            problems.append(f"line {n}: not valid JSON ({exc})")
            continue
        if not isinstance(row, dict):
            problems.append(f"line {n}: row is not an object")
            continue
        for err in _validate(row):
            problems.append(f"line {n}: {err}")
        cid = row.get("claim_id")
        if cid in seen:
            problems.append(f"line {n}: duplicate claim_id {cid}")
        seen.add(cid)
    return problems


# ------------------------------------------------------------------- resolution

def _norm_number(raw: str) -> str:
    """`1,177` and `1177` are the same measurement. Compare on digits."""
    return raw.replace(",", "").rstrip(".").lstrip("0") or "0"


def _evidence_blob(repo=None) -> str:
    return "\n".join(f"{r.get('claim','')}\n{r.get('result','')}\n{r.get('command','')}"
                     for r in read(repo))


def adopted(repo=None) -> bool:
    """Has this instance started keeping a ledger at all?

    WHY (ASK-233): with no ledger, every row lookup misses, so EVERY number in a
    client draft is unbacked and the first write to output/outreach/ blocks on all
    of them at once. The gate was most hostile exactly where it had zero signal to
    offer, which is a wall rather than incremental adoption -- and 21 instances
    received these scripts with no ledger in any of them.

    An absent ledger is now "not adopted yet" and the gate stands down. A ledger
    with even one row means the instance opted in, and enforcement is full strength
    from that point on. The file's existence is the switch.
    """
    return ledger_path(repo).exists()


def resolve_numbers(repo, text: str) -> list[str]:
    """Numbers in `text` that trace to no ledger row. Empty list = everything traces."""
    if not adopted(repo):
        return []
    text = ISO_DATE_RE.sub(" ", text)  # a date is not a measurement; see ISO_DATE_RE
    grounded = {_norm_number(m.group(1)) for m in NUM_RE.finditer(_evidence_blob(repo))}
    missing = []
    for m in NUM_RE.finditer(text):
        norm = _norm_number(m.group(1))
        if len(norm.replace(".", "")) < MIN_SIGNIFICANT_DIGITS:
            continue
        if _is_year(norm):
            continue
        if norm in grounded:
            continue
        missing.append(norm)
    return sorted(set(missing), key=lambda s: (len(s), s))


def resolve_spans(repo, text: str) -> list[str]:
    """Quoted spans in `text` that appear in no ledger row."""
    if not adopted(repo):
        return []
    blob = _evidence_blob(repo).lower()
    missing = []
    for m in SPAN_RE.finditer(text):
        span = m.group(1).strip()
        if len(span.split()) < MIN_SPAN_WORDS:
            continue
        if span.lower() in blob:
            continue
        missing.append(span)
    return sorted(set(missing))


# -------------------------------------------------------------------------- CLI

def _run_audit(argv) -> int:
    """`--audit-instance-roots` is a flag, not a subcommand, because the PRD and the
    issue acceptance both name it that way and a checker copies the string verbatim."""
    reg = None
    if "--registry" in argv:
        reg = argv[argv.index("--registry") + 1]
    rows = audit_instance_roots(reg)
    if "--json" in argv:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{r['status']:<8} {r['name']:<22} registry={str(r['registry_q_dir']):<14} "
                  f"fs={str(r.get('filesystem_q_dir')):<14} {r['detail']}")
    bad = [r for r in rows if r["status"] == "REFUSED"]
    if "--json" not in argv:
        print(f"\n{len(rows)} registered, {len(bad)} REFUSED by the fail-closed resolver")

    # SCAR (Codex review of PR #240, major). This returned a hardcoded 0 on every
    # path, so the one command that enumerates unresolvable instances could not
    # fail for the reason it exists -- a caller wiring it as a check would get a
    # green on a fleet where the resolver refuses. Exit 1 when any instance is
    # REFUSED; exit 2 reserved for the command itself breaking.
    #
    # This is non-zero on the live fleet TODAY and that is the correct report, not
    # a regression: the registry fill that would clear those rows is deliberately
    # out of this PR (the client-name guard refuses client-derived names in this
    # PUBLIC repo, sp-71c71288). `--allow-refused` exists for the enumerating
    # callers that want the rows without the verdict, and it is opt-in per call so
    # it cannot silently become the default posture.
    if bad and "--allow-refused" not in argv:
        sys.stderr.write(
            f"evidence_ledger: {len(bad)} of {len(rows)} registered instances are "
            f"REFUSED by the fail-closed resolver. Fill instance_q_dir in the "
            f"registry so it agrees with the filesystem, or pass --allow-refused "
            f"to enumerate without failing.\n"
        )
        return 1
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--audit-instance-roots" in argv:
        return _run_audit(argv)

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=None, help="repo root (default: CLAUDE_PROJECT_DIR)")
    ap.add_argument("--audit-instance-roots", action="store_true",
                    help="report how every registered instance resolves (handled above)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="append one verified fact")
    for f in ("claim", "source", "command", "result"):
        a.add_argument(f"--{f}", required=True)
    a.add_argument("--verified-at", default=None)

    lst = sub.add_parser("list", help="print the ledger")
    lst.add_argument("--json", action="store_true")

    sub.add_parser("check", help="validate every row; exit 2 on any problem")

    r = sub.add_parser("resolve", help="check a file's numbers and quotes trace to rows")
    r.add_argument("path")

    args = ap.parse_args(argv)
    repo = args.repo

    if args.cmd == "add":
        try:
            row = add(repo, claim=args.claim, source=args.source, command=args.command,
                      result=args.result, verified_at=args.verified_at)
        except LedgerError as exc:
            sys.stderr.write(f"evidence_ledger: {exc}\n")
            return 2
        print(row["claim_id"])
        return 0

    if args.cmd == "list":
        rows = read(repo)
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            for row in rows:
                print(f"{row.get('claim_id')}  {row.get('claim')}\n"
                      f"    source : {row.get('source')}\n"
                      f"    command: {row.get('command')}\n"
                      f"    result : {row.get('result')}\n"
                      f"    at     : {row.get('verified_at')}")
        return 0

    if args.cmd == "check":
        problems = check(repo)
        if problems:
            sys.stderr.write("evidence_ledger check FAILED:\n" +
                             "\n".join(f"  - {p}" for p in problems) + "\n")
            return 2
        print(f"evidence_ledger check OK ({len(read(repo))} rows)")
        return 0

    if args.cmd == "resolve":
        text = Path(args.path).read_text(encoding="utf-8", errors="ignore")
        nums = resolve_numbers(repo, text)
        spans = resolve_spans(repo, text)
        if nums or spans:
            sys.stderr.write("evidence_ledger resolve FAILED for " + args.path + "\n")
            for n in nums:
                sys.stderr.write(f"  - number {n} traces to no ledger row\n")
            for s in spans:
                sys.stderr.write(f'  - quote "{s}" traces to no ledger row\n')
            return 2
        print(f"evidence_ledger resolve OK ({args.path})")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
