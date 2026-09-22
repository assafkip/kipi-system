"""The instance-content leak terms, read from ONE file (GitHub issue #2, PR B).

WHY. Three validators each carried their own copy of the terms that must never leave an
instance for the skeleton (the instance's name, its confidential content, the author's home
path): validator.py, git_ops.py and validate-separation.py. A fork's first act was editing all
three, or accepting that the gates were silently about someone else's instance.
kipi-push-upstream.sh and kipi-promote.sh already read
q-system/.q-system/scripts/tripwire-terms.txt; this makes the Python consumers read the same
file, so a fork edits one list and every gate follows.

THE FILE. Plain terms, one per line; # comments and blank lines are ignored, so the shell
consumers (which take every non-comment line) are unchanged. A comment line of the form
`# scope: instance|content|path` opens a section, and each gate reads the scopes it always
read: the skeleton-wide sweeps look for the INSTANCE name and machine PATHS (a skeleton must
carry neither), while the template and voice gates also refuse CONTENT terms (a client's
role, an incident, the author's name), which a script in the skeleton may legitimately name
in a detector. Terms before any scope header are `content`; a scope this module does not
know (the file has a `shell` section only the push and promote scripts read) is skipped.
Terms are matched literally.

When the file is absent (an old checkout, a test fixture built without it) the defaults are
the terms as they stood before this module existed, so behaviour is unchanged for a tree that
never opted in.
"""
from __future__ import annotations

import re
from pathlib import Path

TRIPWIRE_REL = Path("q-system") / ".q-system" / "scripts" / "tripwire-terms.txt"
SCOPES = ("instance", "content", "path")

# the lists the three consumers carried, merged and scoped; used only when the file is absent
DEFAULT_SCOPED = {
    "instance": ["KTLYST", "ktlyst", "q-ktlyst"],
    "content": ["re-breach", "re.breach", "CISO", "Assaf"],
    "path": ["/Users/assafkip"],
}
DEFAULT_TERMS = [t for s in SCOPES for t in DEFAULT_SCOPED[s]]

_SCOPE_RE = re.compile(r"^\s*#\s*scope:\s*([a-z]+)\s*$")


def load_scoped(repo_dir: Path | None) -> dict[str, list[str]]:
    """{scope: terms} from the tripwire file under `repo_dir`, else DEFAULT_SCOPED."""
    if repo_dir is not None:
        f = Path(repo_dir) / TRIPWIRE_REL
        if f.is_file():
            out: dict[str, list[str]] = {s: [] for s in SCOPES}
            scope: str | None = "content"
            for ln in f.read_text().splitlines():
                m = _SCOPE_RE.match(ln)
                if m:
                    scope = m.group(1) if m.group(1) in SCOPES else None   # unknown scope: skipped
                    continue
                t = ln.strip()
                if t and not t.startswith("#") and scope is not None:
                    out[scope].append(t)
            if any(out.values()):
                return out
    return {s: list(v) for s, v in DEFAULT_SCOPED.items()}


def load_terms(repo_dir: Path | None) -> list[str]:
    """Every term, all scopes, in file order: what the shell consumers see."""
    scoped = load_scoped(repo_dir)
    return [t for s in SCOPES for t in scoped[s]]


def term_patterns(terms: list[str]) -> list[str]:
    """Regexes matching each term literally, for consumers that grep with re."""
    return [re.escape(t) for t in terms]


def path_terms(terms: list[str]) -> list[str]:
    """The subset that names a filesystem path (a machine-specific leak rather than a name)."""
    return [t for t in terms if "/" in t]
