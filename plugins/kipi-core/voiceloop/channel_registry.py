#!/usr/bin/env python3
"""The channel vocabulary this engine validates against, and its ONE owner.

WHY THIS FILE EXISTS (sp-6c93d3d8, measured 2026-08-30). `validate.py` restated
channel membership FOUR times in one file: the correction-scope allowlist, the
`check_pools` loop, `CHECKED_SLOTS`, and `check_budget`'s default. A founder
correction scoped to "reddit" was refused by the first of those, and the fleet
had eighteen hardcoded channel sites for the same reason. Adding "reddit" to the
allowlist would have made it the nineteenth site and left three more disagreeing
inside the same file. Shotgun Surgery has a named cure and it is not one more
literal: derive the value from its owner.

TWO AXES, NOT ONE. Collapsing them is the same defect one level in.

- SCOPE: which channel names a correction may be scoped to. Seven today.
- ASSEMBLED: which channels the assembler actually builds a prompt for, so which
  ones must clear the pool floor, the anchor-rotation floor and the char budget.
  Two today. A channel can be a legal correction scope without owning a pool --
  reddit is exactly that case, and a registry that could not say so would put
  reddit into `check_pools` and turn 27 corpora red for a pool nobody assembles.

THE HARD CONSTRAINT, and it outranks the feature. An instance with NO registry
must behave byte-identically to before this module existed. 27 instances load
this code and none of them asked for a registry. So `DEFAULT` below is today's
literals verbatim, `resolve()` returning None is the normal case, and every
`channels=None` default in validate.py lands here. `test_channel_registry.py`
pins that with the pre-change literals written out independently, so a future
edit to DEFAULT is caught by a test that does not import DEFAULT.

RESOLUTION SHAPE IS COPIED, NOT INVENTED. `resolve()` is the same two-source
shape as `resolve_channel_registry` in q-system/.q-system/scripts/voice-stop-gate.py,
which itself copied `resolve_reporter` beside it. Same relative paths, same
pointer-file semantics, same "return the named path even when it is missing" rule.
sp-52635fa3 tracks collapsing those copies into one importable home; this module
is that home for everything that can import the voice engine. The Stop-gate's
copy is deliberately NOT collapsed into it here: that hook is fail-closed on every
turn of 27 instances, this package's directory name is mid-rename across the
fleet, and an import that resolved to the old name would hold every turn on every
instance that has not synced yet. That collapse waits for the rename to land
and for the schema-conformance fixture sp-52635fa3 asks for.

FAIL-CLOSED, same posture as the rest of this package's validate half. A registry
that is PRESENT and untrustworthy raises rather than falling back to DEFAULT.
Falling back would silently grade a corpus against the wrong vocabulary, which is
the entire defect the registry exists to prevent.
"""
from __future__ import annotations

import json
import os

# Today's literals, lifted verbatim from validate.py before this module existed.
# These ARE the no-registry behavior. Changing them changes 27 instances.
DEFAULT_SCOPES = ("linkedin", "x", "substack", "medium", "dm", "email", "comment")
DEFAULT_ASSEMBLED = ("linkedin", "x")

# A role a channel can hold. Unknown roles fail closed rather than being ignored:
# a typo'd "assembeled" that silently dropped a channel out of the budget check
# would read exactly like a healthy corpus. Same rule as the Stop-gate's
# KNOWN_LINT_INPUTS, for the same reason.
KNOWN_ROLES = ("scope", "assembled")

# Both live under q-system/.q-system/data/, which the fleet sync treats as
# instance-owned, so a sync never overwrites or deletes them. A file placed next
# to this module instead would be replaced by the next sync.
REGISTRY_REL = os.path.join("q-system", ".q-system", "data", "voice-channels.json")
POINTER_REL = os.path.join("q-system", ".q-system", "data", "voice-channels.path")


class ChannelRegistryError(Exception):
    """A registry that is present and cannot be trusted. Callers must not fall back."""


class Channels:
    """The vocabulary, one object, two axes. `source` is the file it came from,
    or None for the built-in default -- so an error message can name the file an
    operator has to edit instead of saying "unknown scope" and stopping there."""

    __slots__ = ("scopes", "assembled", "source")

    def __init__(self, scopes, assembled, source=None):
        self.scopes = tuple(scopes)
        self.assembled = tuple(assembled)
        self.source = source

    def __repr__(self):                                     # pragma: no cover
        return (f"Channels(scopes={self.scopes!r}, assembled={self.assembled!r}, "
                f"source={self.source!r})")

    def __eq__(self, other):
        if not isinstance(other, Channels):
            return NotImplemented
        return (self.scopes == other.scopes
                and self.assembled == other.assembled
                and self.source == other.source)


DEFAULT = Channels(DEFAULT_SCOPES, DEFAULT_ASSEMBLED, None)


def resolve(instance_root):
    """This instance's registry path, or None. Two sources, in order:

    1. `q-system/.q-system/data/voice-channels.json` in the instance.
    2. A pointer file beside it naming the real location, because an instance that
       already owns a registry keeps it beside its own config, and there is no
       fleet-wide answer to which subtree that is. The pointer is one relative or
       absolute path; blank lines and `#` comments are ignored.

    Returns the NAMED path even when it does not exist, so `load` can say "the
    pointer names X, which is missing" instead of "no registry" -- the
    resolve_reporter scar, where a silent None read as "correctly absent".
    """
    if not instance_root:
        return None
    local = os.path.join(instance_root, REGISTRY_REL)
    if os.path.isfile(local):
        return local
    pointer = os.path.join(instance_root, POINTER_REL)
    try:
        with open(pointer, encoding="utf-8") as handle:
            named = handle.read()
    except OSError:
        return None
    named = "".join(ln for ln in named.splitlines()
                    if ln.strip() and not ln.lstrip().startswith("#")).strip()
    if not named:
        return None
    named = os.path.expanduser(named)
    if not os.path.isabs(named):
        named = os.path.join(instance_root, named)
    return os.path.realpath(named)


def load(registry_path):
    """`Channels` for this registry. None (no registry) -> DEFAULT, byte-identical
    to the pre-registry behavior.

    A registry with no `channel_vocabulary` key also returns DEFAULT. That is not
    laziness: the registries already in the field answer the SURFACE question
    only, and a registry gaining a new consumer must not change what it already
    answers to its existing ones.

    Raises ChannelRegistryError on a present-but-untrustworthy registry.
    """
    if registry_path is None:
        return DEFAULT
    try:
        with open(registry_path, encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise ChannelRegistryError(
            f"voice-channels registry named at {registry_path} is unreadable: "
            f"{exc}") from exc
    except ValueError as exc:
        raise ChannelRegistryError(
            f"voice-channels registry at {registry_path} is malformed: {exc}") from exc
    if not isinstance(data, dict):
        raise ChannelRegistryError(
            f"voice-channels registry at {registry_path} must be an object")
    vocab = data.get("channel_vocabulary")
    if vocab is None:
        return DEFAULT
    if not isinstance(vocab, dict):
        raise ChannelRegistryError(
            f"voice-channels registry at {registry_path}: channel_vocabulary must "
            f"be an object mapping channel name -> list of roles")

    scopes, assembled = [], []
    for name, roles in vocab.items():
        if not isinstance(name, str) or not name.strip():
            raise ChannelRegistryError(
                f"voice-channels registry at {registry_path}: a channel_vocabulary "
                f"key is empty")
        if not isinstance(roles, (list, tuple)):
            raise ChannelRegistryError(
                f"voice-channels registry at {registry_path}: roles for {name!r} "
                f"must be a list, got {type(roles).__name__}")
        for role in roles:
            if role not in KNOWN_ROLES:
                raise ChannelRegistryError(
                    f"voice-channels registry at {registry_path}: channel {name!r} "
                    f"declares unknown role {role!r}; known: {list(KNOWN_ROLES)}")
        if "scope" in roles:
            scopes.append(name)
        if "assembled" in roles:
            assembled.append(name)

    # An axis declared EMPTY is a check that can never fire, dressed as protection.
    # Empty scopes refuses every correction; empty assembled makes check_pools,
    # check_anchor_diversity, check_rotation_headroom and check_budget all iterate
    # nothing and report a clean corpus they never looked at. Both are worse than
    # no registry, so both are refused rather than accepted quietly.
    if not scopes:
        raise ChannelRegistryError(
            f"voice-channels registry at {registry_path}: no channel declares the "
            f"'scope' role, so every correction scope would be refused")
    if not assembled:
        raise ChannelRegistryError(
            f"voice-channels registry at {registry_path}: no channel declares the "
            f"'assembled' role, so the pool, anchor and budget checks would grade "
            f"nothing and report healthy")
    return Channels(scopes, assembled, registry_path)


def for_instance(instance_root):
    """`resolve` then `load`. The one call an instance seam needs."""
    return load(resolve(instance_root))


# How far up to look before giving up. Deep enough for the real fleet shape, an
# instance corpus dir sitting four levels under its root, and shallow enough that
# a runaway walk cannot reach a stranger's home directory.
_MAX_WALK = 12


def instance_root_for(start):
    """The directory at or above `start` that OWNS a channel registry, or None.

    Anchored on the registry's OWN two locations rather than on .git or any other
    landmark, because that is literally the question being asked: which directory
    above this one holds voice-channels.json or the pointer beside it. Answering
    it with a different landmark is how a seam ends up reading a tree that has no
    registry -- the public mirror and the skeleton disagree about where .git and
    tests/ live, and a walk keyed on those finds a different answer in each
    (the same trap test_validate_holds_no_channel_literal's VALIDATE_PY note
    records for module paths).

    None is a real answer and the common one: 26 instances own no registry and
    every caller must treat None as "use the built-in default", which is
    byte-identical to the behavior before this module existed.
    """
    current = os.path.abspath(start)
    for _ in range(_MAX_WALK):
        for rel in (REGISTRY_REL, POINTER_REL):
            if os.path.isfile(os.path.join(current, rel)):
                return current
        parent = os.path.dirname(current)
        if parent == current:               # filesystem root
            break
        current = parent
    return None


def for_path(start):
    """The Channels governing `start`, or the built-in default when nothing owns it.

    The whole seam in one call, so a caller cannot wire half of it. A registry
    that IS present and broken still raises: falling back to the default there
    would grade a corpus against a vocabulary its instance rejected, which is the
    wrong-vocabulary bug wearing a fix.
    """
    root = instance_root_for(start)
    return for_instance(root) if root else DEFAULT
