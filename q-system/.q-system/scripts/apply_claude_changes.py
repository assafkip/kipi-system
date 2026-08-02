#!/usr/bin/env python3
"""apply-claude-changes engine: land agent-authored edits inside .claude/ without
any human reading a diff, and without a path that can weaken enforcement.

WHY THIS SHAPE (measured 2026-08-01, do not "simplify" any of it away):

1. The founder will not review diffs. An earlier spec for this tool required him
   to read a diff and confirm. He rejected it, correctly: "that isn't sustainable
   for an autonomous system to send me a diff to review." A human reading code is
   not a safety mechanism, it is a bottleneck that fails open the first tired
   night. Every check here is mechanical. Output is ONE line.

2. The risk is NOT "an agent edits .claude/". It is "an agent WEAKENS its own
   enforcement". That is narrower and mechanically detectable, which is what makes
   an unattended apply possible at all.

3. The harness guard is a CLASSIFIER, not a path rule. Measured the same day, in
   the real repo: the Write TOOL on .claude/_probe_tool.md was REFUSED, while
   `touch .claude/_probe_bash.txt` from Bash SUCCEEDED. The prior belief, written
   into sp-19387a70, was that "both Bash and the Edit tool are refused" -- that is
   wrong on the Bash half. So this script MUST be safe when an AGENT runs it, not
   only when the founder does. There is no privileged caller. That is why there is
   no --force, no confirmation prompt, and no flag that unlocks a removal.

THE THREE LAYERS

  L1 op vocabulary  : insert_after, insert_before, append, create_file reach
                      anything under .claude/. `replace` reaches RULE TEXT ONLY
                      (.claude/rules/*.md) -- see rule_text_only. There is still
                      no delete: insert must be a non-empty string, so "replace
                      this paragraph with nothing" is refused, and "remove a hook
                      entry" is not expressible at all because the config surface
                      is out of replace's reach. Unknown ops and unknown proposal
                      keys are refused, so a proposal cannot smuggle in a flag
                      like disables_enforcement.
  L2 ratchet        : census the live enforcement points before and after. Every
                      pre-existing member must still be present and no category
                      may shrink. This catches the technically-additive edit that
                      removes something as a side effect -- e.g. inserting
                      " || true" after a hook command, which deletes nothing but
                      makes the old exact command string vanish from the census.
                      The census reads rule CONTENT at any depth under rules/,
                      not just the rules/ listing (_rule_marks): an (ENFORCED
                      marker may not lose an occurrence NOR leave the heading it
                      sits on, a pointer to a named enforcer may not vanish or be
                      rerouted, and a rule's count of substantive lines may not
                      shrink. Filenames alone were
                      blind to everything a replace does inside a file, which is
                      exactly why replace could not exist before that census; the
                      line floor is there because 5 of 34 rules carry no token at
                      all, so tokens alone left them free to be gutted.
  L3 verify+revert  : run the gate suite before and after. Any gate that goes
                      pass -> fail auto-restores the backup. The founder must
                      never be the one who notices a regression.

Everything runs against a COPY of .claude/ first. The live tree is touched only
after all of L1, L2 and the preconditions pass on that copy, so a refusal never
half-writes.

OUT OF REACH BY DESIGN (say so, do not pretend otherwise): removing a hook,
deleting a rule, narrowing a matcher, widening permissions.allow or defaultMode,
dropping an occurrence of a rule's (ENFORCED marker or moving it off the heading
it sits on, dropping or rerouting a rule's pointer to a named enforcer, changing
a rule's frontmatter (the keys that decide whether it loads at all) by ANY op
including the additive ones, and shortening a rule's body, cannot be done through
this path at all. Those need a different tool and a real conversation. See
REFUSED_SURFACES.

WHAT STILL GETS THROUGH (the honest residue, do not read the list above as
wider than it is): the census counts markers, the routes to executables, and
line COUNT -- never meaning. A replace that rewrites a rule into something vaguer
while keeping its (ENFORCED marker on the same heading, every script route and
its line count passes. Marker placement is checked at heading granularity only:
moving it between two headings of the same file is invisible here. That is the
deliberate trade: a ratchet that judged prose would refuse the honest
corrections this op exists to enable.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

SCHEMA_VERSION = 1

# L1: the op vocabulary. Additive ops reach anything under .claude/.
ADDITIVE_OPS = ("insert_after", "insert_before", "append", "create_file")
# The one non-additive op. ASK-289: additive-only meant a wrong sentence in a
# rule could be BURIED but never corrected -- design-auto-invoke.md still carries
# its narrowing paragraph wedged ABOVE its own H1 because insert_before was the
# only thing expressible. replace is pinned to rule text (rule_text_only) and
# watched by the rule-content census, so it cannot reach the config surface.
REPLACE_OPS = ("replace",)
ALL_OPS = ADDITIVE_OPS + REPLACE_OPS
ANCHOR_OPS = ("insert_after", "insert_before", "replace")

RULES_DIR = os.path.join(".claude", "rules")

# A rule's pointer to the thing that actually enforces it. Census member, so a
# replace cannot quietly cut a reader's route to the enforcer.
#
# The DIRECTORY PREFIX is part of the mark, not decoration. Matching the
# basename alone let a replace keep `existing-lint.py` while moving its route to
# `q-system/retired/hooks/existing-lint.py` -- the census saw the same member and
# the reader's route pointed at nothing (PR #70 round 4, minor). The route as the
# rule WRITES it is the census member, so moving it is a removal. The leading
# lookbehind stops the match from starting mid-token, which is what keeps a
# prefixed route from also registering as its own bare basename.
#
# The trailing boundary is load-bearing and is NOT a plain \b. Without it,
# rewriting `voice-lint.py` to `voice-lint.py.retired` left the mark
# `voice-lint.py` intact -- the pattern simply matched the prefix -- while the
# reader's route to the enforcer was dead (PR #70 round 3, minor). But a plain
# boundary over-corrects the other way: rules routinely end a sentence with
# "... is voice-lint.py.", and rejecting a following "." would quietly drop
# every one of those from the census. So the lookaheads reject exactly two
# things: more filename characters, and a dot that STARTS another extension.
_EXEC_REF = re.compile(r"(?<![A-Za-z0-9_./-])(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:py|sh)(?![A-Za-z0-9_-])(?!\.[A-Za-z0-9_])")

# A markdown heading line. Used only to ask WHERE an (ENFORCED marker sits; see
# _rule_marks for why the location and not just the presence has to be counted.
_HEADING = re.compile(r"[ ]{0,3}#{1,6}[ \t]")

# A rule's frontmatter decides whether the rule LOADS. Narrowing paths:/globs:
# leaves the body, the tokens and the line count all identical while switching
# the rule off, so no content census can see it (PR #70 round 3, major).
# NO op may move this block -- same standing as removing a hook: a different tool
# and a real conversation. Pinning it to `replace` alone was itself a hole:
# insert_before wedged a never-matching paths: block ABOVE the H1 of any rule
# that had no frontmatter yet, which deletes nothing and switches the rule off
# just the same (PR #70 round 4, major). "Additive" is a claim about the text,
# not about the effect.
_FRONTMATTER = re.compile(r"\A---\n.*?\n---(?:\n|\Z)", re.S)

ALLOWED_PROPOSAL_KEYS = {"schema_version", "slug", "reason", "requires", "edits"}
ALLOWED_EDIT_KEYS = {"file", "op", "anchor", "insert", "reason"}
ALLOWED_REQUIRES_KEYS = {"files_present", "template_pairs"}

# Permission surfaces this path may never move. Widening allow/defaultMode is
# enforcement-weakening even though it is textually additive.
REFUSED_SURFACES = (
    ("permissions", "allow"),
    ("permissions", "defaultMode"),
)

# The only path outside .claude/ this tool can write, and only in the same
# proposal as .claude/settings.json. See scoped_path for why it has to exist.
PAIRED_OUTSIDE = frozenset({"settings-template.json"})

# Refused anywhere, at any depth. These carry permissions.allow and hooks but are
# untracked machine-local overrides, so the permission and census checks that key
# off settings.json would silently inspect the wrong file. See scoped_path.
REFUSED_BASENAMES = frozenset({"settings.local.json"})


class Refusal(Exception):
    """A refusal is a normal outcome, not a crash. Carries the one-line reason."""


# Set the moment --root is parsed, so a refusal logs into the tree the run was
# aimed at. Without this the refusal handler fell back to the REAL repo root and
# a test run against a temp fixture would append to the live repo's apply.log --
# a test touching a live data path, which the fable-discipline lint exists to stop.
_ROOT = None


def acquire_lock(root):
    """Serialise the whole read-decide-write. Returns the held file object.

    Without this, two concurrent applies each read the same base content, each
    stage against it, and the second write silently discards the first
    proposal -- both reporting success. Last-writer-wins on a config file means
    a change that was reported as landed is simply gone.

    The critical section has to span the READ as well as the write: locking only
    the write still lets both stage from the same stale base.

    Non-blocking on purpose. A queued apply would sit behind an unattended run
    holding the lock; refusing is the fail-closed answer and the founder just
    re-runs. The lock is released when the process exits, so a crashed run does
    not wedge the tool (flock is bound to the fd, not to a file that must be
    cleaned up).
    """
    import fcntl
    lock_dir = os.path.join(root, "q-system", "output", "claude-changes")
    os.makedirs(lock_dir, exist_ok=True)
    handle = open(os.path.join(lock_dir, ".apply.lock"), "w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError):
        handle.close()
        raise Refusal("another apply is already running (lock held); nothing was read or written")
    return handle


def repo_root_from_script():
    # scripts/ -> .q-system/ -> q-system/ -> repo root
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


# ---------------------------------------------------------------- validation

def load_proposal(path):
    if not os.path.isfile(path):
        raise Refusal("proposal file not found: %s" % path)
    try:
        with open(path) as fh:
            prop = json.load(fh)
    except ValueError as exc:
        raise Refusal("proposal is not valid JSON: %s" % exc)
    if not isinstance(prop, dict):
        raise Refusal("proposal must be a JSON object")

    unknown = set(prop) - ALLOWED_PROPOSAL_KEYS
    if unknown:
        # Strict keys are what make "disables_enforcement: true" impossible to
        # smuggle in. An unknown key is refused loudly instead of ignored.
        raise Refusal("unknown proposal key(s): %s" % ", ".join(sorted(unknown)))

    if prop.get("schema_version") != SCHEMA_VERSION:
        raise Refusal("schema_version must be %d" % SCHEMA_VERSION)
    for field in ("slug", "reason"):
        if not isinstance(prop.get(field), str) or not prop[field].strip():
            raise Refusal("proposal.%s must be a non-empty string" % field)

    edits = prop.get("edits")
    if not isinstance(edits, list) or not edits:
        raise Refusal("proposal.edits must be a non-empty list")

    req = prop.get("requires", {})
    if not isinstance(req, dict):
        raise Refusal("proposal.requires must be an object")
    unknown_req = set(req) - ALLOWED_REQUIRES_KEYS
    if unknown_req:
        raise Refusal("unknown requires key(s): %s" % ", ".join(sorted(unknown_req)))

    for idx, edit in enumerate(edits):
        if not isinstance(edit, dict):
            raise Refusal("edit %d is not an object" % idx)
        unknown_e = set(edit) - ALLOWED_EDIT_KEYS
        if unknown_e:
            raise Refusal("edit %d has unknown key(s): %s" % (idx, ", ".join(sorted(unknown_e))))
        op = edit.get("op")
        if op not in ALL_OPS:
            raise Refusal(
                "edit %d op %r is not a permitted op (allowed: %s)" % (idx, op, ", ".join(ALL_OPS))
            )
        # insert must be non-empty AND non-blank for every op including replace.
        # That is what keeps "delete this paragraph" inexpressible now that a
        # non-additive op exists: a replace with an empty (or whitespace-only)
        # insert IS a delete, and it is refused here rather than downstream.
        for field in ("file", "insert", "reason"):
            if not isinstance(edit.get(field), str) or not edit[field].strip():
                raise Refusal("edit %d.%s must be a non-empty string" % (idx, field))
        # THE boundary. After this line the proposal holds exactly one spelling
        # of each path and no other reader normalizes anything.
        edit["file"] = canonical_rel(edit["file"])
        if op in ANCHOR_OPS:
            if not isinstance(edit.get("anchor"), str) or not edit["anchor"].strip():
                raise Refusal("edit %d needs a non-empty anchor for op %s" % (idx, op))
        elif "anchor" in edit:
            raise Refusal("edit %d op %s takes no anchor" % (idx, op))
    return prop


def canonical_rel(rel):
    """THE one place a proposal path is normalized. Boundary, called from
    load_proposal; every later reader consumes the stored canonical value.

    Round-2 review found the bypass this exists to kill: permission_surface_check
    was gated on a RAW staged key while touches_settings used normpath, so
    ".claude/./settings.json" wrote the real file while the permission check
    never fired. Two readers of one input with different semantics is a defect
    even when each is individually defensible.

    The fix is NOT another normalization call beside the first -- that would be a
    third reader and a fourth spelling. The proposal's own edit["file"] is
    rewritten to this value at load, so there is only one spelling in the data
    structure afterwards and nothing downstream has anything else to read.

    Covered here: "." segments, ".." segments, duplicate slashes, trailing
    slash (all collapsed by normpath). Case variants and symlinked parents are
    NOT covered by string normalization and are handled separately by inode
    identity in resolve_special_keys -- normpath cannot see either.
    """
    if not isinstance(rel, str) or not rel.strip():
        raise Refusal("edit.file must be a non-empty string")
    if os.path.isabs(rel):
        raise Refusal("edit path must be relative, got %s" % rel)
    norm = os.path.normpath(rel)
    if norm.startswith("..") or os.path.isabs(norm):
        raise Refusal("edit path escapes the repo: %s" % rel)
    return norm


def _same_file(root, rel, target):
    """Inode identity, not string equality.

    Catches the spellings normpath cannot: a case variant on a case-insensitive
    filesystem (.claude/Settings.json is the SAME file on macOS), and a symlinked
    parent directory. Both would otherwise be a second name for a guarded file
    that only some guards recognise -- the round-1 settings.local.json class and
    the round-2 "./" class over again.
    """
    p = os.path.join(root, rel)
    try:
        return os.path.exists(p) and os.path.exists(target) and os.path.samefile(p, target)
    except OSError:
        return False


def refuse_duplicate_spellings(root, prop):
    """One name per file in the proposal, or no run.

    canonical_rel collapses the spellings a STRING can collapse ("./", "..",
    doubled slashes). It cannot see the two normpath is blind to: a case variant
    on a case-insensitive filesystem, and a symlinked parent directory. Those
    arrive as two distinct keys naming one inode, and two keys means two readers:
    each is read from disk independently, each is written back to the same inode
    in sorted() order, so the LAST spelling's content lands while an earlier
    spelling is what a single-key guard inspected.

    PR #70 round 5 found the live consequence. `.claude/Settings.json` became
    settings_key (resolve_special_keys picks the FIRST match), so
    permission_surface_check read that copy while `.claude/settings.json` sorted
    last and its content is what hit disk. A proposal widening permissions.allow
    exited `0 OK applied` with the ratchet and the gates reporting clean, and it
    reported "2 edit(s)" for one edit's worth of surviving content.

    The fix belongs HERE and not in another guard, because the defect is not that
    some particular guard read the wrong key -- it is that two keys existed at
    all. Every guard downstream is correct once the input holds one name per file.

    HONEST BOUNDARY: identity comes from st_dev/st_ino for a file that exists,
    and from realpath for one that does not. So two case-variant spellings of a
    path that exists under NEITHER case (two create_file edits racing to make one
    new file) are not caught. That is a reporting defect, not an enforcement one:
    nothing pre-existing can be weakened by it, and every guarded file this
    engine knows about already exists.
    """
    seen = {}
    for edit in prop["edits"]:
        rel = edit["file"]
        full = os.path.join(root, rel)
        try:
            st = os.stat(full)
            identity = ("inode", st.st_dev, st.st_ino)
        except OSError:
            identity = ("path", os.path.realpath(full))
        first = seen.setdefault(identity, rel)
        if first != rel:
            raise Refusal(
                "edits name one file under two spellings (%s and %s resolve to the "
                "same file); use one spelling per file" % (first, rel)
            )


def resolve_special_keys(root, prop):
    """Resolve, ONCE, which canonical edit keys are the guarded files.

    Returns (settings_key, template_key): the actual keys used in `staged`, or
    None. Every downstream check consumes these instead of comparing strings, so
    a new spelling cannot make one guard match and another miss.
    """
    settings_target = os.path.join(root, ".claude", "settings.json")
    template_target = os.path.join(root, "settings-template.json")
    settings_key = template_key = None
    for edit in prop["edits"]:
        rel = edit["file"]
        if settings_key is None and _same_file(root, rel, settings_target):
            settings_key = rel
        if template_key is None and _same_file(root, rel, template_target):
            template_key = rel
    return settings_key, template_key


def is_rule_text(rel):
    """The SHAPE half of "is this rule text", in one place.

    Two callers ask it -- the `replace` scope pin and the frontmatter pin -- and
    two spellings of one question is the drift class round 2 found in the path
    normalization and round 3 found again between the token census and the
    frontmatter nobody was reading.

    Depth-permissive on purpose, and that is now safe: _rule_marks walks the
    whole rules/ tree, so a rule in a subdirectory is inside the content census
    and inside these pins together. It used to be inside replace's reach and
    outside the census at the same time (PR #70 round 4, minor).
    """
    return rel.startswith(RULES_DIR + os.sep) and rel.endswith(".md")


def rule_text_only(root, rel, settings_key, template_key):
    """`replace` is the only non-additive op, so its reach is pinned to rule TEXT.

    Three checks, because each alone has a hole the other two cover:

      identity : rel IS .claude/settings.json or settings-template.json under
                 some spelling. resolve_special_keys matches by inode, not by
                 string, so a case variant or a ./ spelling of a guarded file is
                 recognised here. It does NOT merge two keys into one -- that is
                 refuse_duplicate_spellings' job, upstream, and round 5 found the
                 hole left when this docstring claimed otherwise.
      shape    : anything that is not .claude/rules/<name>.md is out. agents/ and
                 output-styles/ keep the additive-only guarantee they had before
                 this op existed; widening to them is a separate decision with a
                 separate blast radius, not a side effect of ASK-289.
      realpath : a symlink parked at .claude/rules/x.md pointing somewhere else.
                 scoped_path permits that today -- it only asks that the target
                 stay under .claude/ -- so a string-shape check alone waves it
                 through. Same class as settings.local.json (round 1) and the
                 "./" spelling (round 2): a second name only some guards see.
    """
    if rel == settings_key or rel == template_key:
        raise Refusal("replace may not target %s (rule text only)" % rel)
    if not is_rule_text(rel):
        raise Refusal("replace is only permitted on %s%s*.md, got %s" % (RULES_DIR, os.sep, rel))
    rules_dir = os.path.realpath(os.path.join(root, RULES_DIR))
    real = os.path.realpath(os.path.join(root, rel))
    if not real.startswith(rules_dir + os.sep):
        raise Refusal("replace target resolves outside %s%s: %s" % (RULES_DIR, os.sep, rel))


def scoped_path(root, rel, paired_ok=False):
    """Resolve rel under root/.claude, refusing anything that escapes it.

    Checks the REAL path, so a symlink planted inside .claude/ that points at
    ~/.ssh or at the repo's own hooks cannot be used as an exit.

    ONE file outside .claude/ is reachable, and only in lockstep: repo-root
    settings-template.json. kipi update rebuilds every instance's settings.json
    from the template alone, and settings-template-sync-check fails in BOTH
    directions -- a hook in only one of the two files is a red gate either way.
    So the pair cannot be landed in two steps by two actors; it has to move in
    one transaction or the repo is broken in between. It is permitted only when
    the same proposal also edits .claude/settings.json (see PAIRED_OUTSIDE use in
    main). Nothing else outside .claude/ is reachable by any path or flag.
    """
    if os.path.isabs(rel):
        raise Refusal("edit path must be relative, got %s" % rel)
    norm = os.path.normpath(rel)
    if norm.startswith("..") or os.path.isabs(norm):
        raise Refusal("edit path escapes the repo: %s" % rel)
    if norm in PAIRED_OUTSIDE:
        if not paired_ok:
            raise Refusal("%s may only be edited together with .claude/settings.json" % norm)
        return os.path.join(root, norm)
    if not (norm == ".claude" or norm.startswith(".claude" + os.sep)):
        raise Refusal("edit path is outside .claude/: %s" % rel)

    # settings.local.json is REFUSED, not merely unchecked.
    #
    # It is the whole tool undone by one filename. permission_surface_check and
    # the hook census both key off ".claude/settings.json"; the local override
    # carries its own permissions.allow and hooks, so a proposal aimed here would
    # widen permissions while the ratchet, the additive-only vocabulary and the
    # census all inspected a file the proposal never touched, and reported clean.
    # sp-f434981b already noted this file is excluded from the tripwire as too
    # noisy while still carrying permissions.allow; this is the same file biting
    # from the other side.
    #
    # Refused rather than checked: it is untracked and machine-local, so a change
    # here leaves no reviewable trace, and a tool whose purpose is AUDITABLE
    # config changes has no business writing it.
    # Lowercased: on a case-insensitive filesystem .claude/Settings.Local.json is
    # the SAME file, and an exact-case check would wave it through. On a
    # case-sensitive filesystem that name is a different file that does not
    # exist, so refusing it costs nothing and fails closed either way.
    if os.path.basename(norm).lower() in REFUSED_BASENAMES:
        raise Refusal("%s may not be edited through this path (untracked local override)"
                      % os.path.basename(norm))

    claude_dir = os.path.realpath(os.path.join(root, ".claude"))
    full = os.path.join(root, norm)
    probe = full
    while not os.path.exists(probe) and os.path.dirname(probe) != probe:
        probe = os.path.dirname(probe)
    real_existing = os.path.realpath(probe)
    if not (real_existing == claude_dir or real_existing.startswith(claude_dir + os.sep)):
        raise Refusal("edit path resolves outside .claude/: %s" % rel)
    return full


# ------------------------------------------------------------------- editing

def _unique_anchor_hits(content, anchor, rel):
    """Anchor arithmetic, shared by every anchored op.

    One copy on purpose: when `replace` arrived it grew a second ambiguity check
    beside this one, and the mutation case that proves the check is load-bearing
    then matched two lines and aborted the suite. Two copies of a guard is also
    two chances for them to drift apart -- the same two-readers defect round 2
    found in the path normalization.
    """
    hits = content.count(anchor)
    if hits > 1:
        raise Refusal("anchor matches %d times (must be exactly 1) in %s: %r" % (hits, rel, _snip(anchor)))
    return hits


def _guard_frontmatter(rel, before, after):
    """A rule's frontmatter block may not move, whatever op moved it.

    Compared before/after rather than "is the anchor inside the block": that
    also catches an insert that ADDS or CLOSES a --- fence, which moves the
    frontmatter boundary without the anchor ever sitting in it. Equality is
    transitive, so checking each edit holds across a whole proposal.

    Called for EVERY op with prior content, not just `replace`. The round-3 fix
    lived inside the replace branch, which left insert_before free to wedge a
    never-matching paths: block above the H1 of a rule that had no frontmatter
    yet -- additive text, dead rule, rc=0 (PR #70 round 4, major).
    """
    if not is_rule_text(rel):
        return
    if _frontmatter(after) != _frontmatter(before):
        raise Refusal(
            "edit may not change the frontmatter of %s; the scoping keys "
            "decide whether the rule loads at all" % rel)


def apply_edit(content, edit, rel):
    """Return (new_content, already_satisfied). Pure; never touches disk.

    Every op that has prior content leaves through the single _guard_frontmatter
    call at the bottom. One exit on purpose: a per-branch guard is what round 4
    found missing on three of the four branches.
    """
    op = edit["op"]
    ins = edit["insert"]

    if op == "create_file":
        # No prior content, so there is no frontmatter to preserve. A brand-new
        # rule declaring its own scope is an addition, not a narrowing.
        if content is None:
            return ins, False
        if content == ins:
            return content, True
        raise Refusal("create_file target already exists with different content: %s" % rel)

    if op == "append":
        if content.endswith(ins):
            return content, True
        new = content + ins

    elif op == "replace":
        anchor = edit["anchor"]
        # An anchor that survives into its own replacement never converges: the
        # next run finds it again, inserts again, and the file grows forever
        # while "already applied" stays undetectable. Refused, not tolerated --
        # extending text is what the additive ops are for.
        if anchor in ins:
            raise Refusal(
                "replace anchor is contained in the insert, so it never converges in %s; "
                "use insert_after/insert_before to extend text" % rel)
        if _unique_anchor_hits(content, anchor, rel) == 0:
            # Anchor gone AND the replacement sitting there exactly once is the
            # signature of a completed earlier run, not of a bad proposal. Same
            # already-satisfied contract the insert ops report.
            if content.count(ins) == 1:
                return content, True
            raise Refusal("anchor not found in %s: %r" % (rel, _snip(anchor)))
        new = content.replace(anchor, ins, 1)

    else:
        anchor = edit["anchor"]
        if _unique_anchor_hits(content, anchor, rel) == 0:
            raise Refusal("anchor not found in %s: %r" % (rel, _snip(anchor)))
        pos = content.index(anchor)
        if op == "insert_after":
            cut = pos + len(anchor)
            if content[cut:cut + len(ins)] == ins:
                return content, True
            new = content[:cut] + ins + content[cut:]
        else:  # insert_before
            if content[max(0, pos - len(ins)):pos] == ins:
                return content, True
            new = content[:pos] + ins + content[pos:]

    _guard_frontmatter(rel, content, new)
    return new, False


def _snip(text, n=60):
    flat = " ".join(text.split())
    return flat if len(flat) <= n else flat[:n] + "..."


# ------------------------------------------------------------------- census

def _hook_entries(settings):
    out = set()
    for event, groups in (settings.get("hooks") or {}).items():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            matcher = group.get("matcher", "")
            for hook in group.get("hooks") or []:
                if isinstance(hook, dict) and "command" in hook:
                    # The exact command string is the census member. Inserting
                    # " || true" after it makes the OLD string vanish, which the
                    # ratchet reports as a removal. That is the point.
                    out.add("%s|%s|%s" % (event, matcher, hook["command"]))
    return out


def _dir_names(path):
    if not os.path.isdir(path):
        return set()
    return {n for n in os.listdir(path) if not n.startswith(".")}


def _frontmatter(text):
    """The leading --- block, or "" when the file has none. See _FRONTMATTER."""
    match = _FRONTMATTER.match(text or "")
    return match.group(0) if match else ""


def _rule_marks(rules_dir):
    """Read every rule ONCE and return (token_marks, line_marks).

    One walk and one read per file on purpose. Two functions each opening the
    same rules is two readers free to drift -- the defect class round 2 found in
    the path normalization and round 3 found again between the token census and
    the frontmatter it never looked at.

    The rules census used to be _dir_names -- a directory listing, which is
    blind to everything that happens inside a file. That was fine while every op
    was additive. It is not fine now that `replace` exists: a replace keeps the
    filename and can gut what the file says, and the listing would report clean.

    Two token classes are countable without judgement, which is the bar for a
    ratchet member:

      enforced : the file claims (ENFORCED anywhere. Demoting a rule to advisory
                 is enforcement-weakening whether or not the prose is honest. If
                 the claim is genuinely false, the fix is to correct the SCOPE
                 (which replace now allows) or to take the marker off through a
                 different tool and a real conversation -- same standing as
                 removing a hook.
      exec     : a named .py/.sh the rule routes a reader to. A rule whose
                 pointer to its enforcer vanishes is a rule nobody can act on.

    Deliberately NOT counted: prose meaning and tone. A ratchet that tried to
    judge those would refuse the honest corrections this op exists to enable.

    LINE MARKS are the second half, and they exist because tokens alone are not
    enough: 5 of this repo's 34 rules carry NEITHER token class (security.md has
    no (ENFORCED marker and names no script), so a replace swapped the whole
    475-char body of one for a single sentence while the token census reported
    rule_marks 113 -> 113 and the tool exited OK applied. Measured 2026-08-02,
    PR #70 round 3 major.

    A count only becomes visible to ratchet_check's set-difference when it is
    encoded as a SET, hence one mark per substantive line INDEX. Dropping a line
    drops the highest index, which is exactly the refusal wanted.

    Lines, not words or characters: rewording a line has to stay free, because
    that IS the correction this op exists for, while deleting lines must not. So
    a replace may reword a rule and may grow it; it may never shorten it. The
    residue is named in the module docstring rather than papered over: a rewrite
    that keeps the shape and hollows out the meaning still passes.
    """
    token_marks = set()
    line_marks = set()
    if not os.path.isdir(rules_dir):
        return token_marks, line_marks
    # os.walk, not os.listdir. rule_text_only permits a rule at any depth under
    # rules/, so a one-level census left a subdirectory rule inside replace's
    # reach and outside every content check at once (PR #70 round 4, minor). The
    # mark key is the path relative to rules/, which is identical to the old
    # filename for every top-level rule, so nothing that was censused stops being.
    for dirpath, dirnames, filenames in os.walk(rules_dir):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for filename in sorted(filenames):
            if filename.startswith(".") or not filename.endswith(".md"):
                continue
            full = os.path.join(dirpath, filename)
            name = os.path.relpath(full, rules_dir)
            try:
                with open(full) as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            for ref in set(_EXEC_REF.findall(text)):
                token_marks.add("%s|exec|%s" % (name, ref))
            # (ENFORCED is counted twice, and the second count is the one that
            # closes the hole. A whole-file presence boolean let a replace lift
            # the marker off the heading that DECLARES the rule enforced and park
            # the token in a sentence saying the rule is advisory -- the token was
            # still in the file, so the census reported clean (PR #70 round 4).
            #   occurrences      : total, so losing one anywhere is visible.
            #   enforced-heading : how many HEADING lines carry it, so moving it
            #                      out of a heading and into prose drops a mark.
            # Counts encoded as sets, never positions: rewording a heading and
            # adding a section above it both have to stay free, and only a count
            # survives both. Same encode-a-count-as-a-set trick as line marks,
            # for the same reason -- ratchet_check compares sets.
            for index in range(text.count("(ENFORCED")):
                token_marks.add("%s|enforced|%d" % (name, index))
            lines = text.splitlines()
            headings = sum(1 for line in lines
                           if _HEADING.match(line) and "(ENFORCED" in line)
            for index in range(headings):
                token_marks.add("%s|enforced-heading|%d" % (name, index))
            substantive = sum(1 for line in lines if line.strip())
            for index in range(substantive):
                line_marks.add("%s|line|%d" % (name, index))
    return token_marks, line_marks


def census(root):
    """Count the live enforcement points. Enforcement may only grow."""
    c = {}
    settings_path = os.path.join(root, ".claude", "settings.json")
    settings = {}
    if os.path.isfile(settings_path):
        try:
            with open(settings_path) as fh:
                settings = json.load(fh)
        except ValueError:
            settings = {}
    c["hooks"] = _hook_entries(settings)
    perms = settings.get("permissions") or {}
    c["deny"] = set(perms.get("deny") or [])
    c["rules"] = _dir_names(os.path.join(root, ".claude", "rules"))
    c["rule_marks"], c["rule_lines"] = _rule_marks(os.path.join(root, ".claude", "rules"))
    c["agents"] = _dir_names(os.path.join(root, ".claude", "agents"))
    c["output_styles"] = _dir_names(os.path.join(root, ".claude", "output-styles"))

    manifest = os.path.join(root, "q-system", ".q-system", "capability-manifest.json")
    tests = set()
    if os.path.isfile(manifest):
        try:
            with open(manifest) as fh:
                data = json.load(fh)
            for entry in data.get("expected_tests") or []:
                if isinstance(entry, dict) and "path" in entry:
                    tests.add(entry["path"])
        except ValueError:
            pass
    c["manifest_tests"] = tests
    return c


def ratchet_check(before, after):
    for key in sorted(before):
        gone = before[key] - after.get(key, set())
        if gone:
            raise Refusal(
                "enforcement ratchet: %d %s entr(ies) would disappear, first: %s"
                % (len(gone), key, _snip(sorted(gone)[0]))
            )
        if len(after.get(key, set())) < len(before[key]):
            raise Refusal(
                "enforcement ratchet: %s count would drop %d -> %d"
                % (key, len(before[key]), len(after.get(key, set())))
            )


def permission_surface_check(root, staged_settings_text):
    """permissions.allow / defaultMode may not move; deny may only grow."""
    live_path = os.path.join(root, ".claude", "settings.json")
    if not os.path.isfile(live_path):
        return
    with open(live_path) as fh:
        live = json.load(fh)
    try:
        staged = json.loads(staged_settings_text)
    except ValueError as exc:
        raise Refusal("settings.json would no longer be valid JSON: %s" % exc)

    for section, key in REFUSED_SURFACES:
        a = (live.get(section) or {}).get(key)
        b = (staged.get(section) or {}).get(key)
        if a != b:
            raise Refusal("%s.%s may not be changed through this path" % (section, key))

    live_deny = set((live.get("permissions") or {}).get("deny") or [])
    staged_deny = set((staged.get("permissions") or {}).get("deny") or [])
    missing = live_deny - staged_deny
    if missing:
        raise Refusal("permissions.deny would lose: %s" % _snip(sorted(missing)[0]))


# -------------------------------------------------------------------- gates

def _hook_script_paths(settings):
    """Every $CLAUDE_PROJECT_DIR-relative script a hook command references."""
    found = set()
    pat = re.compile(r'\$CLAUDE_PROJECT_DIR/([A-Za-z0-9_./-]+\.(?:py|sh))')
    for entry in _hook_entries(settings):
        command = entry.split("|", 2)[2]
        # A `test -f X && ...` guard makes a missing script a deliberate no-op,
        # so those are not a broken-wiring finding.
        if "test -f" in command:
            continue
        for m in pat.finditer(command):
            found.add(m.group(1))
    return found


def gate_settings_parses(root):
    p = os.path.join(root, ".claude", "settings.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p) as fh:
            json.load(fh)
        return True
    except ValueError:
        return False


def gate_hook_scripts_exist(root):
    p = os.path.join(root, ".claude", "settings.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p) as fh:
            settings = json.load(fh)
    except ValueError:
        return False
    for rel in _hook_script_paths(settings):
        if not os.path.exists(os.path.join(root, rel)):
            return False
    return True


def _external_gate(root, rel, args):
    script = os.path.join(root, rel)
    if not os.path.isfile(script):
        return None
    env = dict(os.environ)
    env["KIPI_NOTIFY"] = "/usr/bin/true"
    try:
        proc = subprocess.run(
            [sys.executable, script] + args,
            cwd=root, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    except OSError:
        return None
    return proc.returncode == 0


def gate_template_parses(root):
    """settings-template.json must still parse.

    This gate was missing on the first real run and the tool happily reported
    "gates held" after writing a template that no longer parsed -- the anchor had
    ended on an opening brace. Every file this tool can write needs a validity
    gate, not just the ones under .claude/.
    """
    p = os.path.join(root, "settings-template.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p) as fh:
            json.load(fh)
        return True
    except ValueError:
        return False


GATES = (
    ("settings-json-parses", gate_settings_parses),
    ("settings-template-parses", gate_template_parses),
    ("hook-scripts-exist", gate_hook_scripts_exist),
    ("settings-template-sync",
     lambda root: _external_gate(root, "q-system/.q-system/scripts/settings-template-sync-check.py", ["--check"])),
    ("validate-separation",
     lambda root: _external_gate(root, "validate-separation.py", [])),
)


def run_gates(root):
    """None means not-applicable in this tree; it never counts as a regression."""
    return {name: fn(root) for name, fn in GATES}


def gate_regression(before, after):
    for name in before:
        if before.get(name) is True and after.get(name) is not True:
            return name
    return None


# -------------------------------------------------------- preconditions

def check_requires(root, prop, log):
    req = prop.get("requires") or {}
    for rel in req.get("files_present") or []:
        if not os.path.exists(os.path.join(root, rel)):
            raise Refusal("required file missing: %s" % rel)
        log.append("require ok: %s present" % rel)

def check_template_pairs(root, prop, staged, template_key, log):
    """settings.json and settings-template.json are both-or-neither.

    kipi update rebuilds every instance's settings.json from the TEMPLATE only,
    so a hook wired in one and not the other runs dead somewhere, and
    settings-template-sync-check fails in BOTH directions.

    Checked against the STAGED template, not the on-disk one: the proposal that
    arms a hook is usually the same proposal that adds it to the template, so an
    on-disk-only check refused the very shape this exists to support. Caught by
    running the first real proposal against a copy of the live tree.
    """
    req = prop.get("requires") or {}
    commands = req.get("template_pairs") or []
    if not commands:
        return
    if template_key is not None:
        content = staged[template_key]
        origin = "this proposal"
    else:
        tpl = os.path.join(root, "settings-template.json")
        if not os.path.isfile(tpl):
            raise Refusal("settings-template.json missing; cannot verify the pair")
        with open(tpl) as fh:
            content = fh.read()
        origin = "the existing template"
    for command in commands:
        if command not in content:
            raise Refusal("settings-template.json does not carry: %s" % _snip(command))
        log.append("pair ok: %s carries %s" % (origin, _snip(command)))


# ----------------------------------------------------------------- the run

def main(argv):
    global _ROOT
    root = None
    proposal_path = None
    rest = list(argv)
    while rest:
        arg = rest.pop(0)
        if arg == "--root":
            if not rest:
                raise Refusal("--root needs a value")
            root = rest.pop(0)
            # Assigned HERE, not after the loop. A later arg-parse refusal
            # (e.g. --force) used to fall back to repo_root_from_script() and
            # append apply.log to the LIVE repo even when --root aimed the run
            # at a temp tree. A refusal path must never write to a tree the run
            # was not pointed at.
            _ROOT = os.path.abspath(root)
        elif arg.startswith("--"):
            # No --force exists. An unknown flag is refused, never ignored.
            raise Refusal("unknown option %s" % arg)
        elif proposal_path is None:
            proposal_path = arg
        else:
            raise Refusal("unexpected argument %s" % arg)

    if proposal_path is None:
        raise Refusal("usage: apply-claude-changes.sh <proposal.json> [--root DIR]")
    root = os.path.abspath(root or repo_root_from_script())
    _ROOT = root
    if not os.path.isdir(os.path.join(root, ".claude")):
        raise Refusal("no .claude/ directory under %s" % root)

    # Held for the rest of the process. Acquired BEFORE the proposal is read so
    # the base content every decision rests on cannot move under us.
    lock = acquire_lock(root)
    assert lock is not None  # keep a reference; releasing early reopens the race

    log = []
    prop = load_proposal(proposal_path)
    slug = prop["slug"]
    log.append("proposal %s: %s" % (slug, prop["reason"]))
    log.append("root: %s" % root)

    check_requires(root, prop, log)

    # ---- stage every edit against an in-memory COPY. Nothing on disk yet.
    # One name per file FIRST: every check below assumes a key it resolves is the
    # key whose content lands, and that is only true when no second spelling of
    # the same file is still in the proposal (round 5).
    refuse_duplicate_spellings(root, prop)
    # Resolved ONCE by inode; every check below reads these, never a string.
    settings_key, template_key = resolve_special_keys(root, prop)
    touches_settings = settings_key is not None
    touches_template = template_key is not None
    # Both-or-neither, enforced in both directions so the repo is never left in
    # the state sync-check calls red.
    if touches_template and not touches_settings:
        raise Refusal("settings-template.json edited without .claude/settings.json")
    if touches_settings and not touches_template and not (prop.get("requires") or {}).get("template_pairs"):
        raise Refusal(".claude/settings.json edited without the settings-template.json pair")

    staged = {}
    satisfied = []
    for idx, edit in enumerate(prop["edits"]):
        rel = edit["file"]
        full = scoped_path(root, rel, paired_ok=touches_settings)
        if edit["op"] in REPLACE_OPS:
            rule_text_only(root, rel, settings_key, template_key)
        if rel in staged:
            current = staged[rel]
        elif os.path.isfile(full):
            with open(full) as fh:
                current = fh.read()
        elif edit["op"] == "create_file":
            current = None
        else:
            raise Refusal("target file does not exist: %s" % rel)
        new, already = apply_edit(current, edit, rel)
        staged[rel] = new
        satisfied.append(already)
        log.append("edit %d %s %s: %s (%s)" % (
            idx, edit["op"], rel, "already-applied" if already else "staged", edit["reason"]))

    check_template_pairs(root, prop, staged, template_key, log)

    # ---- idempotency. All satisfied = nothing to do. Mixed = a half-applied
    # tree from some earlier run; refuse rather than guess which half is right.
    if all(satisfied):
        return emit("OK already-applied %s: no changes needed" % slug, log, root, 0)
    if any(satisfied):
        raise Refusal("proposal is partially applied (%d of %d edits already present); refusing"
                      % (sum(satisfied), len(satisfied)))

    # ---- L2 ratchet, computed against a real copy tree on disk.
    tmp = tempfile.mkdtemp(prefix="claude-changes-")
    try:
        copy_root = os.path.join(tmp, "root")
        os.makedirs(copy_root)
        shutil.copytree(os.path.join(root, ".claude"), os.path.join(copy_root, ".claude"), symlinks=True)
        manifest_rel = os.path.join("q-system", ".q-system", "capability-manifest.json")
        src_manifest = os.path.join(root, manifest_rel)
        if os.path.isfile(src_manifest):
            os.makedirs(os.path.dirname(os.path.join(copy_root, manifest_rel)), exist_ok=True)
            shutil.copy2(src_manifest, os.path.join(copy_root, manifest_rel))
        for rel, content in staged.items():
            dest = os.path.join(copy_root, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w") as fh:
                fh.write(content)

        before_census = census(root)
        after_census = census(copy_root)
        ratchet_check(before_census, after_census)
        log.append("ratchet ok: hooks %d->%d, rules %d->%d, rule-marks %d->%d, deny %d->%d" % (
            len(before_census["hooks"]), len(after_census["hooks"]),
            len(before_census["rules"]), len(after_census["rules"]),
            len(before_census["rule_marks"]), len(after_census["rule_marks"]),
            len(before_census["deny"]), len(after_census["deny"])))

        if settings_key is not None:
            permission_surface_check(root, staged[settings_key])
            log.append("permission surfaces unchanged")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- gates BEFORE. A gate already failing is not a regression; only
    # pass -> fail is. gates run is RED today (384 open spillover items), so a
    # "must be green" rule would make this tool permanently unusable.
    gates_before = run_gates(root)
    log.append("gates before: %s" % _fmt_gates(gates_before))

    # ---- backup, then write.
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_dir = os.path.join(root, "q-system", "output", "claude-changes", ".backups",
                              "%s-%s" % (slug, stamp))
    os.makedirs(backup_dir, exist_ok=True)
    written = []
    for rel in sorted(staged):
        full = os.path.join(root, rel)
        if os.path.isfile(full):
            dest = os.path.join(backup_dir, rel.replace(os.sep, "__"))
            shutil.copy2(full, dest)
        else:
            with open(os.path.join(backup_dir, rel.replace(os.sep, "__") + ".ABSENT"), "w") as fh:
                fh.write("")
    log.append("backup: %s" % backup_dir)

    # A write failure on the SECOND file used to escape uncaught and leave a
    # PARTIALLY APPLIED config -- worse than a refusal, because everything
    # downstream believes the change landed. Two defences:
    #   per-file: write a sibling temp then os.replace, so a single file is never
    #             observed half-written (replace is atomic within a filesystem).
    #   per-run:  ANY exception restores every target that has a backup, not just
    #             the ones already written, since the in-flight file may be torn.
    try:
        for rel in sorted(staged):
            full = os.path.join(root, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            tmp_path = full + ".claude-changes.tmp"
            with open(tmp_path, "w") as fh:
                fh.write(staged[rel])
            os.replace(tmp_path, full)
            written.append(rel)
    except (OSError, IOError) as exc:
        for rel in sorted(staged):
            leftover = os.path.join(root, rel) + ".claude-changes.tmp"
            if os.path.isfile(leftover):
                os.remove(leftover)
        restore(root, backup_dir, sorted(staged))
        log.append("write failed after %d of %d file(s): %s" % (len(written), len(staged), exc))
        log.append("AUTO-REVERTED from %s" % backup_dir)
        return emit("REVERTED %s: write failed on %s, %d file(s) restored, no partial apply"
                    % (slug, _snip(str(exc)), len(staged)), log, root, 3)
    log.append("wrote: %s" % ", ".join(written))

    # ---- L3 gates AFTER, auto-revert on any regression.
    gates_after = run_gates(root)
    log.append("gates after: %s" % _fmt_gates(gates_after))
    bad = gate_regression(gates_before, gates_after)
    if bad:
        restore(root, backup_dir, written)
        log.append("AUTO-REVERTED from %s" % backup_dir)
        return emit("REVERTED %s: gate %r regressed pass->fail, %d file(s) restored"
                    % (slug, bad, len(written)), log, root, 3)

    return emit("OK applied %s: %d edit(s), %d file(s), hooks %d->%d, gates held"
                % (slug, len(prop["edits"]), len(written),
                   len(before_census["hooks"]), len(after_census["hooks"])),
                log, root, 0)


def restore(root, backup_dir, written):
    for rel in written:
        src = os.path.join(backup_dir, rel.replace(os.sep, "__"))
        full = os.path.join(root, rel)
        if os.path.isfile(src):
            shutil.copy2(src, full)
        elif os.path.isfile(src + ".ABSENT") and os.path.isfile(full):
            os.remove(full)


def _fmt_gates(g):
    return ", ".join("%s=%s" % (k, {True: "pass", False: "FAIL", None: "n/a"}[v])
                     for k, v in sorted(g.items()))


def emit(line, log, root, code):
    """One line to stdout. Everything else to the log file."""
    log_path = os.path.join(root, "q-system", "output", "claude-changes", "apply.log")
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as fh:
            fh.write("=== %s\n" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            for entry in log:
                fh.write("  %s\n" % entry)
            fh.write("  RESULT: %s\n" % line)
    except OSError:
        log_path = "(log unavailable)"
    print("%s (log: %s)" % (line, log_path))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Refusal as exc:
        sys.exit(emit("REFUSED: %s" % exc, ["refusal: %s" % exc],
                      _ROOT or repo_root_from_script(), 2))
