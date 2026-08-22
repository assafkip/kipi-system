from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

CANONICAL_DIGEST = "canonical-digest.json"


def _canonical_content_present() -> bool:
    """True when the resolved canonical dir actually holds canonical content.

    SEQUENCING GUARD (PRD finding-27). canonical-digest.json must become a REQUIRED
    phase-1 file, but promoting it while paths.py still resolves canonical_dir to
    {plugin-data}/instances/<name>/canonical -- a directory measured to hold ZERO
    files -- turns every phase-1 run red on all 23 instances at once. So the
    promotion is computed, not typed: optional until the path contract lands
    (srsa-authoritative-path-contract), required automatically afterwards.

    SCAR (Codex review of PR #240, blocker). The first version of this guard asked
    "does canonical_dir resolve under the plugin-data base?" -- and
    `KipiPaths.canonical_dir` is DEFINED as `{base}/instances/<name>/canonical`
    where `{base}` is exactly `KIPI_PLUGIN_DATA` or `~/.kipi-system`. The answer
    was therefore yes for every reachable configuration. It was a tautology
    wearing a predicate's clothes: the required branch could only be entered by
    monkeypatching this function, so the digest check shipped permanently optional
    and the "make it able to fail" fix was inert in production.

    Emptiness is the condition the docstring above actually names, and unlike a
    path prefix it can be observed BOTH ways through the real code path: an empty
    tree yields False (no outage today), a populated one yields True. When the
    path contract repoints canonical_dir at a live tree, the promotion happens on
    its own with no edit here.
    """
    from kipi_mcp.paths import KipiPaths

    canonical = KipiPaths().canonical_dir
    if not canonical.is_dir():
        return False
    return any(p.is_file() for p in canonical.iterdir())


def canonical_digest_is_required() -> bool:
    """The promotion predicate. Public so its BOTH branches can be tested; a
    predicate whose false branch is never exercised reports success by default.

    Fails toward NOT-required. A crash here must not be able to cause the outage
    the sequencing guard exists to prevent.
    """
    try:
        return _canonical_content_present()
    except Exception:
        return False  # cannot tell -> stay optional -> no outage


def _canonical_digest_substantive(d: dict) -> bool:
    """Reject a digest that parsed nothing, without asserting digest["valid"].

    Calibrated against measurement, not intuition (2026-08-22):
      * the LIVE tree yields decisions=10, objections=5, warnings=0 -> PASSES,
        even though its valid is False and its talk_tracks are all empty because
        those files were retired to pointer docs. Requiring talk_tracks here would
        red every run against real data.
      * the captured all-empty digest has decisions=[], objections=[], 5 warnings
        -> FAILS.
      * Codex finding-14's nonempty placeholder
        {"talk_tracks":{"metaphor":"placeholder"},"objections":[],"decisions":[],...}
        -> FAILS. Key-presence and "some field is nonempty" both accept it, which
        is exactly why neither is used.
    """
    if not all(k in d for k in ("talk_tracks", "objections", "decisions")):
        return False
    if not isinstance(d.get("decisions"), list) or not d["decisions"]:
        return False
    if not isinstance(d.get("objections"), list) or not d["objections"]:
        return False
    return len(d.get("warnings") or []) < 3


class BusVerifier:
    def __init__(self, bus_dir: Path):
        self._bus_dir = bus_dir

    def verify(self, date: str, phase: int) -> dict:
        bus_day = self._bus_dir / date

        if not bus_day.is_dir():
            return {
                "pass": False,
                "phase": phase,
                "date": date,
                "results": [{"status": "fail", "type": "required", "file": "",
                              "detail": f"Bus directory does not exist: {bus_day}"}],
            }

        spec = self._phase_specs().get(phase)
        if spec is None:
            return {"pass": True, "phase": phase, "date": date, "results": []}

        required = list(spec.get("required", []))
        optional = list(spec.get("optional", []))
        checks = spec.get("checks", {})

        # REACHABILITY (PRD defect 1). canonical-digest.json sat in phase 1's `checks`
        # dict but in neither `required` nor `optional`, so its lambda was never once
        # invoked -- dead code that read as protection. Wire it into a list, promoting
        # to required only when the path contract makes that survivable.
        if phase == 1 and CANONICAL_DIGEST not in required and CANONICAL_DIGEST not in optional:
            (required if canonical_digest_is_required() else optional).append(CANONICAL_DIGEST)

        day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A").lower()
        if phase == 4 and day_name in ("tuesday", "thursday"):
            if "tl-content.json" in optional:
                optional.remove("tl-content.json")
            if "tl-content.json" not in required:
                required.append("tl-content.json")

        results: list[dict] = []
        all_pass = True

        for f in required:
            path = bus_day / f
            if not path.is_file():
                results.append({"status": "fail", "type": "required", "file": f, "detail": "MISSING"})
                all_pass = False
                continue
            try:
                data = json.loads(path.read_text())
                if "error" in data:
                    # ERROR SHORT-CIRCUIT (PRD defect 3, the one the first draft missed).
                    # This branch used to emit `warn` and leave all_pass untouched, so a
                    # REQUIRED file containing {"error": "..."} produced pass:true -- and
                    # it survived both the reachability and the substance fix, because it
                    # returns before either is consulted. A required file that carries an
                    # error produced nothing; that is a hard fail, same as MISSING.
                    results.append({"status": "fail", "type": "required", "file": f,
                                    "detail": f"has error key ({data['error']})"})
                    all_pass = False
                elif f in checks and not checks[f](data):
                    results.append({"status": "fail", "type": "required", "file": f,
                                    "detail": "structure check failed"})
                    all_pass = False
                else:
                    results.append({"status": "ok", "type": "required", "file": f, "detail": ""})
            except json.JSONDecodeError as e:
                results.append({"status": "fail", "type": "required", "file": f,
                                "detail": f"invalid JSON ({e})"})
                all_pass = False

        for f in optional:
            path = bus_day / f
            if not path.is_file():
                results.append({"status": "skip", "type": "optional", "file": f, "detail": "not present"})
                continue
            try:
                data = json.loads(path.read_text())
                if "error" in data:
                    results.append({"status": "warn", "type": "optional", "file": f,
                                    "detail": "has error key"})
                elif f in checks and not checks[f](data):
                    results.append({"status": "warn", "type": "optional", "file": f,
                                    "detail": "structure check failed"})
                else:
                    results.append({"status": "ok", "type": "optional", "file": f, "detail": ""})
            except json.JSONDecodeError:
                results.append({"status": "warn", "type": "optional", "file": f,
                                "detail": "invalid JSON"})

        return {"pass": all_pass, "phase": phase, "date": date, "results": results}

    @staticmethod
    def _phase_specs() -> dict:
        return {
            0: {
                "required": ["preflight.json", "energy.json"],
                "checks": {
                    "preflight.json": lambda d: d.get("ready") is True,
                    "energy.json": lambda d: d.get("level") in range(1, 6),
                },
            },
            1: {
                "required": ["calendar.json", "gmail.json", "notion.json"],
                "optional": ["vc-pipeline.json", "content-metrics.json", "copy-diffs.json"],
                "checks": {
                    "calendar.json": lambda d: "today" in d or "this_week" in d,
                    "gmail.json": lambda d: "emails" in d,
                    "notion.json": lambda d: "contacts" in d and "actions" in d,
                    # SUBSTANCE (PRD defect 2). Was key-presence only, which passes an
                    # all-empty digest and passes Codex finding-14's nonempty placeholder.
                    CANONICAL_DIGEST: _canonical_digest_substantive,
                },
            },
            2: {
                "required": ["meeting-prep.json", "warm-intros.json"],
                "checks": {},
            },
            3: {
                "required": ["linkedin-posts.json", "linkedin-dms.json", "dp-pipeline.json"],
                "optional": ["behavioral-signals.json", "prospect-activity.json"],
                "checks": {
                    "linkedin-posts.json": lambda d: "posts" in d,
                    "linkedin-dms.json": lambda d: "dms" in d,
                    "behavioral-signals.json": lambda d: "signals" in d,
                },
            },
            4: {
                "required": ["signals.json"],
                "optional": ["value-routing.json", "post-visuals.json", "promo.json", "tl-content.json"],
                "checks": {
                    "signals.json": lambda d: "selected_signal" in d or "linkedin_draft" in d,
                },
            },
            5: {
                "required": ["temperature.json", "leads.json", "hitlist.json"],
                "optional": ["pipeline-followup.json", "loop-review.json"],
                "checks": {
                    "hitlist.json": lambda d: "actions" in d and len(d["actions"]) > 0,
                    "temperature.json": lambda d: "scores" in d or "prospects" in d,
                },
            },
            6: {
                "required": ["compliance.json", "positioning.json"],
                "checks": {
                    "compliance.json": lambda d: "overall_pass" in d or "items_checked" in d,
                },
            },
            7: {
                "required": [],
                "optional": ["outreach-queue.json"],
                "checks": {
                    "outreach-queue.json": lambda d: "queue" in d,
                },
            },
            9: {
                "required": [],
                "optional": ["notion-push.json", "daily-checklists.json"],
                "checks": {},
            },
        }
