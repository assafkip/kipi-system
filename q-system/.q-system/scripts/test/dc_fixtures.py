#!/usr/bin/env python3
"""Design-chain test fixtures whose provenance is DATA (dc-21).

WHY. The gate was proven on verdicts typed by hand: `checks/impeccable.txt` written as "ran",
a standard.json with `pass: true`, a gap.json with an empty `below_floor`. A fixture typed to
satisfy the reader proves the reader matches the fixture and nothing about the producer
(RCA 2026-09-09 RC2; consulting's capture_payload.py, ASK-781, is the same lesson for
connector payloads, and this ports its contract). So every fixture here carries a
`_provenance` block naming the producer that wrote it, the command that ran, and when; and
`load()` refuses one without it, so a hand-typed fixture cannot be slipped into the suite.

A provenance block is a claim the same user could type. What it buys is that typing one is a
deliberate act a reviewer sees in the diff, not the path of least resistance.

    python3 dc_fixtures.py capture <name> --producer <script> --file <what it wrote> -- <cmd...>
        runs the command, then freezes the file it wrote
    python3 dc_fixtures.py import <name> --producer <script> --from <existing producer output>
        freezes an output a producer wrote earlier (records the source path, its sha and mtime)
"""
import argparse
import datetime as _dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "design-chain"
PROVENANCE_KEY = "_provenance"
REQUIRED = ("producer", "command", "captured_at")


class NotCaptured(ValueError):
    """A fixture with no provenance: it was typed, whatever its name says."""


def load(name: str) -> dict:
    """The fixture `name`, refused unless it carries producer, command and captured_at, each
    non-empty, and its content sha matches the one recorded at capture."""
    path = FIXTURES / f"{name}.json"
    doc = json.loads(path.read_text())
    prov = doc.get(PROVENANCE_KEY) if isinstance(doc, dict) else None
    if not isinstance(prov, dict):
        raise NotCaptured(f"{path.name} has no {PROVENANCE_KEY} block: a hand-typed fixture proves "
                          f"only that the reader matches it. Capture it: dc_fixtures.py capture ...")
    # a string with words in it: str(None) is the non-empty "None", which let a fixture whose
    # every field was null load (dc-21 adversarial review, finding-1)
    missing = [k for k in REQUIRED if not (isinstance(prov.get(k), str) and prov[k].strip())]
    if missing:
        raise NotCaptured(f"{path.name} {PROVENANCE_KEY} is missing {missing}")
    if not isinstance(doc.get("content"), str):
        raise NotCaptured(f"{path.name} carries no text content")
    got = hashlib.sha256(doc["content"].encode()).hexdigest()
    if prov.get("content_sha256") != got:
        raise NotCaptured(f"{path.name} content was edited after capture (sha {got[:12]} is not the "
                          f"recorded {str(prov.get('content_sha256'))[:12]})")
    # A REDACTED fixture is one whose captured bytes could not ship as captured: this repo is
    # public and one producer writes its own absolute path into its output, which the skeleton
    # sweep refuses. Redacting is allowed and excluding the file from the sweep is not (PR #374
    # review round 6, minor), but a redaction must not become a way to launder an ordinary edit.
    # So it has to say what it changed AND keep the pre-redaction sha, or it is not a redaction,
    # it is an edit with a nicer word on it.
    if prov.get("redactions") is not None:
        if not (isinstance(prov["redactions"], list) and prov["redactions"]
                and all(isinstance(r, str) and r.strip() for r in prov["redactions"])):
            raise NotCaptured(f"{path.name} claims redactions but does not say what they were")
        if not (isinstance(prov.get("captured_content_sha256"), str)
                and prov["captured_content_sha256"].strip()):
            raise NotCaptured(f"{path.name} was redacted without recording captured_content_sha256, "
                              f"so what the producer actually wrote can no longer be checked")
    return doc


def wrap(content: str, producer: str, command: str, captured_at: str, **extra) -> dict:
    prov = {"producer": producer, "command": command, "captured_at": captured_at,
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(), **extra}
    return {PROVENANCE_KEY: prov, "content": content}


def _write(name: str, doc: dict) -> Path:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    out = FIXTURES / f"{name}.json"
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("capture")
    c.add_argument("name")
    c.add_argument("--producer", required=True)
    c.add_argument("--file", required=True)
    i = sub.add_parser("import")
    i.add_argument("name")
    i.add_argument("--producer", required=True)
    i.add_argument("--from", dest="src", required=True)
    cmd = argv[argv.index("--") + 1:] if "--" in argv else []
    a = ap.parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    if a.mode == "capture":
        if not cmd:
            print("capture: give the producer command after --", file=sys.stderr)
            return 2
        r = subprocess.run(cmd, capture_output=True, text=True)
        f = Path(a.file)
        if not f.is_file():
            print(f"capture: {f} was not written (exit {r.returncode}): {r.stderr[-400:]}", file=sys.stderr)
            return 2
        doc = wrap(f.read_text(), a.producer, " ".join(cmd), now, exit_code=r.returncode)
    else:
        src = Path(a.src)
        data = src.read_text()
        mtime = _dt.datetime.fromtimestamp(src.stat().st_mtime, _dt.timezone.utc).isoformat(timespec="seconds")
        doc = wrap(data, a.producer, f"copied from {src} (written by {a.producer})", mtime,
                   source=str(src), source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(), frozen_at=now)
    print(f"wrote {_write(a.name, doc)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
