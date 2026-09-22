"""The leak terms come from one file, and every consumer reads it (GitHub issue #2, PR B).

Temp trees only. A term that exists ONLY in a fixture's tripwire file has to be detected by
each consumer, or the consumer is still reading its own copy.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from kipi_mcp.git_ops import GitOps
from kipi_mcp.leak_terms import DEFAULT_SCOPED, DEFAULT_TERMS, TRIPWIRE_REL, load_scoped, load_terms, path_terms, term_patterns

REPO_ROOT = Path(__file__).resolve().parents[4]


def _tripwire(root: Path, terms: list[str]) -> Path:
    f = root / TRIPWIRE_REL
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# comment\n\n" + "\n".join(terms) + "\n")
    return f


def test_defaults_are_the_lists_the_consumers_carried(tmp_path):
    assert load_terms(tmp_path) == DEFAULT_TERMS          # no file: unchanged behaviour
    assert load_terms(None) == DEFAULT_TERMS
    for t in ("KTLYST", "ktlyst", "CISO", "re-breach", "/Users/assafkip"):
        assert t in DEFAULT_TERMS


def test_the_file_wins_and_comments_are_ignored(tmp_path):
    _tripwire(tmp_path, ["ACME", "acme", "/home/acme/"])
    assert load_terms(tmp_path) == ["ACME", "acme", "/home/acme/"]
    assert path_terms(load_terms(tmp_path)) == ["/home/acme/"]
    assert term_patterns(["re.breach"]) == [r"re\.breach"]
    # no scope header: everything is content, and the sweeps see nothing
    assert load_scoped(tmp_path) == {"instance": [], "content": ["ACME", "acme", "/home/acme/"], "path": []}


def test_scope_headers_route_terms(tmp_path):
    _tripwire(tmp_path, ["# scope: instance", "ACME", "acme", "# scope: content", "the incident", "# scope: path", "/home/acme/",
                         "# scope: shell", "/home/", "# scope: content", "more"])
    assert load_scoped(tmp_path) == {"instance": ["ACME", "acme"], "content": ["the incident", "more"], "path": ["/home/acme/"]}
    assert "/home/" not in load_terms(tmp_path)          # an unknown scope is not folded anywhere
    assert load_scoped(None) == DEFAULT_SCOPED


def test_the_shipped_file_carries_the_default_terms():
    # the repo's own tripwire file is a superset of what the consumers used to hardcode, scope for scope
    shipped = load_scoped(REPO_ROOT)
    assert (REPO_ROOT / TRIPWIRE_REL).is_file()
    for scope, terms in DEFAULT_SCOPED.items():
        for t in terms:
            assert t in shipped[scope], (scope, t)
    # and the shell consumers still see the bare home-path term the push tripwire always had
    raw = [ln.strip() for ln in (REPO_ROOT / TRIPWIRE_REL).read_text().splitlines()
           if ln.strip() and not ln.lstrip().startswith("#")]
    assert "/Users/" in raw


def test_git_ops_reads_the_subtree_tripwire(tmp_path, mocker):
    prefix = tmp_path / "q-system"
    (prefix / ".q-system" / "scripts").mkdir(parents=True)
    (prefix / ".q-system" / "scripts" / "tripwire-terms.txt").write_text("ACME\n/home/acme/\n")
    seen = []

    def side_effect(args, **kwargs):
        seen.append(args[2])
        class R:
            returncode, stdout = 1, ""
        return R()

    mocker.patch("subprocess.run", side_effect=side_effect)
    GitOps("https://example.invalid/x.git", "main").check_instance_content(prefix)
    assert seen == ["ACME", "/home/acme/"]


def test_validator_detects_a_term_only_the_file_names(tmp_path):
    # the validator is exercised through its own test helpers so the fixture shape is theirs
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_validator as tv
    paths, repo_dir = tv._build_skeleton(tmp_path)
    registry = tv._make_registry(tmp_path, repo_dir)
    _tripwire(repo_dir, ["# scope: instance", "ACMEWIDGETS"])
    agents_dir = repo_dir / "q-system" / ".q-system" / "agent-pipeline" / "agents"
    (agents_dir / "02-agent-2.md").write_text("---\ntitle: Agent\n---\n\n## Reads\n- ACMEWIDGETS data\n")
    v = tv.Validator(paths, registry)
    result = v.run(phase=1)
    checks = [c for c in result["checks"] if "agents" in c["description"] and "KTLYST" in c["description"]]
    assert checks and any(c["result"] == "fail" for c in checks), checks


def test_validate_separation_reads_the_same_file(tmp_path, monkeypatch):
    src = REPO_ROOT / "validate-separation.py"
    spec = importlib.util.spec_from_file_location("vsep", src)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.load_tripwire_terms() == load_terms(REPO_ROOT)
    monkeypatch.setattr(m, "TRIPWIRE_TERMS_FILE", str(tmp_path / "missing.txt"))
    assert m.load_tripwire_terms() == [t for s in ("instance", "content", "path") for t in m._DEFAULT_LEAK_SCOPED[s]]
    (tmp_path / "t.txt").write_text("# scope: instance\nACME\n# scope: content\nthe incident\n# scope: path\n/home/acme/\n")
    monkeypatch.setattr(m, "TRIPWIRE_TERMS_FILE", str(tmp_path / "t.txt"))
    assert m.leak_instance_patterns() == ["ACME"]
    assert m.leak_name_patterns() == ["ACME", "the\\ incident"]
    assert m.leak_path_patterns() == ["/home/acme/", r"q-ktlyst/"]
    assert m.leak_regex() == "ACME|/home/acme/"
    assert m.leak_regex("instance", "content") == "ACME|the\\ incident"
    # and no gate in that file still carries its own literal list: the only occurrences of the
    # old terms are inside the one default block the loader falls back to
    text = src.read_text()
    body = text.replace('"instance": ["KTLYST", "ktlyst", "q-ktlyst"],', "").replace('"path": ["/Users/assafkip"]}', "")
    assert 'r"KTLYST"' not in body
    assert "/Users/assafkip" not in body
