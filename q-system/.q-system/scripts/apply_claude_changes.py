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

  L1 additive-only  : the only ops that EXIST are insert_after, insert_before,
                      append, create_file. There is no replace and no delete, so
                      "remove a hook entry" is not expressible. Unknown ops and
                      unknown proposal keys are refused, so a proposal cannot
                      smuggle in a flag like disables_enforcement.
  L2 ratchet        : census the live enforcement points before and after. Every
                      pre-existing member must still be present and no category
                      may shrink. This catches the technically-additive edit that
                      removes something as a side effect -- e.g. inserting
                      " || true" after a hook command, which deletes nothing but
                      makes the old exact command string vanish from the census.
  L3 verify+revert  : run the gate suite before and after. Any gate that goes
                      pass -> fail auto-restores the backup. The founder must
                      never be the one who notices a regression.

Everything runs against a COPY of .claude/ first. The live tree is touched only
after all of L1, L2 and the preconditions pass on that copy, so a refusal never
half-writes.

OUT OF REACH BY DESIGN (say so, do not pretend otherwise): removing a hook,
deleting a rule, narrowing a matcher, and widening permissions.allow or
defaultMode cannot be done through this path at all. Those need a different
tool and a real conversation. See REFUSED_SURFACES.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

SCHEMA_VERSION = 1

# L1: the entire op vocabulary. Additive only. There is deliberately no
# "replace" and no "delete" -- a removal is not expressible, not merely gated.
ADDITIVE_OPS = ("insert_after", "insert_before", "append", "create_file")

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


class Refusal(Exception):
    """A refusal is a normal outcome, not a crash. Carries the one-line reason."""


# Set the moment --root is parsed, so a refusal logs into the tree the run was
# aimed at. Without this the refusal handler fell back to the REAL repo root and
# a test run against a temp fixture would append to the live repo's apply.log --
# a test touching a live data path, which the fable-discipline lint exists to stop.
_ROOT = None


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
        if op not in ADDITIVE_OPS:
            raise Refusal(
                "edit %d op %r is not additive (allowed: %s)" % (idx, op, ", ".join(ADDITIVE_OPS))
            )
        for field in ("file", "insert", "reason"):
            if not isinstance(edit.get(field), str) or not edit[field].strip():
                raise Refusal("edit %d.%s must be a non-empty string" % (idx, field))
        if op in ("insert_after", "insert_before"):
            if not isinstance(edit.get("anchor"), str) or not edit["anchor"].strip():
                raise Refusal("edit %d needs a non-empty anchor for op %s" % (idx, op))
        elif "anchor" in edit:
            raise Refusal("edit %d op %s takes no anchor" % (idx, op))
    return prop


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

def apply_edit(content, edit, rel):
    """Return (new_content, already_satisfied). Pure; never touches disk."""
    op = edit["op"]
    ins = edit["insert"]

    if op == "append":
        if content.endswith(ins):
            return content, True
        return content + ins, False

    if op == "create_file":
        if content is None:
            return ins, False
        if content == ins:
            return content, True
        raise Refusal("create_file target already exists with different content: %s" % rel)

    anchor = edit["anchor"]
    hits = content.count(anchor)
    if hits == 0:
        raise Refusal("anchor not found in %s: %r" % (rel, _snip(anchor)))
    if hits > 1:
        raise Refusal("anchor matches %d times (must be exactly 1) in %s: %r" % (hits, rel, _snip(anchor)))

    pos = content.index(anchor)
    if op == "insert_after":
        cut = pos + len(anchor)
        if content[cut:cut + len(ins)] == ins:
            return content, True
        return content[:cut] + ins + content[cut:], False

    # insert_before
    if content[max(0, pos - len(ins)):pos] == ins:
        return content, True
    return content[:pos] + ins + content[pos:], False


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
    import re
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

def check_template_pairs(root, prop, staged, log):
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
    tpl_rel = "settings-template.json"
    if tpl_rel in staged:
        content = staged[tpl_rel]
        origin = "this proposal"
    else:
        tpl = os.path.join(root, tpl_rel)
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

    log = []
    prop = load_proposal(proposal_path)
    slug = prop["slug"]
    log.append("proposal %s: %s" % (slug, prop["reason"]))
    log.append("root: %s" % root)

    check_requires(root, prop, log)

    # ---- stage every edit against an in-memory COPY. Nothing on disk yet.
    targets = {os.path.normpath(e["file"]) for e in prop["edits"]}
    touches_settings = ".claude/settings.json" in targets
    touches_template = bool(targets & PAIRED_OUTSIDE)
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

    check_template_pairs(root, prop, staged, log)

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
        log.append("ratchet ok: hooks %d->%d, rules %d->%d, deny %d->%d" % (
            len(before_census["hooks"]), len(after_census["hooks"]),
            len(before_census["rules"]), len(after_census["rules"]),
            len(before_census["deny"]), len(after_census["deny"])))

        if ".claude/settings.json" in staged:
            permission_surface_check(root, staged[".claude/settings.json"])
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

    for rel in sorted(staged):
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(staged[rel])
        written.append(rel)
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
