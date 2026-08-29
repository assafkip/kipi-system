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
# `uncovered` must point at the ledger, not just sound sorry about itself.
SPILLOVER_REF = re.compile(r"\bsp-[0-9a-f]{8}\b")

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
# `trap '<body>' SIG`. Only the quoted forms: an unquoted `trap - EXIT` clears a
# trap and names no handler, and a bare `trap foo EXIT` is not a shape either file
# uses. The body is scanned for identifiers and intersected with the functions the
# file actually defines, so `trap 'rmdir "$D" || true' EXIT` (kipi-dispatch.sh:539)
# contributes nothing rather than inventing a handler called `rmdir`.
TRAP_LINE = re.compile(r"^\s*trap\s+(['\"])(.*?)\1")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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


def trap_handler_names(masked):
    """Functions a `trap` installs -- their exits have NO top-level call site.

    The exclusion of function bodies below rests on one claim: an exit inside a
    function is reached through a call site that is itself top-level, so the call
    site is where the dead end is counted. A signal handler breaks that claim,
    because its caller is the kernel delivering a signal and there is no line
    anywhere in the file that reaches it. converge.sh's `on_interrupt` exits
    143/130/129 and ends the whole run, and every check in this validator was
    blind to it (codex PR #215 round 3, minor).

    HONEST BOUNDARY: this names the handler ITSELF, not what the handler calls.
    `on_interrupt` calls `release_stale_claim_for_issue`, and an exit added inside
    THAT function is still invisible here. Closing it properly needs a call graph,
    which is a bigger change than this finding; the residual is captured in the
    spillover ledger rather than left implied by silence.
    """
    defined = {ln.split("(", 1)[0] for ln in masked
               if ln is not None and FUNC_OPEN.match(ln)}
    names = set()
    for ln in masked:
        if ln is None or ln.lstrip().startswith("#"):
            continue
        m = TRAP_LINE.match(ln)
        if m:
            names |= {t for t in IDENT.findall(m.group(2)) if t in defined}
    return names


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
    traps = trap_handler_names(masked)
    sites, infn, opened_at, fn = [], False, 0, None
    for i, ln in enumerate(masked):
        if ln is None:
            continue
        if not infn and FUNC_OPEN.match(ln):
            infn, opened_at, fn = True, i + 1, ln.split("(", 1)[0]
            continue
        if infn and FUNC_CLOSE.match(ln):
            infn, fn = False, None
            continue
        if is_comment(ln):
            continue
        # A trap handler's body IS top level for this purpose -- nothing calls it,
        # so there is no other line where its exit could be counted instead.
        if infn and fn not in traps:
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
        # LAST-WINS WAS A BYPASS FOR BOTH FLOORS (codex PR #215 round 3, major).
        # This map is keyed on the id, so a second entry reusing an id REPLACED the
        # file walked for it. The id floor above only asks whether the id appears,
        # and the shell-side path pin only asks whether the path appears -- one
        # entry can satisfy both while a different entry supplies the lines. That
        # declares converge.sh and enumerates something else, which is the ASK-353
        # one-driver blind spot reached by a third route. An id names exactly one
        # file or the registry does not say which file it names.
        if sid in src_lines:
            raise SystemExit(
                f"REGISTRY FAILED: source id {sid!r} is declared twice. The later entry "
                "silently replaces the file walked for that id, so a driver can be "
                "declared and never read. Give each source its own id.")
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
            # THE PROSE AND THE INSTRUMENTS MUST BE ABOUT THE SAME MACHINE
            # (codex PR #215 round 4, major). converge-verdict-terminal declared
            # consumer: "GitHub" while its liveness_check probed
            # com.kipi.dispatch and its reentry pointed inside converge.sh, the
            # driver that had just exited. Every field validated; not one of them
            # was about GitHub. The row read as certified and certified nothing.
            #
            # MEASURED BEFORE IT WAS WRITTEN, not assumed: run against the live
            # registry, 20 of the 21 consumer rows already satisfied this and the
            # single miss was that row. So this codifies the shape the registry
            # was already keeping, and takes an edit to this file -- visible in a
            # diff -- to loosen.
            #
            # Deliberately a SUBSTRING test on the basename or the label, not a
            # prose parse: the claim being checked is only that the sentence
            # names what is being probed. It cannot tell a right name in a wrong
            # sentence, and does not pretend to.
            reent = row.get("reentry") or {}
            live = row.get("liveness_check") or {}
            base = os.path.basename(reent.get("path") or "")
            label = live.get("label") or ""
            ctext = row["consumer"] if isinstance(row.get("consumer"), str) else ""
            if (base or label) and not ((base and base in ctext)
                                        or (label and label in ctext)):
                errors.append(
                    f"{rid}: consumer names neither the job it probes ({label!r}) nor "
                    f"the file its reentry marker lives in ({base!r}). A row whose "
                    "prose is about one machine and whose evidence is about another "
                    "is certified by instruments that cannot see the thing it claims "
                    "-- name the actual consumer, or say terminal:true.")
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
        # `uncovered` IS AN ADMISSION AND IT MUST NOT SIT INSIDE A CERTIFICATION
        # (codex PR #215 round 4, major). converge-verdict-terminal carried a
        # consumer, a liveness_check and a reentry pointer -- and an `uncovered`
        # note saying the stuck-green population has no consumer at all. NOTHING
        # READ THAT KEY. The row passed as covered while its own text said the
        # opposite, which is a worse state than an uncovered row: the gate now
        # reports green ABOUT the gap. A row either certifies that a machine
        # continues from here, or it does not.
        #
        # And an admission with no address is the pile, re-read
        # (no-orphan-findings.md), so it must carry its spillover id: the ledger
        # is what keeps `gates run` red until someone builds the consumer.
        unc = row.get("uncovered")
        if unc is not None:
            if not isinstance(unc, str) or len(unc.strip()) < 40:
                errors.append(f"{rid}: `uncovered` must be a written admission of what "
                              "this state does not cover, not a flag")
            elif not SPILLOVER_REF.search(unc):
                errors.append(f"{rid}: `uncovered` names no spillover id (sp-xxxxxxxx). "
                              "An admission nothing tracks is prose that decays into "
                              "the pile; the ledger is what keeps it red.")
            if has_consumer:
                errors.append(
                    f"{rid}: declares a consumer AND an `uncovered` admission. Those "
                    "contradict: the row certifies that a machine continues from here "
                    "while saying part of this population has nobody. Split the exit, "
                    "or drop the consumer and say terminal:true with the admission.")

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

# --- 6b-trap. A DEAD END REACHED ONLY BY A SIGNAL (codex PR #215 round 3) -----
# The enumerator skips function BODIES on the stated ground that an exit there is
# reached through a call site that is itself top-level, so counting both would
# double-count one dead end. A TRAP HANDLER has no such call site: the signal is
# the caller. converge.sh's `on_interrupt` ends the entire run (exit 143/130/129)
# and was invisible to every check in this file. Two cases, both against copies.
# A WHOLE NEW HANDLER, inserted high, not an extra line inside on_interrupt.
# Tucked inside the existing handler the planted exit sits under the dry-run
# marker 60 lines up and is caught by that row's sites count instead -- a real
# RED for a neighbouring row's reason, which would assert nothing about trap
# handling. Above every marker there is nothing to adopt it, so the claim under
# test is the one being made: a dead end reachable only by a signal is SEEN.
CVTRAP="$WORK/converge-trap-extra-exit.sh"
python3 - "$CONVERGE" "$CVTRAP" <<'EOF'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
for i, ln in enumerate(lines):
    if ln.startswith("set -"):
        lines[i + 1:i + 1] = ["on_bail_fixture() {",
                              "  exit 45",
                              "}",
                              "trap 'on_bail_fixture' USR1"]
        break
else:
    raise SystemExit("FIXTURE FAILED: converge.sh has no `set -` line to anchor to")
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines) + "\n")
EOF
mkfixture "$FIX/cvtrap.json" 'source("converge")["path"] = "'"$CVTRAP"'"'
expect_red "REPRODUCER: a dead end added to a TRAP handler is CAUGHT as UNREGISTERED" \
  "$FIX/cvtrap.json" "UNREGISTERED EXIT"

# NEGATIVE SELF-TEST. An ordinary function is still skipped. Without this the
# cheap fix -- count every exit everywhere -- would pass the case above and quietly
# double-count each of the nine converge exits that already have a top-level call
# site, turning every sites count in the registry red for a reason that is not a
# defect. `receipt_tree` is reached by an ordinary call, not by a trap.
CVFN="$WORK/converge-plain-fn-exit.sh"
python3 - "$CONVERGE" "$CVFN" <<'EOF'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
for i, ln in enumerate(lines):
    if ln.startswith("receipt_tree() {"):
        lines.insert(i + 1, '  if [ "$A_PLAIN_FN_DEAD_END" = "1" ]; then exit 46; fi')
        break
else:
    raise SystemExit("FIXTURE FAILED: converge.sh no longer defines receipt_tree()")
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines) + "\n")
EOF
mkfixture "$FIX/cvfn.json" 'source("converge")["path"] = "'"$CVFN"'"'
if python3 "$WORK/validate.py" "$FIX/cvfn.json" "$ROOT" "$MAN" >/dev/null 2>&1; then
  ok "negative self-test: an exit in an ordinary function body is still not a site"
else
  bad "an exit inside a NON-trap function is being enumerated -- top-level call sites are now double-counted"
fi

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

# --- 14c. REPRODUCER (codex PR #215 round 4, major): certified by the wrong ---
#          instrument.
# converge-verdict-terminal read consumer: "GitHub", liveness_check on
# com.kipi.dispatch, reentry inside converge.sh -- the driver that had just
# exited. Every field resolved and not one was about GitHub, so the row was
# certified by probing a job it did not name. That is the fiction check reached
# from the inside: the pointer exists, it is simply pointed somewhere else.
#
# `drift-cap` is a REAL consumer row and the mutation touches only the prose, so
# a green here would mean the prose is never read against the evidence at all.
mkfixture "$FIX/wrongmachine.json" '
state("drift-cap")["consumer"] = "GitHub -- it lands the PR once every check is green"
'
expect_red "a consumer naming neither the probed job nor the reentry file is refused" \
  "$FIX/wrongmachine.json" "certified by instruments that cannot see"

# NEGATIVE SELF-TEST for 14c. The rule must fire on the MISMATCH, not on any
# rewrite of the sentence -- a check that reddens whenever the prose changes is a
# spell-checker, and it would be switched off the first time someone reworded a
# consumer. Naming the probed job is enough, even with every other word replaced.
mkfixture "$FIX/rightmachine.json" '
state("drift-cap")["consumer"] = "com.kipi.dispatch re-offers it on the next cycle"
'
if python3 "$WORK/validate.py" "$FIX/rightmachine.json" "$ROOT" "$MAN" >/dev/null 2>&1; then
  ok "negative self-test: a reworded consumer that still names its probed job passes"
else
  bad "negative self-test: a reworded consumer that still names its probed job passes -- the rule is reddening on prose, not on the mismatch"
fi

# --- 14d. REPRODUCER (codex PR #215 round 4, major): an admission inside a ----
#          certification.
# The row carried `uncovered` -- "the stuck green state has NO consumer today" --
# next to a consumer, a liveness_check and a reentry pointer. Nothing read that
# key, so the gate reported green ABOUT the gap. Worse than an uncovered row.
mkfixture "$FIX/coveredbutnot.json" '
state("drift-cap")["uncovered"] = "the armed-and-green population has no consumer today; tracked open at sp-9b01682d"
'
expect_red "a row that declares a consumer AND an uncovered admission is refused" \
  "$FIX/coveredbutnot.json" "declares a consumer AND an .uncovered. admission"

# An admission with no address is the pile, re-read (no-orphan-findings.md).
mkfixture "$FIX/untrackedadmission.json" '
r = state("converge-verdict-terminal")
r["uncovered"] = "this population has no consumer today and nobody is tracking that fact anywhere at all"
'
expect_red "an uncovered admission naming no spillover id is refused" \
  "$FIX/untrackedadmission.json" "names no spillover id"

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

# --- 14c. REPRODUCER (codex PR #215 round 3, major): a SHADOWED source -------
# Both floors above ask "is this driver DECLARED", and neither asks "is it the
# entry that gets walked". `src_lines[sid] = read_lines(full)` is last-wins, so a
# second entry carrying an existing id replaces the first one's file. That is a
# way to declare converge.sh and enumerate something else: the id floor sees the
# id, the path floor sees the path on the shadowing entry, and the driver whose
# exits actually run is never read. This fixture puts the PLANTED-EXIT copy in the
# first entry -- the one whose RED the suite already proves at 6b -- and appends a
# clean duplicate behind it. Green here means the planted exit went unseen.
mkfixture "$FIX/dupsource.json" '
dup = json.loads(json.dumps(source("converge")))
source("converge")["path"] = "'"$CVMUT"'"
d["sources"].append(dup)
'
expect_red "REPRODUCER: a second entry shadowing an existing source id is REFUSED" \
  "$FIX/dupsource.json" "declared twice"

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
