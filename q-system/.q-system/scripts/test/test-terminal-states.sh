#!/usr/bin/env bash
# NEVER LET THIS TEST REACH THE FOUNDER PHONE (ASK-729).
#
# This file passes driver scripts to validate.py and to python mutation helpers
# as FILE ARGUMENTS; it never executes them, so today nothing here can page. That
# is a property of the current code, not a guarantee about the next edit: the
# worker and the dispatcher are both pager-capable, and the moment any assertion
# here decides to RUN one, an unstubbed run rings the founder actual phone at
# whatever hour the suite happens to fire.
#
# So the seam is stubbed once, up front, for the whole file rather than argued
# about per call site. The fable-discipline lint also reads a driver path being
# handed to python3 as "this test drives the runner" and blocks on it; this export
# answers that honestly instead of bypassing the gate with a skip marker, which
# would switch the check off for every future edit to this file too.
export KIPI_NOTIFY=/usr/bin/true

# test-terminal-states.sh -- the gate that stops a tenth dead end shipping.
#
# Pairs with q-system/.q-system/terminal-states.json (Piece B,
# prd-terminal-state-redrive-2026-08-01, issue terminal-states-validator).
#
# WHY THIS EXISTS. The Linear loop has abnormal exits in THREE drivers. As of
# 2026-08-01 exactly one had a working machine consumer. Every other exit either
# pages the founder or routes to nobody, and the founder does not read or work on
# code -- so those are permanent parking lots. A hand-maintained registry was the
# v1 design and was rejected (finding-4): it cannot detect an exit someone adds
# later. So the exits are enumerated FROM SOURCE at runtime and the registry is
# only allowed to explain them.
#
# THREE DRIVERS, NOT ONE (ASK-353). v1 declared a single `source`,
# linear-worker.sh, and reported green while converge.sh and kipi-dispatch.sh
# dead-ended freely. `sources` is now a list, each entry declaring which
# enumerator SHAPES apply to it, and every row names the source it belongs to.
#
# FOUR THINGS IT REFUSES TO CERTIFY:
#   1. An exit with no registry row (finding-4). Including one added directly
#      beneath an existing marker -- see the `sites` count below.
#   2. A consumer proven only by a file on disk (finding-14). A plist can exist
#      while the job is unloaded or dead, which is the exact silent-consumer
#      failure this PRD exists to prevent. Liveness means loaded AND a run
#      inside the interval.
#   3. A row whose only actor is the founder. He is not an available actor;
#      naming him is how a dead end gets dressed as a consumer.
#   4. A consumer whose named job contains no selector for this state (ASK-353).
#      A liveness_check proves a job RAN, never that it re-enters HERE. That gap
#      is the validator-satisfying fiction the archived PRD named: ci-redrive.py
#      excluded the reviewer slots on the strength of a comment claiming
#      "it is also already handled", and nothing handled it, for 29 hours
#      (ASK-352). So `reentry` names a file and a literal marker, and this
#      script opens the file and looks for it.
#
# ROWS KEY ON STABLE MARKERS, NEVER LINE NUMBERS (finding-15). The evidence is
# this PRD's own v1: it cited :1297 (which resets variables) and :1295 (a
# comment), and missed that the real persistent stuck gate is :680.
#
# Exit 0 = green. Exit 1 = RED, with every failing site or row named.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# BASH_SOURCE-derived, so the root follows the CODE rather than the caller's cwd.
# This file propagates fleet-wide through `kipi update`; a $PWD-derived root
# would make it validate whichever tree someone happened to be standing in.
ROOT="$(cd "$HERE/../../../.." && pwd)"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0
ok()   { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

# --- the validator ----------------------------------------------------------
# Written to a file and executed, NOT embedded in a $( ) heredoc. Inside a
# command substitution bash keeps tracking quote state through a quoted heredoc,
# so one apostrophe in a Python comment swallows the rest of the substitution --
# the trap that killed linear-worker.sh with "unexpected EOF" and is warned about
# in that file twice.
cat > "$WORK/validate.py" <<'PYEOF'
#!/usr/bin/env python3
"""Validate terminal-states.json against every declared driver, from source.

argv: <registry.json> <repo-root> <capability-manifest.json>

Each registry source declares a repo-relative `path` (an ABSOLUTE path is honored
as-is, which is how the fixtures below point a source at a mutated copy) and the
enumerator `shapes` that apply to it.

Env seams (fixtures only; unset in real runs so the live system is what is read):
  TERMINAL_STATES_LAUNCHCTL    launchd control binary (default: launchctl)  # portability-lint-skip
  TERMINAL_STATES_LAUNCHD_DIR  LaunchAgents directory (default: ~/Library/LaunchAgents)
"""
import json, os, re, shutil, subprocess, sys, time

BLOCK_LOOKBACK = 40  # non-comment lines above a site searched for its marker

# A consumer is a MACHINE. These words in a consumer field mean the row is a
# dead end wearing a consumer's clothes -- the failure this whole PRD is about.
HUMAN_ACTOR = re.compile(
    r"\b(founder|assaf|human|humans|a person|by hand|manually|someone)\b", re.I)
# finding-15: identity is a stable marker. These shapes are line numbers.
LINE_NUMBERISH = re.compile(r"^\s*:?\d+\s*$|\.sh:\d+")

# REVERSED 2026-08-03 BY FOUNDER DIRECTIVE ("nothing should be on me"), ASK-353.
# owner:assaf was a DESIGNED founder queue in the archived PRD and is now an
# error path. A registry that still calls it terminal would keep certifying the
# routing as intended, so the shape is refused here rather than left to review.
FOUNDER_QUEUE = "owner:assaf"

KNOWN_SHAPES = ("issue-loop-continue", "ready-return", "label-apply", "toplevel-exit")

# The three drivers of the Linear loop, as enumerated for ASK-353. This is the
# COVERAGE FLOOR: the registry may add sources, never drop one of these. It is a
# constant in the checker precisely so that narrowing coverage takes an edit to
# the checker -- visible in a diff and answerable in review -- instead of being a
# silent side effect of deleting rows from the file being checked.
#
# KEYED ON ID, NOT ON PATH, and the difference is load-bearing. The suite's own
# mutation fixtures repoint a source at a COPY under $FIX (a tenth dead end added
# to converge.sh, etc.) -- that is the harness verifying against a copy instead of
# the live driver, which is the rule, not a dodge. A path-literal floor called
# every one of those a missing driver and took four passing tests red. The id is
# what survives a legitimate repoint; deleting the entry, which is the bypass
# codex found, changes the id set. The live registry's PATHS are pinned
# separately, in the shell, against the unmutated file (see "coverage floor"
# below).
REQUIRED_SOURCE_IDS = ("linear-worker", "converge", "kipi-dispatch")

HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
# `exit` in COMMAND POSITION only. Without the position anchor every `say "STOP
# exit-7: ..."` line in converge.sh reads as an exit site, and there are nine of
# those; the negative lookahead drops `exit-7` itself.
EXIT_CMD = re.compile(r"""(?:^|[;&|{(]|\b(?:then|else|do)\b)\s*exit\b(?!-)""")
FUNC_OPEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\(\)\s*\{\s*$")
FUNC_CLOSE = re.compile(r"^\}\s*$")


def read_lines(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


def is_comment(line):
    s = line.lstrip()
    return s.startswith("#") or not s


def mask_heredocs(lines):
    """Heredoc BODIES replaced by None so their contents are never parsed.

    kipi-dispatch.sh embeds python that contains `sys.exit(0)`, and converge.sh
    embeds python too. Reading a heredoc body as shell is how a parser invents an
    exit that no shell branch can reach.
    """
    out, delim = [], None
    for ln in lines:
        if delim is not None:
            out.append(None)
            if ln.strip() == delim:
                delim = None
            continue
        out.append(ln)
        if not ln.lstrip().startswith("#"):
            m = HEREDOC.search(ln)
            if m:
                delim = m.group(2)
    return out


def sites_toplevel_exit(lines):
    """Every top-level `exit` in a single-run driver.

    converge.sh drives ONE issue and kipi-dispatch.sh drives ONE cycle, so an
    exit outside a function body ends that run -- the same meaning `continue` has
    inside the worker's issue loop. Function bodies are excluded because an exit
    there is reached through a call site that is itself top-level, and counting
    both would double-count one dead end.

    The function test is deliberately shape-based (`name() {` at column 0, closed
    by `}` at column 0) rather than brace-counting: brace counting in bash is
    wrong the moment a string or a case arm contains one, and both files hold to
    the column-0 convention. The parser asserts that it ends OUTSIDE a function,
    so a file that breaks the convention fails loudly instead of silently
    swallowing every exit after the first ragged definition.
    """
    masked = mask_heredocs(lines)
    sites, infn, opened_at = [], False, 0
    for i, ln in enumerate(masked):
        if ln is None:
            continue
        if not infn and FUNC_OPEN.match(ln):
            infn, opened_at = True, i + 1
            continue
        if infn and FUNC_CLOSE.match(ln):
            infn = False
            continue
        if infn or is_comment(ln):
            continue
        if EXIT_CMD.search(ln):
            sites.append((i + 1, "toplevel-exit", ln.strip()))
    if infn:
        raise SystemExit(
            "ENUMERATION FAILED: reached end of file still inside the function "
            "opened at line %d. The column-0 `name() {` / `}` convention this "
            "parser depends on is broken, so every exit below that point would "
            "be invisible." % opened_at)
    return sites


def sites_issue_loop_continue(lines):
    start = end = None
    for i, ln in enumerate(lines):
        if start is None and re.search(r"while\s+IFS=\s*read\s+-r\s+ISSUE\s*;\s*do", ln):
            start = i
        elif start is not None and re.match(r"^done\b", ln):
            end = i
            break
    if start is None:
        raise SystemExit("ENUMERATION FAILED: no `while IFS= read -r ISSUE; do` issue "
                         "loop in the source. The parser is looking at the wrong shape.")
    if end is None:
        end = len(lines)
    out = []
    for i in range(start + 1, end):
        if is_comment(lines[i]):
            continue
        if re.search(r"\bcontinue\b", lines[i]):
            out.append((i + 1, "continue", lines[i].strip()))
    return out


def sites_ready_return(lines):
    rstart = None
    for i, ln in enumerate(lines):
        if re.match(r"^def ready\(i\):", ln):
            rstart = i
            break
    if rstart is None:
        raise SystemExit("ENUMERATION FAILED: no `def ready(i):` predicate in the source.")
    out = []
    for i in range(rstart + 1, len(lines)):
        ln = lines[i]
        if ln.strip() and not ln.startswith((" ", "\t")):
            break  # dedent out of the function
        if is_comment(ln):
            continue
        if re.search(r"\breturn\b", ln):
            out.append((i + 1, "ready-return", ln.strip()))
    return out


def sites_label_apply(lines):
    out = []
    for i, ln in enumerate(lines):
        if is_comment(ln):
            continue
        # A NON-EMPTY assignment. `REFUSE_LABEL=""` is the per-issue RESET at the
        # top of the refusal block, not a label being applied -- and it is the
        # very line the PRD's v1 mis-cited as a transition (":1297 resets
        # variables", finding-15). This validator reported it as an unregistered
        # exit on its first run, which is the same mistake from the other side.
        if re.search(r'REFUSE_LABEL="[^"]+"', ln):
            out.append((i + 1, "label-apply", ln.strip()))
    return out


SHAPE_FN = {
    "issue-loop-continue": sites_issue_loop_continue,
    "ready-return": sites_ready_return,
    "label-apply": sites_label_apply,
    "toplevel-exit": sites_toplevel_exit,
}


def enumerate_sites(lines, shapes):
    sites = []
    for shape in shapes:
        sites.extend(SHAPE_FN[shape](lines))
    return sorted(sites)


def match_site(site_line, lines, rows):
    """The row whose marker sits CLOSEST above this site.

    Bounded to BLOCK_LOOKBACK non-comment lines: an unbounded search would let a
    marker hundreds of lines up claim an unrelated exit. Comment lines are
    skipped because every one of these markers is also DISCUSSED in prose here,
    and a row must be anchored to code that runs, not to a sentence about it.
    """
    best, best_at, tie = None, -1, False
    seen = 0
    for idx in range(site_line - 1, -1, -1):
        if lines[idx] is None or is_comment(lines[idx]):
            continue
        seen += 1
        if seen > BLOCK_LOOKBACK:
            break
        for row in rows:
            if any(m in lines[idx] for m in row["_markers"]):
                if idx > best_at:
                    best, best_at, tie = row, idx, False
                elif idx == best_at and row is not best:
                    tie = True
    return best, tie


def check_liveness(lc, errors, row_id):
    """Prove the consumer RAN. A plist on disk is not evidence (finding-14)."""
    kind = lc.get("kind")
    if kind != "launchd":
        errors.append(f"{row_id}: unknown liveness_check kind {kind!r}")
        return
    label = lc.get("label", "")
    ev = os.path.expanduser(lc.get("run_evidence", ""))
    max_age = lc.get("max_age_s")
    if not label or not ev or not isinstance(max_age, int):
        errors.append(f"{row_id}: liveness_check needs label, run_evidence and max_age_s")
        return

    agents = os.path.expanduser(
        os.environ.get("TERMINAL_STATES_LAUNCHD_DIR", "~/Library/LaunchAgents"))
    plist = os.path.join(agents, label + ".plist")
    if not os.path.isfile(plist):
        # Never installed on THIS machine. This script propagates fleet-wide via
        # kipi update to instances that never had the job, and failing there
        # would make the gate a nuisance everyone learns to skip. An installed
        # plist is what turns liveness into a claim -- see the branch below.
        print(f"    note: {row_id}: {label} is not installed here; liveness not asserted")
        return

    lcbin = os.environ.get("TERMINAL_STATES_LAUNCHCTL", "launchctl")
    # A plist EXISTS at this point, so this host DOES own the job; only the
    # ability to read its state is missing. That is a gap in the evidence, not a
    # pass. For one round this comment said exactly that while the code below
    # printed a note and returned clean, so pointing TERMINAL_STATES_LAUNCHCTL at
    # a nonexistent binary certified every consumer with zero evidence and the
    # suite still reported 12 passed (codex-adversarial finding-4). The
    # host-never-had-the-job case already returned at the plist check above, so
    # failing closed here costs the fleet nothing.
    if not (os.path.isfile(lcbin) or shutil.which(lcbin)):
        errors.append(f"{row_id}: {label} has a plist at {plist} but {lcbin} is not "
                      "available to read its state -- liveness cannot be asserted, "
                      "and an unverifiable consumer is not a proven live one")
        return
    try:
        rc = subprocess.run([lcbin, "list", label],
                            capture_output=True, text=True, timeout=10).returncode
    except Exception as exc:
        errors.append(f"{row_id}: could not run {lcbin} list {label}: {exc}")
        return
    if rc != 0:
        # THE EXACT FAILURE finding-14 NAMES: the plist is right there on disk
        # and the job is not loaded, so it silently never runs.
        errors.append(f"{row_id}: {label} has a plist at {plist} but is NOT LOADED -- "
                      "it can never run, so this state has no consumer")
        return
    if not os.path.exists(ev):
        errors.append(f"{row_id}: {label} is loaded but its run evidence {ev} "
                      "does not exist -- no run has ever been observed")
        return
    age = time.time() - os.path.getmtime(ev)
    if age > max_age:
        errors.append(f"{row_id}: {label} is loaded but has not run in "
                      f"{int(age)}s (interval allows {max_age}s) -- a loaded job "
                      "that stopped running is a dead consumer")


def check_pointer(row_id, field, ptr, root, errors):
    """A {path, marker} pointer must resolve to a file that CONTAINS the marker.

    This is the anti-fiction check (ASK-353). `consumer` is prose and prose is
    what lied for 29 hours; this makes the claim executable. Absence of the
    marker means either the selector was never written or it moved, and both
    answers are "you cannot certify this row today".
    """
    if not isinstance(ptr, dict):
        errors.append(f"{row_id}: {field} must be an object with `path` and `marker`")
        return
    path, marker = ptr.get("path"), ptr.get("marker")
    if not isinstance(path, str) or not path or not isinstance(marker, str) or not marker:
        errors.append(f"{row_id}: {field} needs a non-empty `path` and `marker`")
        return
    if LINE_NUMBERISH.search(marker):
        errors.append(f"{row_id}: {field} marker {marker!r} is a LINE NUMBER (finding-15)")
        return
    full = path if os.path.isabs(path) else os.path.join(root, path)
    if not os.path.isfile(full):
        errors.append(f"{row_id}: {field} names {path}, which does not exist. A pointer "
                      "at a missing file proves nothing.")
        return
    with open(full, encoding="utf-8", errors="replace") as fh:
        if marker not in fh.read():
            errors.append(
                f"{row_id}: {field} claims {path} contains {marker[:60]!r} and it does "
                "NOT. That is a claim with no code behind it -- the exact shape of "
                "ci-redrive.py's false 'it is also already handled' comment (ASK-352).")


def main():
    reg_path, root, man_path = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(reg_path, encoding="utf-8") as fh:
        registry = json.load(fh)
    rows = registry.get("states", [])
    errors = []

    declared_tests = set()
    if os.path.isfile(man_path):
        with open(man_path, encoding="utf-8") as fh:
            declared_tests = {e.get("path") for e in json.load(fh).get("expected_tests", [])}

    # -- sources --------------------------------------------------------------
    sources = registry.get("sources")
    if not isinstance(sources, list) or not sources:
        raise SystemExit("REGISTRY FAILED: `sources` must be a non-empty list. A single "
                         "`source` is the v1 shape that walked one of three drivers "
                         "and reported green (ASK-353).")

    # THE FLOOR LIVES IN THE CHECKER, NOT IN THE DATA IT CHECKS (codex PR #215,
    # major). Making `sources` a list fixed the v1 shape but left the registry
    # declaring its own coverage: delete the converge and kipi-dispatch entries
    # AND the rows pointing at them, and every remaining row still validates --
    # green again, on one driver again, which is the exact defect this issue was
    # opened for. Enforcement a file can switch off by editing itself is not
    # enforcement.
    #
    declared_ids = {s.get("id") for s in sources if isinstance(s, dict)}
    for req in REQUIRED_SOURCE_IDS:
        if req not in declared_ids:
            raise SystemExit(
                f"REGISTRY FAILED: source {req!r} is a DRIVER of this loop and no `sources` "
                "entry declares it. Its exits are then never enumerated, so every dead end "
                "in it reads as green -- the one-driver blind spot ASK-353 closed. Add the "
                "source back, or change REQUIRED_SOURCE_IDS in this validator and say in "
                "the diff why that file stopped being a driver.")

    src_lines, src_shapes = {}, {}
    for src in sources:
        sid, path = src.get("id"), src.get("path")
        shapes = src.get("shapes")
        if not sid or not path or not isinstance(shapes, list) or not shapes:
            raise SystemExit(f"REGISTRY FAILED: source {src!r} needs id, path and shapes")
        for sh in shapes:
            if sh not in KNOWN_SHAPES:
                raise SystemExit(f"REGISTRY FAILED: source {sid}: unknown shape {sh!r}")
        full = path if os.path.isabs(path) else os.path.join(root, path)
        if not os.path.isfile(full):
            raise SystemExit(f"REGISTRY FAILED: source {sid} path {path} does not exist")
        src_lines[sid] = read_lines(full)
        src_shapes[sid] = shapes

    # -- schema ---------------------------------------------------------------
    seen_ids = set()
    seen_markers = {}          # (source, marker) -> row id; markers are per-source
    for row in rows:
        rid = row.get("id", "<no id>")
        if rid in seen_ids:
            errors.append(f"duplicate row id: {rid}")
        seen_ids.add(rid)

        sid = row.get("source")
        if sid not in src_lines:
            errors.append(f"{rid}: `source` {sid!r} is not a declared source id. Every "
                          "row belongs to exactly one driver.")
            continue

        # `marker` is a string OR a list. A list is not a convenience: one state
        # can reach the source in two SHAPES (a label tested in a predicate, the
        # same label assigned at the refusal), and a single loose token that
        # spans both also matches prose and unrelated code. Round 1 of this
        # validator used the bare string "needs-scope" and it silently claimed
        # linear-worker.sh:654 -- the dirty-file ignore list -- as a third exit
        # site. Exact tokens, one per shape.
        marker = row.get("marker")
        markers = [marker] if isinstance(marker, str) else (marker or [])
        if not markers or not all(isinstance(m, str) and m for m in markers):
            errors.append(f"{rid}: no marker (string, or list of strings)")
            continue
        row["_markers"] = markers
        for m in markers:
            if LINE_NUMBERISH.search(m):
                errors.append(f"{rid}: marker {m!r} is a LINE NUMBER. Identity must be "
                              "a stable token (label name, sentinel filename, function "
                              "name) -- line numbers drift on the first nearby edit "
                              "(finding-15)")
            if (sid, m) in seen_markers:
                errors.append(f"{rid}: marker {m!r} is already used by "
                              f"{seen_markers[(sid, m)]} in source {sid}")
            seen_markers[(sid, m)] = rid

        if not isinstance(row.get("sites"), int) or row["sites"] < 1:
            errors.append(f"{rid}: `sites` must be a positive int (it is what makes an "
                          "exit added beneath an existing marker detectable)")

        has_consumer = bool(row.get("consumer"))
        is_terminal = row.get("terminal") is True
        is_error = row.get("error_path") is True
        if sum((has_consumer, is_terminal, is_error)) != 1:
            errors.append(f"{rid}: declare EXACTLY ONE of consumer+liveness_check+reentry, "
                          "terminal:true+rationale, or error_path:true+error_evidence")

        # THE FOUNDER QUEUE IS AN ERROR PATH NOW (ASK-353, founder directive
        # 2026-08-03). Refused as a SHAPE rather than by row id, so re-adding the
        # queue under a new row name does not slip through.
        if any(FOUNDER_QUEUE in m for m in markers) and not is_error:
            errors.append(
                f"{rid}: marker names {FOUNDER_QUEUE} but the row is not error_path:true. "
                "The founder queue was closed by directive 2026-08-03 (`nothing should be "
                "on me`); a code path routing work there is a DEFECT that must fail "
                "loudly, not a terminal state the registry certifies as designed.")

        if is_error:
            if not row.get("error_evidence"):
                errors.append(f"{rid}: error_path:true needs error_evidence naming the "
                              "file and marker where the code says so out loud. Without "
                              "it this is a label, not an error path.")
            else:
                check_pointer(rid, "error_evidence", row["error_evidence"], root, errors)
            if len((row.get("rationale") or "").strip()) < 40:
                errors.append(f"{rid}: error_path:true needs a written rationale")

        if has_consumer:
            # Type-guard BEFORE the regex. HUMAN_ACTOR.search on a non-string
            # raises an uncaught TypeError that kills the run before a single
            # RED: line prints, so one malformed row silently suppressed every
            # other row's findings -- a gate that reports nothing looks exactly
            # like a gate that found nothing (codex-adversarial finding-5).
            if not isinstance(row["consumer"], str):
                errors.append(f"{rid}: consumer must be a string, got "
                              f"{type(row['consumer']).__name__}")
            elif HUMAN_ACTOR.search(row["consumer"]):
                errors.append(
                    f"{rid}: consumer names a HUMAN ({row['consumer'][:60]!r}). The "
                    "founder does not read or work on code, so a state whose only "
                    "actor is a person does not continue. If that is the truth, say "
                    "terminal:true with a rationale instead of dressing it as a consumer")
            if not row.get("liveness_check"):
                errors.append(f"{rid}: a consumer without a liveness_check proves "
                              "nothing ran (finding-14)")
            else:
                check_liveness(row["liveness_check"], errors, rid)
            # ASK-353: liveness proves the job RAN, never that it re-enters HERE.
            if not row.get("reentry"):
                errors.append(f"{rid}: a liveness_check without a `reentry` pointer is "
                              "not accepted -- it proves the job ran, not that the job "
                              "ever selects THIS state. Name the consumer file and the "
                              "literal selector marker inside it.")
            else:
                check_pointer(rid, "reentry", row["reentry"], root, errors)
            ct = row.get("consumer_test")
            if ct and ct not in declared_tests:
                errors.append(f"{rid}: consumer_test {ct} is not in "
                              "capability-manifest.json expected_tests, so nothing "
                              "runs it -- the consumer is never proven to read this state")
        if is_terminal:
            if len((row.get("rationale") or "").strip()) < 40:
                errors.append(f"{rid}: terminal:true needs a written rationale. An honest "
                              "dead end passes; an unexamined one does not")
            # Optional, but verified when present: a refusal ON EVIDENCE is what
            # this issue asked each remaining state for, and unverified evidence
            # is just a longer rationale.
            if row.get("evidence"):
                check_pointer(rid, "evidence", row["evidence"], root, errors)

    # -- the founder queue must be registered at all ---------------------------
    if not any(any(FOUNDER_QUEUE in m for m in r.get("_markers", [])) for r in rows):
        errors.append(
            f"no row covers {FOUNDER_QUEUE}. It is an error path, and an error path "
            "nobody registered is indistinguishable from one nobody has.")

    # -- enumeration, per source ----------------------------------------------
    good_rows = [r for r in rows if r.get("_markers") and r.get("source") in src_lines]
    observed = {r["id"]: 0 for r in good_rows}
    debug = os.environ.get("TERMINAL_STATES_DEBUG") == "1"
    total_sites = 0
    for sid, lines in src_lines.items():
        rows_here = [r for r in good_rows if r["source"] == sid]
        if not rows_here:
            errors.append(f"source {sid} has NO registry rows. A declared driver nobody "
                          "explained is the v1 hole, not a clean source.")
        sites = enumerate_sites(lines, src_shapes[sid])
        total_sites += len(sites)
        # heredoc bodies are masked for matching too, for the same reason they are
        # masked for enumeration: a marker found inside embedded python is not the
        # shell branch that runs.
        mlines = mask_heredocs(lines) if "toplevel-exit" in src_shapes[sid] else lines
        for line_no, kind, text in sites:
            row, tie = match_site(line_no, mlines, rows_here)
            if debug:
                # The site table. A RED here is usually a marker claiming a site
                # it does not own, and reading that off the source by hand is the
                # slow way to find it.
                print(f"    [{sid}] site {line_no:>5} {kind:<18} -> "
                      f"{(row or {}).get('id', 'UNMATCHED')}   | {text[:60]}")
            if row is None:
                errors.append(
                    f"UNREGISTERED EXIT in source {sid} at line {line_no} ({kind})\n"
                    f"      {text}\n"
                    "      No registry row's marker appears above it. Add a row to "
                    "terminal-states.json naming a consumer + liveness_check + reentry, "
                    "or terminal:true with a rationale.")
                continue
            if tie:
                errors.append(f"AMBIGUOUS EXIT in source {sid} at line {line_no}: "
                              "two markers tie for nearest. Make one more specific.")
                continue
            observed[row["id"]] += 1

    for row in good_rows:
        got, want = observed[row["id"]], row.get("sites")
        if isinstance(want, int) and got != want:
            if got == 0:
                errors.append(f"{row['id']}: marker(s) {row['_markers']!r} match NO "
                              f"exit in source {row['source']}. Stale row, or the "
                              "marker moved.")
            else:
                errors.append(f"{row['id']}: covers {got} exit site(s), registry "
                              f"declares {want}. An exit was added or removed next to "
                              f"marker(s) {row['_markers']!r} -- reconcile the row.")

    print(f"    enumerated {total_sites} exit site(s) across {len(src_lines)} driver(s); "
          f"{len(rows)} registry row(s)")
    if errors:
        for e in errors:
            print(f"    RED: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
PYEOF

REG="$ROOT/q-system/.q-system/terminal-states.json"
SRC="$ROOT/q-system/.q-system/scripts/linear-worker.sh"
CONVERGE="$ROOT/q-system/.q-system/scripts/converge.sh"
DISPATCH="$ROOT/kipi-dispatch.sh"
MAN="$ROOT/q-system/.q-system/capability-manifest.json"

for f in "$REG" "$SRC" "$CONVERGE" "$DISPATCH" "$MAN"; do
  if [ ! -f "$f" ]; then echo "RED: missing $f"; exit 1; fi
done

echo "== terminal-states validator =="

# --- 1. the real thing must be green ----------------------------------------
if python3 "$WORK/validate.py" "$REG" "$ROOT" "$MAN"; then
  ok "live registry covers every enumerated exit in all three drivers"
else
  bad "live registry does NOT validate against its declared drivers"
fi

# --- fixture plumbing --------------------------------------------------------
# Every negative test runs against COPIES. Nothing below reads or writes the
# live registry, the live sources, or ~/.config/kipi -- the fable-discipline rule
# that a test never touches a live data path.
FIX="$WORK/fix"; mkdir -p "$FIX"
mkdir -p "$FIX/agents"
: > "$FIX/agents/com.kipi.fixture-job.plist"
cat > "$FIX/launchctl-loaded" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat > "$FIX/launchctl-unloaded" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$FIX/launchctl-loaded" "$FIX/launchctl-unloaded"

# A fixture registry that is otherwise VALID, so each negative test isolates the
# one defect it is about. Built by mutating the live registry in memory.
mkfixture() {  # mkfixture <out> <python-mutation-on-`d`>
  local out="$1" mut="$2"
  python3 - "$REG" "$out" "$mut" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
def source(sid):
    return [s for s in d["sources"] if s["id"] == sid][0]
def state(rid):
    return [r for r in d["states"] if r["id"] == rid][0]
exec(sys.argv[3])
json.dump(d, open(sys.argv[2], "w"), indent=2)
EOF
}

expect_red() {  # expect_red <name> <registry> <grep-pattern> [env...]
  local name="$1" reg="$2" pat="$3"; shift 3
  local out rc
  out="$(env "$@" python3 "$WORK/validate.py" "$reg" "$ROOT" "$MAN" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then
    bad "$name -- validator returned GREEN on a case it must refuse"
    return
  fi
  if printf '%s' "$out" | grep -q "$pat"; then
    ok "$name (RED, and names it)"
  else
    bad "$name -- went RED but did not name the defect (wanted /$pat/)"
    printf '%s\n' "$out" | sed 's/^/        /'
  fi
}

# --- 2. NEGATIVE SELF-TEST (a): the only actor is the founder ---------------
# The bypass_check's first half. This is the shape every parked state in this
# loop already has, so a validator that accepts it certifies the bug.
mkfixture "$FIX/founder.json" '
row = state("attempts-cap-stuck")
row.pop("terminal", None); row.pop("rationale", None); row.pop("evidence", None)
row["consumer"] = "the founder reviews the issue and decides what to do next"
row["liveness_check"] = {"kind": "launchd", "label": "com.kipi.fixture-job",
                         "run_evidence": "'"$FIX"'/ran", "max_age_s": 86400}
row["reentry"] = {"path": "q-system/.q-system/scripts/linear-worker.sh",
                  "marker": "stuck_paged"}
'
touch "$FIX/ran"
expect_red "negative (a): a row whose only actor is the founder" \
  "$FIX/founder.json" "consumer names a HUMAN" \
  "TERMINAL_STATES_LAUNCHD_DIR=$FIX/agents" \
  "TERMINAL_STATES_LAUNCHCTL=$FIX/launchctl-loaded"

# --- 3. NEGATIVE SELF-TEST (b): consumer has not run inside its interval ----
# The bypass_check's second half, and finding-14 exactly: the plist is present
# AND the job is loaded. Only the absence of a RUN makes this red.
mkfixture "$FIX/stale.json" '
row = state("needs-scope")
row.pop("consumer_test")
row["liveness_check"] = {"kind": "launchd", "label": "com.kipi.fixture-job",
                         "run_evidence": "'"$FIX"'/stale-ran", "max_age_s": 60}
'
touch -t 202601010000 "$FIX/stale-ran"
expect_red "negative (b): consumer is loaded but has not run inside its interval" \
  "$FIX/stale.json" "has not run in" \
  "TERMINAL_STATES_LAUNCHD_DIR=$FIX/agents" \
  "TERMINAL_STATES_LAUNCHCTL=$FIX/launchctl-loaded"

# --- 4. a plist on disk while the job is unloaded (finding-14, literally) ----
mkfixture "$FIX/unloaded.json" '
row = state("needs-scope")
row.pop("consumer_test")
row["liveness_check"] = {"kind": "launchd", "label": "com.kipi.fixture-job",
                         "run_evidence": "'"$FIX"'/ran", "max_age_s": 86400}
'
expect_red "a present plist whose job is UNLOADED fails (path existence would pass)" \
  "$FIX/unloaded.json" "NOT LOADED" \
  "TERMINAL_STATES_LAUNCHD_DIR=$FIX/agents" \
  "TERMINAL_STATES_LAUNCHCTL=$FIX/launchctl-unloaded"

# --- 5. MUTATION: delete a row -> the check must go red ----------------------
# If either of these stays green the enumeration is decorative: the registry
# would be a document rather than a gate.
#
# TWO CASES, because a deleted row fails in two different ways and asserting
# only the first would have let the second regress silently. When the orphaned
# site has no other marker above it, it is UNREGISTERED. When a neighbouring
# row's marker is within lookback, the site is ADOPTED by that neighbour and the
# only thing that catches it is that neighbour's `sites` count -- which is the
# whole reason the count field exists.
mkfixture "$FIX/dropped.json" '
d["states"] = [r for r in d["states"] if r["id"] != "attempts-cap-stuck"]
'
expect_red "mutation: deleting a row whose site stands alone -> UNREGISTERED" \
  "$FIX/dropped.json" "UNREGISTERED EXIT"

mkfixture "$FIX/dropped2.json" '
d["states"] = [r for r in d["states"] if r["id"] != "claim-contended"]
'
expect_red "mutation: deleting a row whose site is adopted by a neighbour -> count mismatch" \
  "$FIX/dropped2.json" "covers 2 exit site"

# --- 6. MUTATION: a tenth dead end added to the WORKER -----------------------
# Two variants, because they fail for different reasons and only the second one
# is hard. (a) a continue with no marker near it -> unregistered. (b) a continue
# inserted directly BENEATH an existing marker, which inherits that marker --
# caught only by the `sites` count.
SRCMUT="$WORK/worker-extra-exit.sh"
python3 - "$SRC" "$SRCMUT" <<'EOF'
import re, sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
for i, ln in enumerate(lines):
    if re.search(r"while\s+IFS=\s*read\s+-r\s+ISSUE\s*;\s*do", ln):
        lines.insert(i + 1, '  if [ "$SOME_NEW_GATE" = "1" ]; then continue; fi')
        break
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines) + "\n")
EOF
mkfixture "$FIX/srcmut.json" 'source("linear-worker")["path"] = "'"$SRCMUT"'"'
expect_red "mutation: a tenth dead end added to the worker is named as UNREGISTERED" \
  "$FIX/srcmut.json" "UNREGISTERED EXIT"

SRCMUT2="$WORK/worker-inherited-exit.sh"
python3 - "$SRC" "$SRCMUT2" <<'EOF'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
for i, ln in enumerate(lines):
    if "claimed by another session" in ln and not ln.lstrip().startswith("#"):
        lines.insert(i + 1, '    if [ "$ANOTHER_NEW_GATE" = "1" ]; then continue; fi')
        break
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines) + "\n")
EOF
mkfixture "$FIX/srcmut2.json" 'source("linear-worker")["path"] = "'"$SRCMUT2"'"'
expect_red "mutation: an exit INHERITING a nearby marker is caught by the sites count" \
  "$FIX/srcmut2.json" "declares"

# --- 6b. THE ASK-353 REPRODUCER: a dead end added to converge.sh -------------
# THE ACCEPTANCE CRITERION THIS ISSUE WAS FILED FOR. Before this change the
# registry declared one `source` and converge.sh was never read, so this exact
# mutation returned exit 0 -- a new dead end in the driver that owns every
# rework round shipped silently. Two variants for the same reason the worker has
# two: a standalone exit is UNREGISTERED, and one tucked under an existing marker
# is caught only by the sites count.
CVMUT="$WORK/converge-extra-exit.sh"
python3 - "$CONVERGE" "$CVMUT" <<'EOF'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
# INSERTED HIGH, not appended. Appending put it inside BLOCK_LOOKBACK of the
# cap-out marker at the foot of the file, so the row adopted it and the count
# check fired instead -- a real RED, for the wrong reason, and the fixture would
# have passed while asserting nothing about unregistered detection. Above every
# marker there is nothing to adopt it.
for i, ln in enumerate(lines):
    if ln.startswith("set -"):
        lines.insert(i + 1, 'if [ "$A_BRAND_NEW_DEAD_END" = "1" ]; then exit 42; fi')
        break
else:
    raise SystemExit("FIXTURE FAILED: converge.sh has no `set -` line to anchor to")
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines) + "\n")
EOF
mkfixture "$FIX/cvmut.json" 'source("converge")["path"] = "'"$CVMUT"'"'
expect_red "REPRODUCER: a dead end added to converge.sh is CAUGHT as UNREGISTERED" \
  "$FIX/cvmut.json" "UNREGISTERED EXIT"

CVMUT2="$WORK/converge-inherited-exit.sh"
python3 - "$CONVERGE" "$CVMUT2" <<'EOF'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
for i, ln in enumerate(lines):
    if "review produced no verdict on round" in ln and not ln.lstrip().startswith("#"):
        lines.insert(i + 1, '    if [ "$YET_ANOTHER_GATE" = "1" ]; then exit 43; fi')
        break
else:
    raise SystemExit("FIXTURE FAILED: converge.sh no longer carries the anchor line")
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines) + "\n")
EOF
mkfixture "$FIX/cvmut2.json" 'source("converge")["path"] = "'"$CVMUT2"'"'
expect_red "REPRODUCER: a converge exit inheriting a marker is caught by the sites count" \
  "$FIX/cvmut2.json" "declares"

# --- 6c. the same reproducer for kipi-dispatch.sh ----------------------------
DPMUT="$WORK/dispatch-extra-exit.sh"
python3 - "$DISPATCH" "$DPMUT" <<'EOF'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
# Inserted high, for the same reason the converge fixture is: appended, it sat
# under the DISPATCH DIED marker and tripped that row's count instead.
for i, ln in enumerate(lines):
    if ln.startswith("set -"):
        lines.insert(i + 1, 'if [ "$A_BRAND_NEW_DEAD_END" = "1" ]; then exit 44; fi')
        break
else:
    raise SystemExit("FIXTURE FAILED: kipi-dispatch.sh has no `set -` line to anchor to")
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines) + "\n")
EOF
mkfixture "$FIX/dpmut.json" 'source("kipi-dispatch")["path"] = "'"$DPMUT"'"'
expect_red "REPRODUCER: a dead end added to kipi-dispatch.sh is CAUGHT as UNREGISTERED" \
  "$FIX/dpmut.json" "UNREGISTERED EXIT"

# --- 6d. a row pointing at a source nothing declares -------------------------
# The ROW-level half of the coverage question. This used to be exercised by
# deleting converge + kipi-dispatch and leaving their rows behind, but the
# coverage floor (14b) now refuses that input earlier and for a stronger reason,
# so the old fixture could no longer reach this check -- it went red on the
# floor's message and asserted nothing of its own. A test that passes for another
# check's reason is not a test.
#
# Rebuilt on a source id the floor does not pin, so the two stay independent: the
# floor owns "a required driver went missing", this owns "a row belongs to no
# declared driver at all".
mkfixture "$FIX/onesource.json" '
row = dict(state("owner-assaf"))
row["id"] = "orphan-row-fixture"
row["source"] = "no-such-driver"
d["states"].append(row)
'
expect_red "a row naming a source nothing declares is refused, not silently unwalked" \
  "$FIX/onesource.json" "is not a declared source id"

# --- 7. a line number is refused as identity (finding-15) --------------------
mkfixture "$FIX/lineno.json" 'state("attempts-cap-stuck")["marker"] = "linear-worker.sh:680"'
expect_red "a line-number marker is refused as row identity" \
  "$FIX/lineno.json" "is a LINE NUMBER"

# --- 8. terminal:true without a rationale is unexamined, not honest ----------
mkfixture "$FIX/norationale.json" 'state("out-of-repo")["rationale"] = "n/a"'
expect_red "terminal:true with no written rationale is refused" \
  "$FIX/norationale.json" "needs a written rationale"

# --- 9. a consumer with no liveness_check ------------------------------------
mkfixture "$FIX/noliveness.json" 'state("needs-scope").pop("liveness_check")'
expect_red "a consumer declared without a liveness_check is refused" \
  "$FIX/noliveness.json" "proves nothing ran"

# --- 10. a consumer_test nothing runs ----------------------------------------
mkfixture "$FIX/unregtest.json" '
state("needs-scope")["consumer_test"] = \
    "q-system/.q-system/scripts/test/test-does-not-exist.sh"
'
expect_red "a consumer_test absent from capability-manifest.json is refused" \
  "$FIX/unregtest.json" "expected_tests"

# --- 11. plist present but launchctl unreadable (codex-adversarial finding-4) -
# The second fail-open, and the one the code's own comment already argued
# against while returning clean anyway. The plist EXISTS, so this host owns the
# job; only the reader is missing. Before the fix this fixture returned exit 0
# and the suite printed 12 passed while asserting nothing about any consumer.
mkfixture "$FIX/nolaunchctl.json" '
row = state("needs-scope")
row.pop("consumer_test", None)
row["liveness_check"] = {"kind": "launchd", "label": "com.kipi.fixture-job",
                         "run_evidence": "'"$FIX"'/ran", "max_age_s": 86400}
'
expect_red "a plist present with an unreadable launchd control binary fails closed" \
  "$FIX/nolaunchctl.json" "available to read its state" \
  "TERMINAL_STATES_LAUNCHD_DIR=$FIX/agents" \
  "TERMINAL_STATES_LAUNCHCTL=$FIX/no-such-launchctl-binary"

# --- 12. a non-string consumer must be named, not crash (finding-5) ----------
# Guards the REPORTING path, not just this row: the uncaught TypeError aborted
# before any RED: line, so this fixture must go red AND still name the row.
mkfixture "$FIX/badconsumer.json" 'state("needs-scope")["consumer"] = {"not": "a string"}'
expect_red "a non-string consumer is named, not an uncaught TypeError" \
  "$FIX/badconsumer.json" "consumer must be a string" \
  "TERMINAL_STATES_LAUNCHD_DIR=$FIX/agents" \
  "TERMINAL_STATES_LAUNCHCTL=$FIX/launchctl-loaded"

# --- 13. ASK-353: a consumer with no reentry pointer -------------------------
# A liveness_check proves the job RAN. This is the assertion that it re-enters
# THIS state, and it is the one the archived PRD's Reversal-2 tension turns on.
mkfixture "$FIX/noreentry.json" 'state("drift-cap").pop("reentry")'
expect_red "a consumer without a reentry pointer is refused" \
  "$FIX/noreentry.json" "not that the job"

# --- 14. ASK-353: a reentry pointer whose marker is NOT in the named file ----
# THE FICTION TEST. This is ci-redrive.py's false "it is also already handled"
# comment, reduced to a fixture: a named consumer that contains no selector for
# the state it claims to consume. It cost 29 hours and it must never be green.
mkfixture "$FIX/fakereentry.json" '
state("drift-cap")["reentry"] = {
    "path": "q-system/.q-system/scripts/review-redrive.py",
    "marker": "a selector that does not exist anywhere in this file"}
'
expect_red "a reentry marker absent from the named consumer is refused as fiction" \
  "$FIX/fakereentry.json" "claim with no code behind it"

mkfixture "$FIX/missingfile.json" '
state("drift-cap")["reentry"] = {"path": "q-system/.q-system/scripts/no-such-consumer.py",
                                 "marker": "anything"}
'
expect_red "a reentry pointer at a file that does not exist is refused" \
  "$FIX/missingfile.json" "which does not exist"

# --- 14b. REPRODUCER (codex PR #215, major): coverage may not narrow ---------
# The registry used to declare its own scope, so the way to make two of the three
# drivers stop being checked was to delete their `sources` entries and the rows
# that reference them -- a pure deletion, no marker moved, everything left over
# still valid. That is green on one driver: the ASK-353 defect, re-achieved by
# subtraction. This is the case that must be RED.
mkfixture "$FIX/dropsource.json" '
d["sources"] = [s for s in d["sources"] if s["id"] not in ("converge", "kipi-dispatch")]
d["states"] = [r for r in d["states"] if r["source"] not in ("converge", "kipi-dispatch")]
'
expect_red "REPRODUCER: dropping the converge + dispatch sources and their rows is REFUSED" \
  "$FIX/dropsource.json" "is a DRIVER of this loop and no"

# Dropping ONE is refused for the same reason, and the message NAMES the driver
# that went missing rather than reporting a generic count -- an operator reading
# this at 3am needs to know which one stopped being walked.
mkfixture "$FIX/dropone.json" '
d["sources"] = [s for s in d["sources"] if s["id"] != "kipi-dispatch"]
d["states"] = [r for r in d["states"] if r["source"] != "kipi-dispatch"]
'
expect_red "dropping a single driver is refused and the message names it" \
  "$FIX/dropone.json" "'kipi-dispatch' is a DRIVER"

# NEGATIVE SELF-TEST for the floor: it must not fire on a source REPOINTED to a
# copy. That is what every mutation fixture in this suite does, and it is the
# fable-discipline rule (verify against a copy, never the live driver) -- a floor
# that called it a missing driver would make the safe form of the test impossible
# and push the next author onto the live file.
mkfixture "$FIX/repointed.json" 'source("converge")["path"] = "'"$CVMUT"'"'
if python3 "$WORK/validate.py" "$FIX/repointed.json" "$ROOT" "$MAN" >/dev/null 2>&1; then
  bad "repointed-source fixture went green for the WRONG reason -- \$CVMUT carries a planted exit"
else
  if python3 "$WORK/validate.py" "$FIX/repointed.json" "$ROOT" "$MAN" 2>&1 | grep -q "is a DRIVER"; then
    bad "the coverage floor fires on a source repointed to a COPY -- it is path-literal, not identity-keyed"
  else
    ok "negative self-test: the floor does not fire on a source repointed to a copy"
  fi
fi

# THE PATHS ARE PINNED HERE, against the LIVE registry only. The floor inside the
# validator keys on ids so fixtures can repoint to copies; that leaves "keep the
# id, point it at an empty file" as the remaining way to declare a driver and walk
# nothing. This closes it, and it runs against the unmutated file so no fixture is
# affected.
for want in "q-system/.q-system/scripts/linear-worker.sh" \
            "q-system/.q-system/scripts/converge.sh" \
            "kipi-dispatch.sh"; do
  if python3 -c "
import json,sys
d=json.load(open('$REG'))
sys.exit(0 if any(s.get('path')=='$want' for s in d['sources']) else 1)"; then
    ok "coverage floor: the live registry declares $want as a driver"
  else
    bad "coverage floor: the live registry no longer declares $want -- its exits are unwalked"
  fi
done

# --- 15. ASK-353: owner:assaf may not be certified as a terminal state -------
# The founder's reversal, made deterministic. Refused by SHAPE (any row whose
# marker names the label) so re-adding the queue under a new row id is caught.
mkfixture "$FIX/founderqueue.json" '
row = state("owner-assaf")
row.pop("error_path"); row.pop("error_evidence")
row["terminal"] = True
'
expect_red "owner:assaf declared terminal is refused -- it is an error path now" \
  "$FIX/founderqueue.json" "not error_path:true"

mkfixture "$FIX/noerrorevidence.json" 'state("owner-assaf").pop("error_evidence")'
expect_red "error_path:true with no error_evidence is a label, not an error path" \
  "$FIX/noerrorevidence.json" "needs error_evidence"

# --- 16. ASK-353: the loud refusal must exist in the worker ------------------
# A copy of linear-worker.sh with the DEFECT line removed. If the code stops
# saying it out loud, the registry's error_path claim is fiction and this goes
# red -- the pointer is only worth something if its absence is caught.
WKMUT="$WORK/worker-no-defect-line.sh"
python3 - "$SRC" "$WKMUT" <<'EOF'
import sys
text = open(sys.argv[1], encoding="utf-8").read()
if "DEFECT: owner:assaf" not in text:
    raise SystemExit("FIXTURE FAILED: the worker no longer carries the DEFECT line")
open(sys.argv[2], "w", encoding="utf-8").write(text.replace("DEFECT: owner:assaf", "note"))
EOF
mkfixture "$FIX/nodefectline.json" '
state("owner-assaf")["error_evidence"]["path"] = "'"$WKMUT"'"
'
expect_red "removing the loud owner:assaf refusal from the worker is caught" \
  "$FIX/nodefectline.json" "claim with no code behind it"

echo
echo "== $PASS passed, $FAIL failed =="
[ "$FAIL" -eq 0 ] || exit 1
