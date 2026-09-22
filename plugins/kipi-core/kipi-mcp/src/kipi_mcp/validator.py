from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kipi_mcp.paths import KipiPaths
    from kipi_mcp.registry import RegistryManager

from kipi_mcp.leak_terms import load_scoped, term_patterns

# Kept as names for anyone importing them; the live lists come from the tripwire file through
# _leak_patterns() below (GitHub issue #2, PR B), so a fork edits one file, not this module.
KTLYST_PATTERNS = term_patterns(load_scoped(None)["instance"])
HARDCODED_PATH_PATTERNS = term_patterns(load_scoped(None)["path"]) + [r"q-ktlyst/"]

SWEEP_EXCLUDE_FILES = [
    "validate-separation",
    "instance-registry",
    "tripwire-terms",      # the roster of terms the sweep refuses carries them by design
    "PHASE-0-AUDIT",
    "EXECUTION-PLAN",
]

CANONICAL_FILES = [
    "discovery.md",
    "objections.md",
    "talk-tracks.md",
    "decisions.md",
    "engagement-playbook.md",
    "lead-lifecycle-rules.md",
    "market-intelligence.md",
    "pricing-framework.md",
    "verticals.md",
]

DOC_FILES = ["README.md"]


class Validator:
    def __init__(self, paths: KipiPaths, registry: RegistryManager):
        self.paths = paths
        self.repo_dir = paths.repo_dir
        self.registry = registry

    def run(self, phase: int = 5, verbose: bool = False) -> dict:
        checks: list[dict] = []
        errors: list[str] = []

        phase_methods = [
            (0, self._phase_0),
            (1, self._phase_1),
            (2, self._phase_2),
            (3, self._phase_3),
            (4, self._phase_4),
            (5, self._phase_5),
        ]

        for p, method in phase_methods:
            if p > phase:
                break
            try:
                if p == 1:
                    method(checks, verbose)
                else:
                    method(checks)
            except Exception as exc:
                errors.append(f"Phase {p} error: {exc}")

        passed = sum(1 for c in checks if c["result"] == "pass")
        failed = sum(1 for c in checks if c["result"] == "fail")
        warned = sum(1 for c in checks if c["result"] == "warn")

        return {
            "phase": phase,
            "passed": passed,
            "failed": failed,
            "warned": warned,
            "checks": checks,
            "errors": errors,
        }

    # -- Phase methods --

    def _phase_0(self, checks: list) -> None:
        self._check(
            checks,
            "Registry file exists",
            self.registry.registry_path.exists(),
        )
        self._check(
            checks,
            "q-system/ directory exists in skeleton",
            (self.repo_dir / "q-system").is_dir(),
        )
        for inst in self.registry.list_instances():
            p = Path(inst["path"])
            self._check(
                checks,
                f"Instance path exists: {inst['name']}",
                p.exists(),
                detail=str(p),
            )

    def _phase_1(self, checks: list, verbose: bool = False) -> None:
        agents_dir = (
            self.repo_dir / "q-system" / ".q-system" / "agent-pipeline" / "agents"
        )
        qsys = self.repo_dir / "q-system" / ".q-system"

        # Gate 1.1 - Agent files
        self._check(checks, "Agent directory exists", agents_dir.is_dir())

        if agents_dir.is_dir():
            md_files = [
                f
                for f in agents_dir.iterdir()
                if f.suffix == ".md"
                and not f.name.startswith("_")
                and not f.name.startswith("step-")
            ]
            self._check(
                checks,
                "Agent count >= 35",
                len(md_files) >= 35,
                detail=f"found {len(md_files)}",
            )

            numbered = [f for f in md_files if f.name[0:1].isdigit()]
            for f in numbered:
                text = f.read_text(errors="replace")
                lines = text.strip().splitlines()
                has_frontmatter = len(lines) > 0 and lines[0].strip() == "---"
                self._check(
                    checks,
                    f"YAML frontmatter: {f.name}",
                    has_frontmatter,
                )
                has_reads = bool(
                    re.search(r"^## Reads?\b", text, re.MULTILINE)
                )
                self._check(
                    checks,
                    f"Reads section: {f.name}",
                    has_reads,
                )

            ktlyst_hits = self._grep_dir(agents_dir, self._leak_patterns()[0])
            self._check(
                checks,
                "No KTLYST-specific terms in agents",
                len(ktlyst_hits) == 0,
                detail=", ".join(ktlyst_hits) if ktlyst_hits else None,
            )

            hardcoded_hits = self._grep_dir(agents_dir, HARDCODED_PATH_PATTERNS)
            self._check(
                checks,
                "No hardcoded paths in agents",
                len(hardcoded_hits) == 0,
                detail=", ".join(hardcoded_hits) if hardcoded_hits else None,
            )

        self._check(
            checks,
            "step-orchestrator.md exists",
            (agents_dir / "step-orchestrator.md").exists()
            if agents_dir.is_dir()
            else False,
        )
        self._check(
            checks,
            "Cadence config exists",
            (agents_dir / "_cadence-config.yaml").exists()
            or (agents_dir / "_cadence-config.md").exists()
            if agents_dir.is_dir()
            else False,
        )
        self._check(
            checks,
            "_auto-fail-checklist.md exists",
            (agents_dir / "_auto-fail-checklist.md").exists()
            if agents_dir.is_dir()
            else False,
        )

        # Gate 1.2 - Scripts (only hook scripts remain in q-system/)
        self._check(
            checks,
            "token-guard.py exists",
            (qsys / "hooks" / "token-guard.py").exists(),
        )

        # Migrated modules live in kipi_mcp package
        for mod_name in [
            "schedule_verifier", "bus_verifier", "orchestrator_verifier",
            "bus_bridge", "draft_scanner", "morning_auditor",
        ]:
            try:
                __import__(f"kipi_mcp.{mod_name}")
                self._check(checks, f"kipi_mcp.{mod_name} importable", True)
            except ImportError:
                self._check(checks, f"kipi_mcp.{mod_name} importable", False)

        # Gate 1.3 - Canonical templates
        canonical_dir = self.paths.canonical_dir
        for fname in CANONICAL_FILES:
            self._check(
                checks,
                f"canonical/{fname} exists",
                (canonical_dir / fname).exists(),
            )

        profile = self.paths.founder_profile
        self._check(checks, "founder-profile.md exists", profile.exists())
        if profile.exists():
            content = profile.read_text(errors="replace")
            self._check(
                checks,
                "founder-profile.md contains SETUP_NEEDED",
                "SETUP_NEEDED" in content,
            )

        # Gate 1.4 - Voice & AUDHD agent skills (delivered via skills/)
        skills_dir = self.repo_dir / "skills"
        self._check(
            checks,
            "founder-voice skill exists",
            (skills_dir / "founder-voice" / "SKILL.md").exists(),
        )
        self._check(
            checks,
            "audhd-executive-function skill exists",
            (skills_dir / "audhd-executive-function" / "SKILL.md").exists(),
        )

        # Gate 1.5 - Behavioral rules as agent skills (delivered via skills/, not CLAUDE.md)
        self._check(checks, "skills/ directory exists", skills_dir.is_dir())
        if skills_dir.is_dir():
            skill_dirs = [
                d for d in skills_dir.iterdir()
                if d.is_dir() and (d / "SKILL.md").exists()
            ]
            self._check(
                checks,
                "At least 28 skill directories in skills/",
                len(skill_dirs) >= 28,
                detail=f"found {len(skill_dirs)}",
            )
            skill_hits = self._grep_dir(skills_dir, self._leak_patterns()[0])
            self._check(
                checks,
                "No KTLYST refs in skills/",
                len(skill_hits) == 0,
                detail=", ".join(skill_hits) if skill_hits else None,
            )

        # Full skeleton sweep
        q_system_dir = self.repo_dir / "q-system"
        if q_system_dir.is_dir():
            all_patterns = self._leak_patterns()[0] + self._leak_patterns()[1]
            sweep_hits = self._grep_dir(
                q_system_dir, all_patterns, exclude_files=SWEEP_EXCLUDE_FILES
            )
            self._check(
                checks,
                "No KTLYST/hardcoded refs in q-system/ (full sweep)",
                len(sweep_hits) == 0,
                detail=", ".join(sweep_hits) if sweep_hits else None,
            )

    def _phase_2(self, checks: list) -> None:
        for inst in self.registry.list_instances():
            name = inst["name"]
            inst_path = Path(inst["path"])
            prefix = inst.get("subtree_prefix", "q-system")
            inst_type = inst.get("type", "subtree")
            instance_q_dir = inst.get("instance_q_dir")

            q_dir = inst_path / prefix / "q-system" if inst_type == "subtree" else inst_path / prefix
            self._check(
                checks,
                f"[{name}] q-system/ exists at {prefix}",
                (inst_path / prefix).is_dir() if inst_type == "subtree" else (inst_path / prefix).is_dir(),
                detail=str(inst_path / prefix),
            )

            if instance_q_dir:
                self._check(
                    checks,
                    f"[{name}] instance_q_dir exists",
                    (inst_path / instance_q_dir).is_dir(),
                    detail=str(inst_path / instance_q_dir),
                )

            if inst_type == "subtree":
                agents_dir = inst_path / prefix / ".q-system" / "agent-pipeline" / "agents"
            else:
                agents_dir = inst_path / ".q-system" / "agent-pipeline" / "agents"

            self._check(
                checks,
                f"[{name}] agents directory exists",
                agents_dir.is_dir(),
                detail=str(agents_dir),
            )

            if agents_dir.is_dir():
                md_files = [
                    f for f in agents_dir.iterdir()
                    if f.suffix == ".md"
                    and not f.name.startswith("_")
                    and not f.name.startswith("step-")
                ]
                threshold = 35 if inst_type == "subtree" else 15
                self._check(
                    checks,
                    f"[{name}] agent count >= {threshold}",
                    len(md_files) >= threshold,
                    detail=f"found {len(md_files)}",
                )

            # Instance data validation (CLAUDE.md no longer required —
            # behavioral rules are delivered via plugin skills/)

    def _phase_3(self, checks: list) -> None:
        for entry in self.registry.list_eliminated():
            name = entry.get("name", "unknown")
            path = entry.get("path")
            if path:
                self._check(
                    checks,
                    f"Eliminated plugin removed: {name}",
                    not Path(path).exists(),
                    detail=path,
                )

    def _phase_4(self, checks: list) -> None:
        for inst in self.registry.list_instances():
            name = inst["name"]
            inst_path = Path(inst["path"])
            inst_type = inst.get("type", "subtree")

            if inst_type == "subtree":
                agents_dir = inst_path / inst.get("subtree_prefix", "q-system") / ".q-system" / "agent-pipeline" / "agents"
            else:
                agents_dir = inst_path / ".q-system" / "agent-pipeline" / "agents"

            self._check(
                checks,
                f"[{name}] Phase 4: agents dir exists",
                agents_dir.is_dir(),
            )

            # Instance CLAUDE.md no longer required — behavioral rules
            # are delivered via plugin skills/

    def _phase_5(self, checks: list) -> None:
        for fname in DOC_FILES:
            self._check(
                checks,
                f"Documentation: {fname} exists",
                (self.repo_dir / fname).exists(),
            )

        for fname in DOC_FILES:
            fpath = self.repo_dir / fname
            if fpath.exists():
                hits = self._grep_dir(fpath.parent, self._leak_patterns()[0])
                doc_hits = [h for h in hits if Path(h).name == fname]
                self._check(
                    checks,
                    f"No KTLYST in {fname}",
                    len(doc_hits) == 0,
                    detail=", ".join(doc_hits) if doc_hits else None,
                )

    # -- Helpers --

    def _check(
        self,
        checks: list,
        description: str,
        passed: bool,
        detail: str | None = None,
    ) -> None:
        checks.append(
            {
                "description": description,
                "result": "pass" if passed else "fail",
                "detail": detail,
            }
        )

    def _leak_patterns(self) -> tuple[list[str], list[str]]:
        """(instance-name patterns, path patterns) from this repo's tripwire file, or the
        defaults. The sweeps here look for the instance's name and machine paths, the scopes
        this module always checked; content terms belong to the template gates."""
        scoped = load_scoped(self.repo_dir)
        names = term_patterns(scoped["instance"])
        paths = term_patterns(scoped["path"]) + [r"q-ktlyst/"]
        return names, paths

    def _grep_dir(
        self,
        directory: Path,
        patterns: list[str],
        exclude_files: list[str] | None = None,
    ) -> list[str]:
        matches: list[str] = []
        if not directory.is_dir():
            return matches

        compiled = [re.compile(p) for p in patterns]

        for fpath in directory.rglob("*"):
            if not fpath.is_file():
                continue
            if fpath.suffix in (".pyc", ".pyo", ".so", ".dylib", ".png", ".jpg", ".gif"):
                continue
            if exclude_files:
                if any(exc in fpath.name for exc in exclude_files):
                    continue
            try:
                text = fpath.read_text(errors="replace")
            except (OSError, PermissionError):
                continue
            for pat in compiled:
                if pat.search(text):
                    matches.append(str(fpath))
                    break

        return matches
