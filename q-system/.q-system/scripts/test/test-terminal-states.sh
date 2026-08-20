#!/usr/bin/env bash
# NEVER LET THIS TEST REACH THE FOUNDER PHONE (ASK-729).
#
# This file passes $SRC (linear-worker.sh) to validate.py and to python mutation
# helpers as a FILE ARGUMENT; it never executes the worker, so today nothing here
# can page. That is a property of the current code, not a guarantee about the next
# edit: the worker is pager-capable, and the moment any assertion here decides to
# RUN it, an unstubbed run rings the founder actual phone at whatever hour the
# suite happens to fire.
#
# So the seam is stubbed once, up front, for the whole file rather than argued
# about per call site. The fable-discipline lint also reads $SRC being handed to
# python3 as "this test drives the runner" and blocks on it; this export answers
# that honestly instead of bypassing the gate with a skip marker, which would
# switch the check off for every future edit to this file too.
export KIPI_NOTIFY=/usr/bin/true

# test-terminal-states.sh -- the gate that stops a tenth dead end shipping.
#
# Pairs with q-system/.q-system/terminal-states.json (Piece B,
# prd-terminal-state-redrive-2026-08-01, issue terminal-states-validator).
#
# WHY THIS EXISTS. The Linear loop has ~9 abnormal exits. As of 2026-08-01
# exactly one has a working machine consumer. Every other exit either pages the
# founder or routes to nobody, and the founder does not read or work on code --
# so those are permanent parking lots. A hand-maintained registry was the v1
# design and was rejected (finding-4): it cannot detect an exit someone adds
# later. So the exits are enumerated FROM SOURCE at runtime and the registry is
# only allowed to explain them.
#
# THREE THINGS IT REFUSES TO CERTIFY:
#   1. An exit with no registry row (finding-4). Including one added directly
#      beneath an existing marker -- see the `sites` count below.
#   2. A consumer proven only by a file on disk (finding-14). A plist can exist
#      while the job is unloaded or dead, which is the exact silent-consumer
#      failure this PRD exists to prevent. Liveness means loaded AND a run
#      inside the interval.
#   3. A row whose only actor is the founder. He is not an available actor;
#      naming him is how a dead end gets dressed as a consumer.
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
"""Validate terminal-states.json against linear-worker.sh, enumerating from source.

argv: <registry.json> <linear-worker.sh> <capability-manifest.json>

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


def read_lines(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


def is_comment(line):
    s = line.lstrip()
    return s.startswith("#") or not s


def enumerate_sites(lines):
    """Every source site that removes an issue from the run, found at runtime.

    Three kinds, exactly as the issue spec names them:
      continue      each `continue` inside the issue loop
      ready-return  each `return` inside the ready() exclusion predicate
      label-apply   each REFUSE_LABEL assignment (the durable-queue labels)
    Returns [(1-based line, kind, text)].
    """
    sites = []

    # -- the issue loop ------------------------------------------------------
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
    for i in range(start + 1, end):
        if is_comment(lines[i]):
            continue
        if re.search(r"\bcontinue\b", lines[i]):
            sites.append((i + 1, "continue", lines[i].strip()))

    # -- ready() exclusion predicates ----------------------------------------
    rstart = None
    for i, ln in enumerate(lines):
        if re.match(r"^def ready\(i\):", ln):
            rstart = i
            break
    if rstart is None:
        raise SystemExit("ENUMERATION FAILED: no `def ready(i):` predicate in the source.")
    for i in range(rstart + 1, len(lines)):
        ln = lines[i]
        if ln.strip() and not ln.startswith((" ", "\t")):
            break  # dedent out of the function
        if is_comment(ln):
            continue
        if re.search(r"\breturn\b", ln):
            sites.append((i + 1, "ready-return", ln.strip()))

    # -- label applies -------------------------------------------------------
    for i, ln in enumerate(lines):
        if is_comment(ln):
            continue
        # A NON-EMPTY assignment. `REFUSE_LABEL=""` is the per-issue RESET at the
        # top of the refusal block, not a label being applied -- and it is the
        # very line the PRD's v1 mis-cited as a transition (":1297 resets
        # variables", finding-15). This validator reported it as an unregistered
        # exit on its first run, which is the same mistake from the other side.
        if re.search(r'REFUSE_LABEL="[^"]+"', ln):
            sites.append((i + 1, "label-apply", ln.strip()))

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
        if is_comment(lines[idx]):
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


def main():
    reg_path, src_path, man_path = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(reg_path, encoding="utf-8") as fh:
        registry = json.load(fh)
    lines = read_lines(src_path)
    rows = registry.get("states", [])
    errors = []

    declared_tests = set()
    if os.path.isfile(man_path):
        with open(man_path, encoding="utf-8") as fh:
            declared_tests = {e.get("path") for e in json.load(fh).get("expected_tests", [])}

    # -- schema ---------------------------------------------------------------
    seen_ids, seen_markers = set(), {}
    for row in rows:
        rid = row.get("id", "<no id>")
        if rid in seen_ids:
            errors.append(f"duplicate row id: {rid}")
        seen_ids.add(rid)

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
            if m in seen_markers:
                errors.append(f"{rid}: marker {m!r} is already used by {seen_markers[m]}")
            seen_markers[m] = rid

        if not isinstance(row.get("sites"), int) or row["sites"] < 1:
            errors.append(f"{rid}: `sites` must be a positive int (it is what makes an "
                          "exit added beneath an existing marker detectable)")

        has_consumer = bool(row.get("consumer"))
        is_terminal = row.get("terminal") is True
        if has_consumer == is_terminal:
            errors.append(f"{rid}: declare EITHER a consumer + liveness_check OR "
                          "terminal:true with a rationale, not both and not neither")
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
            ct = row.get("consumer_test")
            if ct and ct not in declared_tests:
                errors.append(f"{rid}: consumer_test {ct} is not in "
                              "capability-manifest.json expected_tests, so nothing "
                              "runs it -- the consumer is never proven to read this state")
        if is_terminal and len((row.get("rationale") or "").strip()) < 40:
            errors.append(f"{rid}: terminal:true needs a written rationale. An honest "
                          "dead end passes; an unexamined one does not")

    # -- enumeration ----------------------------------------------------------
    good_rows = [r for r in rows if r.get("_markers")]
    sites = enumerate_sites(lines)
    observed = {r["id"]: 0 for r in good_rows}
    debug = os.environ.get("TERMINAL_STATES_DEBUG") == "1"
    for line_no, kind, text in sites:
        row, tie = match_site(line_no, lines, good_rows)
        if debug:
            # The site table. A RED here is usually a marker claiming a site it
            # does not own, and reading that off the source by hand is the slow
            # way to find it.
            print(f"    site {line_no:>5} {kind:<13} -> "
                  f"{(row or {}).get('id', 'UNMATCHED')}   | {text[:70]}")
        if row is None:
            errors.append(
                f"UNREGISTERED EXIT at {os.path.basename(src_path)}:{line_no} ({kind})\n"
                f"      {text}\n"
                "      No registry row's marker appears above it. Add a row to "
                "terminal-states.json naming a consumer + liveness_check, or "
                "terminal:true with a rationale.")
            continue
        if tie:
            errors.append(f"AMBIGUOUS EXIT at {os.path.basename(src_path)}:{line_no}: "
                          "two markers tie for nearest. Make one more specific.")
            continue
        observed[row["id"]] += 1

    for row in good_rows:
        got, want = observed[row["id"]], row.get("sites")
        if isinstance(want, int) and got != want:
            if got == 0:
                errors.append(f"{row['id']}: marker(s) {row['_markers']!r} match NO "
                              "exit in the source. Stale row, or the marker moved.")
            else:
                errors.append(f"{row['id']}: covers {got} exit site(s), registry "
                              f"declares {want}. An exit was added or removed next to "
                              f"marker(s) {row['_markers']!r} -- reconcile the row.")

    print(f"    enumerated {len(sites)} exit site(s) from "
          f"{os.path.basename(src_path)}; {len(rows)} registry row(s)")
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
MAN="$ROOT/q-system/.q-system/capability-manifest.json"

for f in "$REG" "$SRC" "$MAN"; do
  if [ ! -f "$f" ]; then echo "RED: missing $f"; exit 1; fi
done

echo "== terminal-states validator =="

# --- 1. the real thing must be green ----------------------------------------
if python3 "$WORK/validate.py" "$REG" "$SRC" "$MAN"; then
  ok "live registry covers every enumerated exit in linear-worker.sh"
else
  bad "live registry does NOT validate against linear-worker.sh"
fi

# --- fixture plumbing --------------------------------------------------------
# Every negative test runs against COPIES. Nothing below reads or writes the
# live registry, the live source, or ~/.config/kipi -- the fable-discipline rule
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
exec(sys.argv[3])
json.dump(d, open(sys.argv[2], "w"), indent=2)
EOF
}

expect_red() {  # expect_red <name> <registry> <grep-pattern> [env...]
  local name="$1" reg="$2" pat="$3"; shift 3
  local out rc
  out="$(env "$@" python3 "$WORK/validate.py" "$reg" "$SRC" "$MAN" 2>&1)"; rc=$?
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
row = [r for r in d["states"] if r["id"] == "attempts-cap-stuck"][0]
row.pop("terminal", None); row.pop("rationale", None)
row["consumer"] = "the founder reviews the issue and decides what to do next"
row["liveness_check"] = {"kind": "launchd", "label": "com.kipi.fixture-job",
                         "run_evidence": "'"$FIX"'/ran", "max_age_s": 86400}
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
row = [r for r in d["states"] if r["id"] == "needs-scope"][0]
row["consumer_test"] = None; row.pop("consumer_test")
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
row = [r for r in d["states"] if r["id"] == "needs-scope"][0]
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

# --- 6. MUTATION: a tenth dead end added to the source -----------------------
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
out="$(python3 "$WORK/validate.py" "$REG" "$SRCMUT" "$MAN" 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "UNREGISTERED EXIT"; then
  ok "mutation: a tenth dead end added to the source is named as UNREGISTERED"
else
  bad "mutation: an added exit did NOT make the check red"
  printf '%s\n' "$out" | sed 's/^/        /'
fi

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
out="$(python3 "$WORK/validate.py" "$REG" "$SRCMUT2" "$MAN" 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "declares"; then
  ok "mutation: an exit INHERITING a nearby marker is caught by the sites count"
else
  bad "mutation: an exit added beneath an existing marker slipped through"
  printf '%s\n' "$out" | sed 's/^/        /'
fi

# --- 7. a line number is refused as identity (finding-15) --------------------
mkfixture "$FIX/lineno.json" '
[r for r in d["states"] if r["id"] == "attempts-cap-stuck"][0]["marker"] = "linear-worker.sh:680"
'
expect_red "a line-number marker is refused as row identity" \
  "$FIX/lineno.json" "is a LINE NUMBER"

# --- 8. terminal:true without a rationale is unexamined, not honest ----------
mkfixture "$FIX/norationale.json" '
[r for r in d["states"] if r["id"] == "out-of-repo"][0]["rationale"] = "n/a"
'
expect_red "terminal:true with no written rationale is refused" \
  "$FIX/norationale.json" "needs a written rationale"

# --- 9. a consumer with no liveness_check ------------------------------------
mkfixture "$FIX/noliveness.json" '
[r for r in d["states"] if r["id"] == "needs-scope"][0].pop("liveness_check")
'
expect_red "a consumer declared without a liveness_check is refused" \
  "$FIX/noliveness.json" "proves\s*$\|proves nothing ran"

# --- 10. a consumer_test nothing runs ----------------------------------------
mkfixture "$FIX/unregtest.json" '
[r for r in d["states"] if r["id"] == "needs-scope"][0]["consumer_test"] = \
    "q-system/.q-system/scripts/test/test-does-not-exist.sh"
'
expect_red "a consumer_test absent from capability-manifest.json is refused" \
  "$FIX/unregtest.json" "not in\s*$\|expected_tests"

# --- 11. plist present but launchctl unreadable (codex-adversarial finding-4) -
# The second fail-open, and the one the code's own comment already argued
# against while returning clean anyway. The plist EXISTS, so this host owns the
# job; only the reader is missing. Before the fix this fixture returned exit 0
# and the suite printed 12 passed while asserting nothing about any consumer.
mkfixture "$FIX/nolaunchctl.json" '
row = [r for r in d["states"] if r["id"] == "needs-scope"][0]
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
mkfixture "$FIX/badconsumer.json" '
row = [r for r in d["states"] if r["id"] == "needs-scope"][0]
row["consumer"] = {"not": "a string"}
'
expect_red "a non-string consumer is named, not an uncaught TypeError" \
  "$FIX/badconsumer.json" "consumer must be a string" \
  "TERMINAL_STATES_LAUNCHD_DIR=$FIX/agents" \
  "TERMINAL_STATES_LAUNCHCTL=$FIX/launchctl-loaded"

echo
echo "== $PASS passed, $FAIL failed =="
[ "$FAIL" -eq 0 ] || exit 1
