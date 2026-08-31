#!/usr/bin/env python3
"""The channel vocabulary has ONE owner, and an instance without one is unchanged.

Every assertion about the no-registry case writes the pre-change literals out by
hand rather than importing them. A test that reads `DEFAULT` and asserts against
`DEFAULT` cannot see an edit to DEFAULT, which is the one edit that would silently
change 27 instances.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import channel_registry as cr           # noqa: E402
from voiceloop import corpus, validate                 # noqa: E402


# The literals that lived in validate.py at lines 110 / 120 / 138 / 293 before
# this module existed. Typed here, imported from nowhere.
PRE_CHANGE_SCOPES = ("linkedin", "x", "substack", "medium", "dm", "email", "comment")
PRE_CHANGE_ASSEMBLED = ("linkedin", "x")
PRE_CHANGE_CHECKED_SLOTS = (("linkedin", "post"), ("linkedin", "comment"),
                            ("x", "post"), ("x", "comment"))


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(obj, handle)
    return path


def _corrections(tmp_path, scope):
    """A voice dir holding exactly one correction with this scope."""
    d = tmp_path / "voice"
    d.mkdir(exist_ok=True)
    row = {"id": "r-1", "date": "2026-08-30", "instruction": "no CTA here",
           "class": "interpretive", "status": "active", "scope": [scope]}
    (d / corpus.CORRECTIONS).write_text(json.dumps(row) + "\n", encoding="utf-8")
    return str(d / corpus.CORRECTIONS)


# --- the hard constraint: no registry is byte-identical to before -----------------

class TestAnInstanceWithNoRegistry:
    def test_default_is_the_pre_change_literals(self):
        assert cr.DEFAULT.scopes == PRE_CHANGE_SCOPES
        assert cr.DEFAULT.assembled == PRE_CHANGE_ASSEMBLED
        assert cr.DEFAULT.source is None

    def test_checked_slots_is_the_pre_change_tuple(self):
        assert validate.checked_slots() == PRE_CHANGE_CHECKED_SLOTS
        assert validate.CHECKED_SLOTS == PRE_CHANGE_CHECKED_SLOTS

    def test_an_empty_instance_resolves_to_nothing(self, tmp_path):
        assert cr.resolve(str(tmp_path)) is None
        assert cr.for_instance(str(tmp_path)) == cr.DEFAULT

    def test_load_of_none_is_the_default(self):
        assert cr.load(None) is cr.DEFAULT

    def test_reddit_is_still_refused_without_a_registry(self, tmp_path):
        """The behavior sp-6c93d3d8 recorded, unchanged where no registry exists."""
        problems = validate.check_corrections(_corrections(tmp_path, "reddit"))
        assert any("unknown scope 'reddit'" in p for p in problems), problems


# --- resolution, the shape copied from the Stop-gate -----------------------------

class TestResolve:
    def test_the_in_repo_registry_wins(self, tmp_path):
        p = _write(os.path.join(str(tmp_path), cr.REGISTRY_REL), {})
        assert cr.resolve(str(tmp_path)) == p

    def test_a_pointer_names_a_registry_outside_the_synced_tree(self, tmp_path):
        target = _write(os.path.join(str(tmp_path), "config", "voice-channels.json"),
                        {"channel_vocabulary": {"reddit": ["scope"],
                                                "linkedin": ["scope", "assembled"]}})
        pointer = os.path.join(str(tmp_path), cr.POINTER_REL)
        os.makedirs(os.path.dirname(pointer), exist_ok=True)
        with open(pointer, "w", encoding="utf-8") as handle:
            handle.write("# where this instance keeps it\nconfig/voice-channels.json\n")
        assert cr.resolve(str(tmp_path)) == os.path.realpath(target)

    def test_a_pointer_to_a_missing_file_still_names_it(self, tmp_path):
        """Not None. The caller must be able to say WHICH file is missing."""
        pointer = os.path.join(str(tmp_path), cr.POINTER_REL)
        os.makedirs(os.path.dirname(pointer), exist_ok=True)
        with open(pointer, "w", encoding="utf-8") as handle:
            handle.write("config/gone.json\n")
        named = cr.resolve(str(tmp_path))
        assert named and named.endswith("gone.json")
        with pytest.raises(cr.ChannelRegistryError) as exc:
            cr.load(named)
        assert "gone.json" in str(exc.value)

    def test_an_empty_pointer_is_no_registry(self, tmp_path):
        pointer = os.path.join(str(tmp_path), cr.POINTER_REL)
        os.makedirs(os.path.dirname(pointer), exist_ok=True)
        with open(pointer, "w", encoding="utf-8") as handle:
            handle.write("# nothing but a comment\n\n")
        assert cr.resolve(str(tmp_path)) is None


# --- the derivation is BOUND to the registry, not merely equal to it -------------

class TestTheDerivationFollowsTheRegistry:
    VOCAB = {"linkedin": ["scope", "assembled"], "x": ["scope", "assembled"],
             "substack": ["scope"], "medium": ["scope"], "dm": ["scope"],
             "email": ["scope"], "comment": ["scope"], "reddit": ["scope"]}

    def _load(self, tmp_path, vocab):
        return cr.load(_write(os.path.join(str(tmp_path), cr.REGISTRY_REL),
                              {"channel_vocabulary": vocab}))

    def test_reddit_becomes_a_legal_scope(self, tmp_path):
        ch = self._load(tmp_path, self.VOCAB)
        assert "reddit" in ch.scopes
        assert "reddit" not in ch.assembled, "reddit owns no pool; it must not"
        assert validate.check_corrections(_corrections(tmp_path, "reddit"), ch) == []

    @pytest.mark.parametrize("dropped", sorted(set(VOCAB) - {"linkedin"}))
    def test_dropping_a_channel_drops_it_from_the_derived_set(self, tmp_path, dropped):
        """Bound, not equal. Every channel in the registry, one at a time, so a
        derivation that happened to match the literal cannot pass this."""
        vocab = {k: v for k, v in self.VOCAB.items() if k != dropped}
        ch = self._load(tmp_path, vocab)
        assert dropped not in ch.scopes
        assert dropped not in ch.assembled
        problems = validate.check_corrections(_corrections(tmp_path, dropped), ch)
        assert any(f"unknown scope {dropped!r}" in p for p in problems), problems

    def test_adding_an_assembled_channel_reaches_the_pool_and_budget_checks(
            self, tmp_path):
        vocab = dict(self.VOCAB, substack=["scope", "assembled"])
        ch = self._load(tmp_path, vocab)
        assert ch.assembled == ("linkedin", "x", "substack")
        assert ("substack", "post") in validate.checked_slots(ch)
        voice = corpus.load(str(tmp_path / "empty-voice"))
        assert any(p.startswith("pool (substack") for p in
                   validate.check_pools(voice, ch))

    def test_a_registry_without_a_vocabulary_changes_nothing(self, tmp_path):
        """The live surface-only registries must keep answering only what they did."""
        ch = cr.load(_write(os.path.join(str(tmp_path), cr.REGISTRY_REL),
                            {"channels": {"reddit": {"lint": "reddit_persona_lint"}}}))
        assert ch is cr.DEFAULT


# --- fail closed -----------------------------------------------------------------

class TestAPresentRegistryThatCannotBeTrusted:
    def _raises(self, tmp_path, payload, needle):
        path = os.path.join(str(tmp_path), cr.REGISTRY_REL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload if isinstance(payload, str) else json.dumps(payload))
        with pytest.raises(cr.ChannelRegistryError) as exc:
            cr.load(path)
        assert needle in str(exc.value), str(exc.value)

    def test_malformed_json(self, tmp_path):
        self._raises(tmp_path, "{not json", "malformed")

    def test_not_an_object(self, tmp_path):
        self._raises(tmp_path, ["linkedin"], "must be an object")

    def test_vocabulary_is_not_an_object(self, tmp_path):
        self._raises(tmp_path, {"channel_vocabulary": ["linkedin"]},
                     "channel_vocabulary must be an object")

    def test_roles_are_not_a_list(self, tmp_path):
        self._raises(tmp_path, {"channel_vocabulary": {"linkedin": "scope"}},
                     "must be a list")

    def test_a_typod_role_is_refused_rather_than_ignored(self, tmp_path):
        """`assembeled` silently dropping linkedin out of the budget check would
        read exactly like a healthy corpus."""
        self._raises(tmp_path,
                     {"channel_vocabulary": {"linkedin": ["scope", "assembeled"]}},
                     "unknown role 'assembeled'")

    def test_an_empty_scope_axis_is_refused(self, tmp_path):
        self._raises(tmp_path, {"channel_vocabulary": {"linkedin": ["assembled"]}},
                     "every correction scope would be refused")

    def test_an_empty_assembled_axis_is_refused(self, tmp_path):
        """A guard that grades nothing and reports healthy is worse than no guard."""
        self._raises(tmp_path, {"channel_vocabulary": {"linkedin": ["scope"]}},
                     "report healthy")


# --- structural: no site may own a private copy again ----------------------------

# Channel names that are ONLY ever channels. "dm" / "comment" / "email" are
# deliberately absent: they are also `EXEMPLAR_KINDS` and `SLOT_KINDS` values, so
# matching them would fire on `("post", "comment")`, which is a slot kind and not
# a channel. A detector that fires on the wrong thing gets deleted, and then
# nothing checks the real thing.
UNAMBIGUOUS_CHANNELS = ("linkedin", "x", "substack", "medium", "reddit")


def _channel_literals(source):
    """Channel names appearing as STRING CONSTANTS in code, docstrings and comments
    excluded. A grep over the raw text always fails here (every one of these names
    is discussed in a scar comment), so it would be deleted as noise rather than
    kept as a check."""
    import ast
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = node.body[0] if node.body else None
            if (isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant)
                    and isinstance(doc.value.value, str)):
                docstrings.add(id(doc.value))
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings
                and node.value in UNAMBIGUOUS_CHANNELS):
            found.add(node.value)
    return found


# From the IMPORTED module, never from this file's path. The public mirror puts
# tests/ at the repo root while the skeleton puts them inside the package, so a
# dirname walk finds validate.py in one tree and nothing in the other. Asking the
# module where it lives also checks the copy that actually got imported.
VALIDATE_PY = os.path.abspath(validate.__file__)


def test_validate_holds_no_channel_literal():
    """The mutation this whole change exists to prevent is someone adding the
    nineteenth hardcoded site. Four sites in this file each owned the set, so the
    check is on the SOURCE and not on any one behavior."""
    found = _channel_literals(open(VALIDATE_PY, encoding="utf-8").read())
    assert found == set(), (
        f"validate.py names {sorted(found)} directly; the channel vocabulary "
        f"belongs to channel_registry")


def test_the_literal_detector_can_fail():
    """Negative self-test. The check above is green on a file that also has every
    channel name written across its comments, so "it passed" proves nothing until
    the same detector is shown going red on the exact defect it guards."""
    mutated = open(VALIDATE_PY, encoding="utf-8").read().replace(
        "for channel in channels.assembled:",
        'for channel in ("linkedin", "x"):', 1)
    assert _channel_literals(mutated) == {"linkedin", "x"}
