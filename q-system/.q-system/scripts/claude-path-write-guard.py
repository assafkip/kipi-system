#!/usr/bin/env python3
"""claude-path-write-guard.py -- Layer 1 of the .claude/ write protection (ASK-282).

PreToolUse hook on Bash. Blocks shell commands that would write inside a
`.claude/` tree.

SCOPE HONESTY, STATED UP FRONT:
This layer is COVERAGE, NOT A BOUNDARY. It reasons about a command string, and a
command string can always be obfuscated further than any parser follows. It is
here to stop the ordinary forms cheaply and early. The actual control is Layer 2
(claude-integrity-tripwire.py), which ignores commands entirely and checks
whether the CONTENT of the tree moved. If you are reading this while adding
"just one more pattern", stop: the answer to an evaded pattern is that Layer 2
already caught it, not that this list should grow.

WHY IT IS BUILT THIS WAY (scar, 2026-08-01, ASK-282):
Bash could write into `.claude/` while Write/Edit were refused there --
`touch .claude/_probe.txt` succeeded. The obvious fix, a denylist of dangerous
commands, is the exact defect class this repo hit six times in one file: matching
a phrase where the intent is a structure. A writer-denylist loses to touch, >,
>>, tee, cp, mv, install, rsync, sed -i, python -c open(w), `cd .claude && ...`,
a path in a variable, $HOME/.claude, a relative path from a subdirectory.

So the polarity is INVERTED. We do not enumerate writers. We enumerate READERS
and fail closed on everything else:

    a command that touches a .claude/ path is BLOCKED
    unless its program is on a small, stable read-only allowlist

Getting the reader list wrong yields a false BLOCK (loud, harmless, fixable).
Enumerating writers and getting it wrong yields a false ALLOW (silent, and the
gate was never real). A gate fails closed; a filter fails open.

Exit contract: 2 = block (stderr is fed back to Claude), 0 = allow.
"""

import json
import fnmatch
import os
import re
import shlex
import sys

# Programs with NO file-writing channel on ANY command line. That is the exact
# property this exemption asserts, and it is what the next person adding a name
# here has to establish -- not "this is usually used as a read".
#
# SCAR (review finding, round 10): the set used to say "programs that cannot
# write to a path they are given" while holding eight programs that can, and the
# file's answer for two of them was READER_WRITE_FLAGS -- an inner enumeration of
# the write FORMS of `sed` and `find`. That inner list is precisely the fail-open
# surface this file's header warns about. It knew `sed -i` and missed
# `sed 'w FILE'`; it knew `find -delete` and missed `find -fprint`; and it never
# covered `awk` at all, despite the comment above it naming "awk-into-a-file".
# Enumerating a program's write forms is out-guessing its manual forever.
# Enumerating programs with no write channel at all is a claim that can be
# checked once and stays checked, and a mistake in it is a false BLOCK.
#
# Dropped, each with the channel that disqualifies it:
#   awk, sed    a PROGRAM TEXT that writes -- see SCRIPT_ARG_INTERPRETERS
#   sort        -o FILE / --output=FILE
#   uniq, xxd   the SECOND positional argument is the output file
#   tree        -o FILE
#   yq          -i (in place)
#   find        -delete / -exec / -execdir / -ok / -fprint / -fls / -fprintf
#   less, more  `+'s FILE'` runs the pager's save command at startup
#
# test-claude-write-path.sh pins this exact membership, so a later addition is a
# reviewed decision and not a quiet one.
READ_ONLY = {
    "cat", "ls", "head", "tail", "grep", "egrep", "fgrep", "rg", "ag",
    "wc", "stat", "file", "diff", "cmp", "cut",
    "md5", "md5sum", "shasum", "sha256sum", "basename", "dirname", "realpath",
    "readlink", "test", "echo", "printf", "pwd", "which", "type", "du", "df",
    "jq", "column", "nl", "od",
}

# Programs whose first non-flag argument is a PROGRAM in another language rather
# than a path, and that write THROUGH that program text: awk's `system()`,
# `print > "f"` and `print | "cmd"`; sed's `w FILE`, `W FILE` and `s///w FILE`.
#
# This file already holds exactly this principle for python/perl/node -- "an
# interpreter carries its target INSIDE a code string, where component-wise path
# resolution cannot see it" (see SHELL_SINKS / INLINE_CODE_FLAGS below). awk and
# sed differ only in that their script is POSITIONAL, so no inline-code flag
# announces it; they were misfiled as readers because they default to printing.
#
# The verdict for these depends on ZERO awk/sed grammar, which is the point: a
# `.claude` mention anywhere in the STAGE is a block. Stage, not statement, so
# the escape hatch stays open -- pipe the file in and the interpreter's own stage
# names no path at all. See _stage(), the only reader.
SCRIPT_ARG_INTERPRETERS = {"awk", "gawk", "mawk", "nawk", "sed", "ed"}

# git subcommands that only read. Any other git subcommand touching .claude/ is
# treated as write-capable (checkout, restore, apply, clean, mv, rm...).
# `config` and `worktree` were here in rounds 1-2 and both WRITE:
#   git config -f .claude/settings.json user.x y   -> rewrites the file
#   git worktree add .claude/wt                    -> creates a tree inside it
# A subcommand is not read-only independent of its arguments (finding, round 3).
# Dropped rather than special-cased: their read forms on a .claude/ path are
# rare, and a false block is the safe direction here.
# `add` is here from ASK-291, and it is the one entry that writes ANYTHING: it
# writes the git INDEX. It cannot write the working tree, which is the only thing
# this guard protects. Measured live 2026-08-03, one command after the guards
# were armed through the sanctioned route:
#     BLOCKED: git add targets .claude/: .../.claude/settings.json
# So the founder could arm the guards and then never commit the arming. That is
# the acceptance criterion this issue carries in its own words -- a guard that
# blocks the legitimate path too is a different outage -- and it is how a gate
# gets switched off. `checkout`, `restore`, `stash` and `apply` stay OUT: those
# write the worktree, and probe_guard.py pins two of them blocked so nobody
# "completes the set" later by pattern-matching on the word read-only.
GIT_READ_ONLY = {
    "status", "log", "diff", "show", "ls-files", "ls-tree", "cat-file",
    "blame", "grep", "rev-parse", "describe", "shortlog", "hash-object",
    "branch", "remote", "count-objects", "check-ignore", "add",
}

# Piping into an interpreter re-enters the shell with content this parser never
# inspected. Treat as write-capable regardless of the visible program.
# Flags that hand an interpreter CODE on the command line rather than a script
# path. A sink carrying one of these is executing the text next to it, so a
# .claude/ mention there is a payload, not an argument to some other program.
INLINE_CODE_FLAGS = {"-c", "-e", "-E", "--command", "--eval", "-exec"}

SHELL_SINKS = {"bash", "sh", "zsh", "dash", "ksh", "eval", "source", "xargs",
               "python", "python3", "perl", "ruby", "node", "tee", "install"}

# The sanctioned write path. It carries its own additive-only vocabulary,
# enforcement ratchet and auto-revert (PR #63); Layer 1 defers to those guards
# rather than duplicating them. Naming a script cannot smuggle a payload -- the
# command still has to actually BE that script for this to matter.
SANCTIONED = ("apply-claude-changes.sh", "apply_claude_changes.py",
              "claude-integrity-tripwire.py", "kipi-update.sh")

# The same four programs, named a SECOND time for a DIFFERENT property: each one
# rewrites Layer 2's baseline (the tripwire directly; the other three by calling
# it once they have written). Being sanctioned to write and being able to erase
# the backstop are not the same claim -- a future entrypoint could be one without
# the other -- so the next person editing one list does not silently change the
# other. Read by _voids_layer2(), which matches these names against a stage's
# TEXT rather than its program position -- see the comment there for why the
# loose match is the safe direction in that one place.
REBASELINERS = SANCTIONED

# Layer 2's baseline, named here because Layer 1 is the only thing that can
# protect it. Every other piece of Layer 2's machinery is watched BY the
# baseline -- both guard scripts are in the tripwire's EXTRA_WATCHED, so
# deleting one lands as `removed` on the next tool call (round-2 scar). The
# baseline is the one piece that cannot watch itself, which is exactly why
# round 11's blocker went through it.
#
# Kept in sync with claude-integrity-tripwire.py's BASELINE_REL by a test, not
# by hope: two files disagreeing about where the baseline lives would silently
# turn this whole check off.
LAYER2_BASELINE_REL = os.path.join(
    "q-system", ".q-system", "claude-integrity-baseline.json")
LAYER2_BASELINE_NAME = os.path.basename(LAYER2_BASELINE_REL)

# Statement boundaries only. A single `|` is deliberately NOT a boundary: a
# pipeline is one unit of intent, and splitting it severs the path from the
# writer. `echo .claude/x | xargs touch` has the path in stage 1 and the writer
# in stage 2, and neither stage alone looks dangerous. Caught by its own test.
STATEMENT_OPS = ("&&", "||", ";", "\n")
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def split_outside_quotes(text, ops):
    """Split on `ops`, but never inside a quoted string.

    SCAR (ASK-291, measured live one command after the guards were armed): the
    splitters were quote-blind regexes. A multi-line quoted argument -- a git
    commit message DESCRIBING a .claude/ change, including the guard's own
    stderr, which begins ".claude/ wires every hook, rule and agent" -- was
    shredded into fake statements, and that line became a bare `.claude` token in
    program position:

        BLOCKED: git commit targets .claude/: /Users/.../ask-291/.claude

    So the guard blocked the commit of its own arming. A quoted string was never
    a separate statement; treating it as one invents commands nobody wrote, which
    is the phrase-versus-structure defect this file's header warns about.

    This does NOT weaken the guard: an operator inside quotes is data, not a
    boundary, so no real statement is merged away. `D=.claude; touch $D/x` still
    splits -- its `;` is unquoted -- and probe_guard.py pins that.
    """
    out, buf, quote, i, n = [], [], None, 0, len(text)
    while i < n:
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(ch)
            buf.append(text[i + 1])
            i += 2
            continue
        hit = next((op for op in ops if text.startswith(op, i)), None)
        if hit:
            out.append("".join(buf))
            buf = []
            i += len(hit)
            continue
        buf.append(ch)
        i += 1
    out.append("".join(buf))
    return out

# Gitignored scratch at the TOP of a `.claude/` tree. Layer 2
# (claude-integrity-tripwire.py) already refuses to watch these -- they churn
# constantly and carry no hook/rule/agent wiring -- so a path Layer 2 does not
# protect is not a path Layer 1 should block on. THIS SET MUST EQUAL LAYER 2's
# EXCLUDED_DIRS. The parity assertion lives in
# `q-system/.q-system/scripts/test/test-claude-write-path.sh`, case
# "L1 EXCLUDED_DIRS == L2 EXCLUDED_DIRS", because two layers disagreeing about
# what the protected set IS is worse than either bound alone. Rounds 1-4 named a
# test file that has never existed in this repo (review finding, round 5): a
# citation nobody can open is not a citation, it reads as coverage that is not
# there. The dead name is deliberately not repeated here -- a grep cannot tell a
# citation from a correction, so leaving it in leaves the finding standing.
#
# SCAR (sp-2b9372f6, measured 2026-08-02): without this, Layer 1 wedged any
# session whose cwd was `.claude/worktrees/<name>/`. `expand()` resolves every
# bare argv token against cwd, so in `git commit` the literal word `commit`
# became `<cwd>/commit`, "inside .claude", and BLOCKED. git commit / git push /
# gh pr create / running the tests all died. Two live registered worktrees sit
# under that path right now. A guard that stops the work it is guarding gets
# switched off, and a gate that is off protects nothing.
#
# This does NOT widen the write route: everything Layer 2 watches -- settings,
# rules/, agents/, skills/, commands/, output-styles/ -- is still protected, and
# `.claude/worktrees` itself (with nothing under it) stays protected too.
EXCLUDED_DIRS = {"state", "plans", "worktrees", "backups", "__pycache__"}

# Layer 2's EXCLUDED_FILES, mirrored. These sit at the TOP of `.claude/` and are
# protected positions -- but Layer 2 deliberately does not watch them, because
# they are gitignored and churn every session. `settings.local.json` carries
# `permissions`, so it is the single most security-relevant file on that list.
#
# THIS IS WHERE THE TWO-LAYER STORY BREAKS (review finding, round 5). Every
# NAMED GAP in this file is licensed by one sentence: "Layer 2 still catches it,
# because the file lands and the hash moves." For these files no hash moves --
# nothing is watching them. So Layer 1 walking past an unanchorable
# `$UNSET/.claude/settings.local.json` meant a permissions self-grant landed
# with NEITHER layer firing. Layer 1 therefore fails closed for exactly this
# set, and only this set: see _unanchored_unwatched().
#
# Pinned equal to Layer 2's copy by probe_round5_findings.sh phase 2, the same
# way EXCLUDED_DIRS is pinned: a compensating control that drifts out of sync
# with the thing it compensates for is worse than no control.
LAYER2_EXCLUDED_FILES = {"settings.local.json", ".DS_Store"}

# <root>/q-system/.q-system/scripts/this-file.py -> up 3. Matches the tripwire's
# default_root(): both layers answer for the same tree.
GUARD_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


def unquote(token):
    """Strip shell quoting before any path comparison.

    SCAR (review finding, round 3): the redirect target is captured by regex,
    not by shlex, so `echo pwned > ".claude/settings.json"` kept its quote
    characters. The first path component became `".claude` instead of `.claude`,
    the component test missed, and the write landed. That is comparing a
    REPRESENTATION instead of the thing -- the same root cause as matching a
    phrase where the intent is a structure.
    """
    t = token.strip()
    while len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        t = t[1:-1].strip()
    return t.replace('"', "").replace("'", "")


def _subst(token, assigns):
    """~, $HOME, ${HOME} and locally-assigned vars, WITHOUT anchoring to a cwd.
    A path held in a variable is still a path; a guard that only reads literals
    misses `D=.claude; touch $D/x`."""
    t = token
    for name, val in assigns.items():
        t = t.replace("${%s}" % name, val).replace("$" + name, val)
    home = os.path.expanduser("~")
    t = t.replace("${HOME}", home).replace("$HOME", home)
    if t.startswith("~"):
        t = os.path.expanduser(t)
    return t


def expand(token, cwd, assigns):
    """Substitute what we can, then anchor a relative result to `cwd`."""
    t = _subst(token, assigns)
    if not os.path.isabs(t):
        t = os.path.join(cwd, t)
    return os.path.normpath(t)


# Anything the shell will still expand once _subst() has done what it can.
#
# SCAR (review finding, PR #85 round 9, BLOCKER): this used to ENUMERATE the
# expansion shapes it knew -- `$(`, a backtick, `${?<letter>`. `${!V}` is `$`,
# `{`, `!`, so it matched none of them and the token was treated as ANCHORABLE.
# resolve() joined it to the cwd verbatim, producing the fabricated path
# `<cwd>/${!V}/rules/pwn.md`, which carries no `.claude` component -- so
# hits_claude() said no, literal_claude_tail() found nothing, and round 8's
# fail-closed branch (reachable only from `resolve() is None`) never ran. That is
# the round-3 scar again: comparing a REPRESENTATION instead of the thing.
#
# The fix is not one more shape. Enumerating shapes is open-ended -- `${V:-x}`,
# `${#V}`, `${V/a/b}`, `${A[0]}`, `$'..'`, `$((..))`, `$1`, `$@` are the same hole
# with different spelling, and probe_round9_findings.sh phase 2 measured six of
# them live. The ALPHABET is not open-ended: in the shell grammar every expansion
# is introduced by `$` or by a backtick, and by nothing else. So the test is on
# the alphabet. A token still carrying either character after substitution names
# something this parser cannot know, full stop.
#
# Deliberately NOT here: glob and brace metacharacters. They expand too, but
# widening THIS regex to cover them would send `touch .claude/rules/{a,b}.md` --
# a token whose `.claude` component is plainly visible and which is blocked
# outright today -- down the unanchorable path and into a mere handoff. Weaker,
# not stronger. They are handled where that weakening cannot apply: the
# no-backstop rule in _stage(). See NOT_A_LITERAL.
UNRESOLVED = re.compile(r"[$`]")

# Every metacharacter that makes a token something other than a plain literal
# path: the two expansion introducers above, plus glob and brace expansion.
# Read ONLY when the command re-baselines Layer 2 (see _stage), where "this
# parser cannot read the token" must mean block, because nothing is left
# downstream to catch whatever it turns out to name.
NOT_A_LITERAL = re.compile(r"[$`*?\[\]{}]")

# Sentinel cwd for "a `cd` went somewhere this parser cannot name". Never a real
# path, and deliberately carries no `.claude` component, so hits_claude() is
# False on it rather than accidentally true.
UNKNOWN_CWD = "\x00unknown-cwd"


def resolve(token, cwd, assigns):
    """The path a token refers to, or None when it CANNOT BE ANCHORED.

    SCAR (review finding, PR #85 round 2 -- and it blocked the reviewer's own
    first command of the review, verbatim): every token was joined against the
    session cwd whether or not its expansions had actually been resolved. So

        D=$(mktemp -d); mkdir -p "$D/.claude/rules"
        cd "$WORK" && mkdir -p .claude/agents

    were refused with a fabricated path -- `<session-cwd>/$(mktemp/.claude/rules`
    -- naming a `.claude/` that exists nowhere. Building a fixture tree in a temp
    dir is ordinary work, and this is the fourth false block of the same class in
    one issue. A guard that stops the work it guards gets switched off.

    NAMED GAP, not an oversight, and the same shape as the newline-token gap
    below: `touch $UNSET/.claude/settings.json` now walks past Layer 1 when the
    shell expands $UNSET to empty. Layer 2 still catches it -- the file lands and
    the hash moves -- which is exactly the division of labour this file's header
    describes.

    THE BOUND ON THAT CLAIM (review finding, round 5): it holds only for files
    Layer 2 actually watches. For `.claude/settings.local.json` -- gitignored,
    unwatched, and the file that carries `permissions` -- no hash moves, so a
    self-grant behind an unresolvable prefix fired NEITHER layer. Those tokens
    are now judged by their literal tail instead of waved through; see
    _unanchored_unwatched(). Everything else about this gap is unchanged. What is NOT traded away: anything this parser can actually resolve
    ($HOME, ~, a var it saw assigned, a literal) stays blocked, and
    probe_round3_findings.sh phase 4 pins all three of those.
    """
    if UNRESOLVED.search(_subst(token, assigns)):
        return None
    if cwd == UNKNOWN_CWD and not os.path.isabs(_subst(token, assigns)):
        return None
    return expand(token, cwd, assigns)


def protected_position(path):
    """True if the path sits at a PROTECTED position in some `.claude` tree,
    ignoring WHICH tree that is.

    Component-wise, so `my.claude-notes` and `claude/` do not false-positive.

    A path whose first component under `.claude/` is in EXCLUDED_DIRS is
    gitignored scratch: Layer 2 does not watch it, so Layer 1 does not block on
    it. The exclusion needs something UNDER the scratch dir -- `.claude/worktrees`
    itself is still a protected path, so `rm -rf .claude/worktrees` stays blocked
    while `touch .claude/worktrees/wt/scratch.txt` is allowed.

    Fails closed on ambiguity: with more than one `.claude` component, the path
    is protected if ANY of them resolves to a protected position.
    """
    parts = os.path.normpath(path).split(os.sep)
    for i, part in enumerate(parts):
        if part != ".claude":
            continue
        tail = parts[i + 1:]
        if len(tail) >= 2 and tail[0] in EXCLUDED_DIRS:
            continue  # scratch under this .claude -- unwatched by Layer 2
        return True
    return False


def _under(path, root):
    p = os.path.normpath(path)
    r = os.path.normpath(root).rstrip(os.sep)
    return p == r or p.startswith(r + os.sep)


def guarded_roots(session_cwd=None):
    """The trees whose `.claude/` this hook answers for.

    SCAR (review finding, round 5): the protected-position test had no
    project-root notion, so a `.claude` component ANYWHERE on the machine
    blocked the command -- a fixture tree in /tmp, an unrelated checkout, an
    archive being unpacked. This guard is a PROJECT hook; another tree's gates
    are that tree's business and its own Layer 2 owns them. False blocks on
    unrelated work are not free: four of them landed in ASK-291 alone, and a
    guard that stops ordinary work gets switched off.

    What stays in scope, deliberately:
      * GUARD_REPO_ROOT -- the repo whose hooks THIS script wires, even when the
        command runs from a cwd outside it.
      * the session cwd -- the tree the agent is actually working in.
      * $HOME -- this is where the round-5 finding named `~/.claude`, and where
        this fix does NOT follow it. `~/.claude/hooks/` holds
        destructive-op-deny.sh, the one gate an agent must never be able to
        edit, and $HOME also covers every other checkout and every registered
        worktree on this machine. Narrowing there would trade a false block for
        a real hole, which is the wrong direction for a gate.
    """
    roots = [GUARD_REPO_ROOT, os.path.expanduser("~")]
    if session_cwd and session_cwd != UNKNOWN_CWD:
        roots.append(os.path.abspath(session_cwd))
    return roots


def hits_claude(path, session_cwd=None):
    """True if `path` is a protected position in a tree this hook guards.

    `session_cwd=None` means no scope was supplied -> fail closed, exactly the
    pre-round-5 behaviour, so a caller that forgets the argument over-blocks
    rather than under-blocks.
    """
    if not protected_position(path):
        return False
    if session_cwd is None:
        return True
    return any(_under(path, root) for root in guarded_roots(session_cwd))


def literal_claude_tail(token, assigns):
    """The `.claude/...` suffix a token names LITERALLY, ignoring any prefix this
    parser cannot expand. None when the token names no `.claude` component.

    `$UNSET/.claude/settings.local.json` -> `.claude/settings.local.json`. The
    prefix is unknown; the tail is not, and the tail is what decides whether
    Layer 2 will ever see the write.
    """
    parts = unquote(_subst(token, assigns)).split("/")
    for i, part in enumerate(parts):
        if part == ".claude":
            return "/".join(parts[i:])
    return None


def unwatched_by_layer2(path):
    """A protected `.claude` position that Layer 2 refuses to watch -- the only
    place Layer 1 cannot hand off, so the only place it fails closed on a path
    it could not anchor. See LAYER2_EXCLUDED_FILES."""
    if not protected_position(path):
        return False
    return os.path.basename(os.path.normpath(path)) in LAYER2_EXCLUDED_FILES


def _unanchored_unwatched(args, cwd, assigns, layer2_blind=False):
    """Tokens this parser cannot anchor whose LITERAL tail names a `.claude/`
    file Layer 2 does not watch. Returned as ordinary touches, so the read-only
    allowlist, the git-subcommand rule and the sink rule all still apply.

    Narrow on purpose, twice over:

    * `mkdir -p "$D/.claude/rules"` in a temp fixture stays ALLOWED -- rules/ is
      watched, so the handoff to Layer 2 is real, and that is the false block
      that has already nearly killed this guard four times.
    * a token carrying a NEWLINE is skipped, same as the rule above. Those are
      text payloads (a commit message, a --body, a progress comment), and the
      first version of this function judged them as paths -- so a message that
      merely NAMED settings.local.json would have been refused as a write. It
      would have blocked the comment reporting this very fix. What that costs is
      the exotic `touch $'.claude/settings.local.json\ny'` shape, which stays
      inside the newline gap this file already names.
    """
    out = []
    for arg in args:
        if arg.startswith("-") or "\n" in arg:
            continue
        if resolve(arg, cwd, assigns) is not None:
            continue  # anchorable: judged as a real path elsewhere
        tail = literal_claude_tail(arg, assigns)
        if not tail:
            continue
        # Normally only the files Layer 2 refuses to watch fail closed here. When
        # the command re-baselines Layer 2, NO protected position has a backstop
        # left, so every one of them does (review finding, round 8).
        if unwatched_by_layer2(tail) or (layer2_blind and protected_position(tail)):
            out.append(tail)
    return out


HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def strip_heredocs(text):
    """Remove heredoc BODIES before the text is parsed as shell statements.

    SCAR (ASK-291, measured 2026-08-03, second false block in a row on the
    legitimate path): the quote-aware splitter fixed quoted arguments but a
    heredoc body is not quoted. `git commit -F - <<'MSG' ... MSG` describing this
    very change was shredded line by line into fake statements, and a prose line
    became a bare command with `.claude` in argument position:

        BLOCKED: 'run' would write inside .claude/: /Users/.../ask-291/.claude

    A heredoc body is stdin DATA, never commands. The delimiter line and the
    redirect itself stay in the text, so `cat <<EOF > .claude/settings.json` is
    still judged on its `> .claude/...` redirect -- what is dropped is only the
    payload between the delimiters. Pinned by two cases in probe_guard.py: a
    benign heredoc whose body mentions .claude/, and an ATTACK heredoc that
    redirects INTO .claude/.
    """
    out, pos = [], 0
    for start, end, delim, _quoted in _heredoc_openers(text):
        if start < pos:
            continue  # inside a body already consumed
        nl = text.find("\n", end)
        if nl == -1:
            continue  # no body in this payload; nothing to strip
        term = re.search(r"^[\t ]*%s[\t ]*$" % re.escape(delim),
                         text[nl + 1:], re.M)
        if term is None:
            # FAIL CLOSED. Round 2 set `body_end = len(text)` here, so an opener
            # whose delimiter never appears on its own line DISCARDED THE WHOLE
            # REST OF THE COMMAND before it was ever judged.
            continue
        out.append(text[pos:nl + 1])
        pos = nl + 1 + term.start()
    out.append(text[pos:])
    return "".join(out)


def _heredoc_openers(text):
    """(start, end, delimiter) for every `<<WORD` that is OUTSIDE quotes.

    SCAR (review finding, PR #85 round 2): `split_outside_quotes` was written
    quote-aware and `strip_heredocs`, added in the same commit, was not. A `<<`
    inside a quoted string read as a heredoc opener, its delimiter was never
    found on its own line, and the round-2 code then dropped everything after
    line 1:

        echo "diff a<<b"          ->  strip_heredocs leaves only this line
        touch .claude/evil.txt    ->  never judged at all, ALLOWED

    Layer 2 backstops writes to WATCHED files, but `.claude/settings.local.json`
    is in its EXCLUDED_FILES (the documented named gap), so Layer 1 was the only
    cover on a permissions self-grant and this removed it. The defect is not an
    unenumerated evasion shape -- it is the parser throwing away input it was
    asked to judge, which also hit benign work like
    `git commit -m "switch to <<EOF heredocs" && rm .claude/rules/stale.md`.

    Same state machine as split_outside_quotes. A quoted DELIMITER (`<<'EOF'`) is
    still an opener: the quotes there sit after the `<<`, so the scanner meets
    the `<<` outside any string.
    """
    out, quote, i, n = [], None, 0, len(text)
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        m = HEREDOC_RE.match(text, i)
        if m:
            out.append((m.start(), m.end(), m.group(2), bool(m.group(1))))
            i = m.end()
            continue
        i += 1
    return out


def _strip_inert_heredocs(text):
    """Drop the bodies of QUOTED-delimiter heredocs (`<<\'EOF\'`) only.

    The shell expands `$(...)` inside an unquoted-delimiter body and does not
    inside a quoted one, and extract_substitutions has to know the difference.
    Judge an inert body and this guard refuses prose that merely QUOTES an
    attack shape -- the false-block class that has already nearly killed it five
    times in this issue alone. Skip an expanding body and the substitution scan
    has a hole a heredoc walks straight through.

    An unterminated opener is NOT stripped: leaving it in risks a false block,
    dropping it risks a false allow, and this layer fails closed.
    """
    out, pos = [], 0
    for start, end, delim, quoted in _heredoc_openers(text):
        if start < pos or not quoted:
            continue
        nl = text.find("\n", end)
        if nl == -1:
            continue
        term = re.search(r"^[\t ]*%s[\t ]*$" % re.escape(delim),
                         text[nl + 1:], re.M)
        if term is None:
            continue
        out.append(text[pos:nl + 1])
        pos = nl + 1 + term.start()
    out.append(text[pos:])
    return "".join(out)


def _matching_paren(text, i):
    """Body and end-index of the `$(` whose contents start at `i`.

    Quote-aware and nesting-aware. Returns (None, len(text)) if it never closes.
    """
    depth, quote, n, start = 1, None, len(text), i
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    return None, n


PROC_SUB_OPENERS = ("<(", ">(")


def extract_substitutions(text):
    """Every command body the shell RUNS before the visible program is exec'd.

    `$(...)` and backticks, and the PROC_SUB_OPENERS process substitutions
    `<(...)` / `>(...)`. Nested bodies come back flat so one pass judges all of
    them.

    The two families do not share quoting rules, which is why they are separate
    branches rather than one wider match. Measured with bash itself, not assumed:

        bash -c 'echo "$(touch x)"'     -> runs, x created
        bash -c 'echo "<(touch x)"'     -> prints the text, nothing created
        bash -c 'echo <(touch x)'       -> runs
        bash -c 'echo<(touch x)'        -> runs (adjacency is not required)

    So `$(` stays live inside double quotes and a process substitution does not.
    Judging an inert body is the false-block class this issue has already hit
    five times -- it would refuse the very comment reporting this fix.

    WHY THIS EXISTS (review finding, PR #85 round 6, BLOCKER): `_is_sanctioned`
    matches on argv[0]/argv[1] and `_stage` then returns `ok` without looking at
    a single argument. So

        bash apply-claude-changes.sh "$(touch .claude/evil.txt)"

    walked past Layer 1 untouched -- and past Layer 2 as well, because the shell
    expands BEFORE it execs: the substitution mutates the tree, and then the
    sanctioned tool's own re-baseline records the mutation as the trusted state.
    One Bash call, both layers defeated, no alarm. Measured in
    probe_round6_findings.sh phase 2 before the fix: `.claude/rules/r.md`
    rewritten, `--check` answering `clean: 2 file(s) match baseline`.

    A substitution is a COMMAND, not an argument, so it is judged as one. That
    is also why this runs in `analyse` ahead of everything rather than as one
    more special case inside `_stage`: an exemption handed to the outer program
    must not be reachable from inside it, and every future exemption added to
    `_stage` inherits that property for free instead of re-opening this hole.

    Only the `>` shapes were ever covered here, and by accident: the redirect
    scan happens to run before the sanctioned early-return, which is why the
    first probe cases written for this finding passed against the broken guard
    and had to be rewritten redirect-free to mean anything.

    NAMED GAP: a body is judged against the SESSION cwd, so the substitution in
    `cd /tmp && bash apply.sh "$(touch .claude/x)"` is judged as if it ran at the
    session cwd. That direction is a false BLOCK, never a false allow, and
    threading expansion-order cwd through the parser is more than this layer's
    stated scope (COVERAGE, NOT A BOUNDARY) is meant to carry.
    """
    text = _strip_inert_heredocs(text)
    out, quote, i, n = [], None, 0, len(text)
    while i < n:
        ch = text[i]
        if quote == "'":
            if ch == "'":
                quote = None
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            i += 2                      # `\$(` and a backslashed backtick are literal
            continue
        if quote == '"':
            if ch == '"':
                quote = None
                i += 1
                continue
            # `$(` and backticks stay LIVE inside double quotes -- fall through.
        elif ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if quote is None and any(text.startswith(op, i) for op in PROC_SUB_OPENERS):
            # SCAR (review finding, PR #85 round 7, BLOCKER): round 6 closed this
            # hole for `$(...)` and stopped there, so
            #
            #     bash apply-claude-changes.sh <(touch .claude/evil.txt)
            #
            # still walked past `_is_sanctioned` -> `_stage` returns `ok` without
            # reading an argument -- and past Layer 2 as well, because the body
            # runs BEFORE the exec and the sanctioned tool then baselines the
            # mutation as trusted. Measured in probe_round7_findings.sh phase 2
            # against the pre-fix guard: `.claude/rules/r.md` overwritten,
            # `--check` answering `clean: 2 file(s) match baseline`.
            #
            # The redirect scan does NOT cover the `>(` shape despite looking
            # like it should: its target class `[^\s;&|<>]+` refuses the `>` that
            # opens the substitution, so `cmd > >(rm .claude/x)` captures `(rm`
            # and resolves to nothing.
            #
            # NAMED OVER-EXTRACTION, not a defect: `$((3>(1)))` is arithmetic,
            # and the `$(` branch below hands its body `(3>(1))` back to this
            # scan, which reads `>(` as an opener and returns `1`. That body is
            # judged as the statement `1` -- no program, no path, no block. The
            # alternative is an arithmetic-context tracker, which buys nothing.
            body, end = _matching_paren(text, i + 2)
            if body is None:
                out.append(text[i + 2:])   # fail closed, same as `$(` below
                return out
            out.append(body)
            out.extend(extract_substitutions(body))
            i = end
            continue
        if text.startswith("$(", i):
            body, end = _matching_paren(text, i + 2)
            if body is None:
                # FAIL CLOSED: an opener with no closer hands its tail over to
                # be judged anyway. Round 2's heredoc code dropped an
                # unterminated tail instead, and dropped a real write with it.
                out.append(text[i + 2:])
                return out
            out.append(body)
            out.extend(extract_substitutions(body))
            i = end
            continue
        if ch == "`":
            j = text.find("`", i + 1)
            if j == -1:
                out.append(text[i + 1:])
                return out
            out.append(text[i + 1:j])
            out.extend(extract_substitutions(text[i + 1:j]))
            i = j + 1
            continue
        i += 1
    return out


def analyse(command, cwd):
    """Return a blocking reason, or None.

    Substitutions -- command AND process -- are judged FIRST and on their own
    terms, because the shell runs them first and because no exemption granted to
    the outer program, the sanctioned-entrypoint one above all, can reach inside
    them.
    """
    # Computed ONCE over the whole command, never per body: a substitution body
    # names no sanctioned program of its own, so a per-body flag would read False
    # for `<tripwire> --register x <(touch $UNSET/.claude/rules/pwn.md)`.
    blind = _voids_layer2(command, cwd)
    for body in extract_substitutions(command):
        reason = _analyse_statements(body, cwd, blind)
        if reason:
            return "shell substitution %s" % reason
    return _analyse_statements(command, cwd, blind)


def _analyse_statements(command, cwd, layer2_blind=False):
    """The statement-and-stage walk over one command string.

    `layer2_blind` is True when this command also re-baselines Layer 2, which
    voids every handoff to it. See _voids_layer2()."""
    assigns = {}
    effective_cwd = cwd
    command = strip_heredocs(command)

    for raw_stmt in split_outside_quotes(command, STATEMENT_OPS):
        stmt = raw_stmt.strip()
        if not stmt:
            continue

        # Stages split quote-aware too: a `|` inside a quoted message ("reverted
        # 1 | quarantined at ...") used to cut the argument in half, leaving a
        # fragment with an unbalanced quote that shlex refused, falling back to a
        # whitespace split that handed `.claude/...` back as a bare token.
        stages = [s.strip() for s in split_outside_quotes(stmt, ("|",)) if s.strip()]

        # Pipeline judged whole: any stage that re-enters an interpreter turns
        # a .claude/ path anywhere in the statement into a write.
        # Same program-position rule as _is_sanctioned: a mention of a
        # sanctioned script must never disarm a pipeline (review finding, r2).
        if ".claude" in stmt and not any(_is_sanctioned(s.split()) for s in stages):
            for idx, stage in enumerate(stages):
                head = stage.split()
                if not head or os.path.basename(head[0]) not in SHELL_SINKS:
                    continue
                # The rule is what its message says: the interpreter must be
                # RECEIVING the .claude/ text, as piped stdin or as inline code.
                #
                # SCAR (2026-08-03, third false block in a row on the legitimate
                # path -- it refused the `prd_runner.py spillover add` that was
                # capturing findings from this same review): `idx` was not
                # checked, so ANY `python3 some-script.py --arg "...text
                # mentioning .claude/..."` was read as an interpreter being fed a
                # path. The interpreter was the FIRST stage; nothing was piped
                # into it and the mention was a script argument, not code.
                #
                # Both attack shapes survive: `python3 -c "open('.claude/x','w')"`
                # carries an inline-code flag, and `echo .claude/x | xargs touch`
                # puts the sink at idx > 0. probe_guard.py pins all three.
                if idx > 0 or any(t in INLINE_CODE_FLAGS for t in head[1:]):
                    return "pipeline feeds a .claude/ path into %r" % os.path.basename(head[0])

        for seg in stages:
            reason = _stage(seg, assigns, [effective_cwd], cwd, layer2_blind)
            if isinstance(reason, str):
                return reason
            effective_cwd = reason[0]

    return None


def _flag_values(token):
    """The path candidates hiding inside a flag token (review finding, round 10).

    A flag is not a path, which is why `_stage()` skips `-`-leading tokens. But a
    value ATTACHES to a flag two ways and only two ways, so this needs no table
    of which flags take a path:

        --output=.claude/x   the part after the first `=`
        -o.claude/x          the dash-stripped token minus its flag letter

    Both candidates go through the same resolve()/hits_claude() as any other
    token, so an unrelated tree's `.claude/` stays out of scope
    (`--output=/tmp/other/.claude/x` is still allowed; the round-5 pin holds).
    Ordinary flags yield harmless garbage: `-rn` gives `rn` and `n`, neither of
    which resolves anywhere near `.claude`.
    """
    body = token.lstrip("-")
    if "=" in token:
        return [token.split("=", 1)[1]]
    return [body, body[1:]] if body else []


def _is_sanctioned(tokens):
    """True only if the command actually EXECUTES a sanctioned entrypoint.

    Round 1 tested `any(s in seg for s in SANCTIONED)` -- a substring match on
    the raw segment. That meant any command merely CONTAINING the text
    "kipi-update.sh", including inside a quoted string or a trailing comment,
    disabled Layer 1 for that statement:

        touch .claude/evil.txt  # kipi-update.sh

    Which is the phrase-versus-structure defect this guard's own header warns
    about, committed inside the guard. Caught in review, round 2. The check now
    looks at the PROGRAM POSITION only: argv[0], plus argv[1] when argv[0] is an
    interpreter, since `bash apply-claude-changes.sh ...` is the normal form.
    """
    return any(c in SANCTIONED for c in _program_names(tokens))


# `env`'s two options whose value is a SEPARATE token. Deliberately short: an
# option this tuple does not know costs one skipped token, and the only thing
# downstream of a miss here is a false block on the sanctioned route.
ENV_SEPARATE_VALUE_OPTS = ("-u", "--unset", "-C", "--chdir")


def _env_split_string(tok, tokens, i):
    """`env -S "python3 x --baseline"` hides an entire command line inside ONE
    token. Returns that line's tokens, or None when this is not that option."""
    if tok in ("-S", "--split-string"):
        value = tokens[i + 1] if i + 1 < len(tokens) else ""
    elif tok.startswith("--split-string="):
        value = tok.split("=", 1)[1]
    elif tok.startswith("-S") and len(tok) > 2:
        value = tok[2:]
    else:
        return None
    try:
        return shlex.split(value)
    except ValueError:
        return value.split()


def _strip_one_prefix(tokens):
    """Remove ONE layer of what stands between the shell and the executable: the
    leading `NAME=value` assignments, plus one `env` and its own arguments.
    Returns the shorter list, or None when there was nothing to strip -- which is
    how _exec_position() terminates."""
    i = 0
    while i < len(tokens) and ASSIGN.match(tokens[i]):
        i += 1
    if i >= len(tokens) or os.path.basename(tokens[i]) != "env":
        return tokens[i:] if i else None
    i += 1
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--":
            return tokens[i + 1:]
        if ASSIGN.match(tok):
            i += 1
        elif not tok.startswith("-"):
            break
        elif tok in ENV_SEPARATE_VALUE_OPTS:
            i += 2
        else:
            inner = _env_split_string(tok, tokens, i)
            if inner is not None:
                return inner
            i += 1
    return tokens[i:]


def _exec_position(tokens):
    """The tokens from the EXECUTABLE onward.

    SCAR (review finding, PR #85 round 13, BLOCKER). `_program_names` read argv[0]
    literally, so in

        touch $UNSET/.claude/rules/pwn.md; KIPI_NOTIFY=/usr/bin/true python3 <tripwire> --baseline

    the program was `KIPI_NOTIFY=/usr/bin/true`, whose basename is `true` -- not an
    interpreter, so argv[1] was never consulted either. Measured by the reviewer:
    voids_layer2=False, trusted_sha=pwned, next_enforce_rc=0. `_stage()` has
    stripped these tokens since round 2; this function never did, and one file
    holding two answers to "what is argv[0]" is the drift `_program_names` was
    factored out to prevent.

    It also shuts a hole nobody had named: `os.path.basename` of an assignment
    reads its VALUE, so `FOO=path/to/apply-claude-changes.sh <write>` reported
    SANCTIONED and disarmed the pipeline rule at _analyse_statements, which passes
    RAW tokens. Pinned as a non-sanction, probe_round13 phase 5.

    WRAPPER PROGRAMS (`nice`, `timeout`, `command`, `nohup`, `stdbuf`) are
    deliberately NOT stripped here. Each carries its own operand grammar --
    `timeout`'s duration is neither an option nor an assignment -- and a table of
    which flags take a value is the fail-open surface round 10 deleted one for.
    They are covered where a miss is actually a hole: _voids_layer2 names the
    rebaseliners with no grammar at all. Missing one HERE can only cost a false
    block on the sanctioned route, which is the safe direction to be wrong in.
    """
    for _ in range(8):  # bounded: `env env env ...` must not loop forever
        stripped = _strip_one_prefix(tokens)
        if stripped is None:
            return tokens
        tokens = stripped
    return tokens


def _program_names(tokens):
    """The basenames a segment could be EXECUTING: argv[0] once the assignment and
    `env` prefix is off it, plus argv[1] when argv[0] is an interpreter, since
    `bash apply-claude-changes.sh ...` is the normal form.

    ONE CALLER NOW: `_is_sanctioned`, which GRANTS an exemption. Round 1 shipped a
    substring match here and it took a review to catch, because in this direction
    matching loose text is fail-OPEN. `_voids_layer2` used to share this function
    and no longer does -- it withdraws a handoff rather than granting anything, so
    loose text there is fail-CLOSED and it names the rebaseliners directly
    (round 13). Two callers with opposite failure directions were never really
    asking one question; pretending they were is what let an `env` prefix pass.
    """
    tokens = _exec_position(tokens)
    if not tokens:
        return []
    cands = [os.path.basename(tokens[0])]
    if cands[0] in ("bash", "sh", "zsh", "python", "python3") and len(tokens) > 1:
        for t in tokens[1:]:
            if not t.startswith("-"):
                cands.append(os.path.basename(t))
                break
    return cands


def _could_name_baseline(token, cwd, assigns):
    """True if `token` could name Layer 2's baseline file.

    NOT a check for a writer. The question is reach: if this command can NAME
    the baseline, Layer 1 cannot promise the baseline still exists when the
    PostToolUse hook fires, and every handoff that depends on it is void.

    ASKED COMPONENT-WISE, because that is what a path is. Pass 1 bounded a glob
    by its flat literal prefix and `.$P/settings.json` produced the prefix "."
    -- which anchors to cwd, and every relative path starts with cwd. That made
    the check fire on nearly everything, and the permanent suite caught it: case
    D1 is PINNED as a Layer 1 MISS (it is the proof Layer 2 is load-bearing), and
    it started blocking. A shell glob does not cross `/`; `*` matches within ONE
    component. So:

      - the token is rebased onto each GUARDED ROOT, never onto the cwd, because
        `LAYER2_BASELINE_REL` is root-relative and comparing it against a
        cwd-relative path silently switched this whole check off for every
        session below the root (round 12 BLOCKER),
      - a component holding an EXPANSION (`$`, backtick, brace) could be any
        single component. Unknowable, so it does not veto -- it is skipped,
      - a component holding a GLOB is fnmatch-ed against the baseline's
        component at that position. Precise, no filesystem access, no guessing,
      - a LITERAL component must be equal, and
      - FEWER components than the baseline means a CONTAINING DIRECTORY, so
        `rm -rf q-system` reaches the baseline and is treated as such. MORE
        components names something strictly deeper, which the baseline is not.

    A token that is ENTIRELY expansions reaches NOTHING: it agrees with no
    component, so there is no evidence it names the baseline, and returning True
    on zero evidence is what made pass 2 block an awk program text. That is the
    named bound of this whole check -- `rm -f "${!V}"` is not caught here -- and
    Layer 2's armed marker is what covers it. It is also what keeps the round-8/9
    handoff alive: the unanchorable `.claude` write is itself such a token, and
    blocking on it would collapse every handoff and delete the handoff."""
    raw = _subst(unquote(token), assigns)
    if not raw or raw.startswith("-"):
        return False
    known_cwd = bool(cwd) and cwd != UNKNOWN_CWD
    # HOW MANY COMPONENTS THE TOKEN ITSELF SUPPLIED (review finding, round 12).
    # `..` consumes a cwd component instead of adding one, so the token's own
    # components are always the LAST `own` of the rebased path. An absolute token
    # supplied all of them; so does a relative token read with no cwd, which is
    # read as root-relative. `_agrees` is where this count earns its keep.
    own = None
    if not os.path.isabs(raw) and known_cwd:
        own = len([p for p in os.path.normpath(raw).split(os.sep)
                   if p not in ("", ".", "..")])
    base_parts = [p for p in LAYER2_BASELINE_REL.split(os.sep) if p not in ("", ".")]
    for root in guarded_roots(cwd if known_cwd else None):
        if os.path.isabs(raw):
            full = os.path.normpath(raw)
        elif known_cwd:
            full = os.path.normpath(os.path.join(cwd, raw))
        else:
            full = os.path.normpath(os.path.join(root, raw))
        parts = [p for p in os.path.relpath(full, root).split(os.sep)
                 if p not in ("", ".")]
        if not parts or parts[0] == ".." or len(parts) > len(base_parts):
            continue  # above this root, or strictly deeper than the baseline
        first_own = 0 if own is None else max(0, len(parts) - own)
        if _agrees(parts, base_parts, first_own):
            return True
    return False


def _agrees(parts, base_parts, first_own):
    """Component-wise agreement between a ROOT-REBASED token and the baseline.

    REACH REQUIRES EVIDENCE. An unknowable component (an expansion, a brace)
    cannot veto -- it really could be anything -- but it cannot AGREE either.
    Round 11 pass 2 let a token made entirely of unknowable components fall out
    of this loop having compared nothing and return True, which blocked
    `{print $1}` (an awk program text) as though it named the baseline.

    `first_own` is where the TOKEN's own components start; anything before it came
    from the cwd the token was rebased against. Those still have to MATCH -- a cwd
    that is not on the baseline's path means nothing under it can reach the
    baseline by a relative name -- but they are NOT evidence, because the token
    did not supply them. Counting them is round 11 pass 2's defect arriving
    through a new door: from `<root>/q-system` the padded path of `{print $1}` is
    `q-system/{print $1}`, whose first component agrees with the baseline's
    perfectly and was written by nobody."""
    evidence = 0
    for i, (got, want) in enumerate(zip(parts, base_parts)):
        if UNRESOLVED.search(got) or "{" in got or "}" in got:
            continue
        if NOT_A_LITERAL.search(got):
            if not fnmatch.fnmatchcase(want, got):
                return False
        elif got != want:
            return False
        if i >= first_own:
            evidence += 1
    return evidence > 0


def _voids_layer2(command, cwd=None):
    """True if ANY stage of this command could leave Layer 2 unable to catch
    what Layer 1 is handing off to it -- by REWRITING its baseline (round 8) or
    by REACHING the baseline file at all (round 11).

    WHY THIS EXISTS (review finding, PR #85 round 8, BLOCKER). Layer 1 hands an
    UNANCHORABLE `.claude/` write to Layer 2 -- `resolve()` returns None, the
    named gap this file already documents -- on the explicit ground that the file
    lands and the hash moves, so the tripwire reverts it. That ground is a claim
    about what happens AFTER this tool call. A sanctioned re-baseline in the SAME
    call falsifies it:

        touch $UNSET/.claude/rules/pwn.md; <tripwire> --register .claude/rules/pwn.md

    The shell runs both before any PostToolUse hook fires, `--register` records
    the tampered file as the trusted state, and the tripwire that was supposed to
    be the backstop reports clean. Measured against the pre-fix guard by Codex
    and by probe_round8_findings.sh phase 1: rc=0, six shapes through.

    It is round 6 and round 7's hole a third time -- an exemption granted to one
    program reaching work it was never granted for -- but it needs no
    substitution at all, so the extractor could never have caught it. The
    exemption that matters here is not `_is_sanctioned` returning `ok` for a
    statement; it is the HANDOFF taken by a DIFFERENT statement whose backstop
    the sanctioned one erases.

    ORDER-INDEPENDENT on purpose. `;` is linear but `&&`, `||`, subshells and
    background jobs are not, and a parser that decides which side of a `;` runs
    first is a new failure surface guarding a hole it may get wrong. Blocking
    both orders costs one tool call and mis-ordering costs the gate.

    THE ESCAPE HATCH, and why the false-block cost is affordable: split the
    command into TWO Bash calls. Layer 2 then runs BETWEEN them, which is exactly
    the property the handoff assumed. probe_round8_findings.sh phase 3 pins the
    one real false block this buys (a temp fixture tree built in the same command
    as a re-baseline) rather than pretending the fix is free.

    Substitution bodies are searched too: `--register` hidden in a `<(...)` still
    erases the baseline.

    ROUND 11 (BLOCKER): the same handoff is voided by DELETING the baseline, and
    the program test could never see it -- `rm` is not a sanctioned applier, and
    the baseline lives OUTSIDE `.claude/` so no `.claude` component appears in
    the delete. Measured, 9 shapes at rc=0 (probe_round11_findings.sh phases
    1-2): rm, mv, `: >`, `echo >`, a variable holding the path, a basename glob,
    a process substitution, `python3 -c "os.remove(...)"`, and an absolute path.

    THE VERB IS NOT THE QUESTION. Enumerating what can unlink a file is the
    fail-open surface this file's header warns about and round 10 deleted a
    whole table for. Both new tests are about the PATH:

      - the baseline's FILENAME appearing in a stage's text. Zero grammar, so
        `rm`, `mv`, a redirect and an interpreter code string all fall to it
        identically -- each one has to NAME the file.
      - a TOKEN that could name the baseline (_could_name_baseline), which
        bounds globs by their literal prefix and catches `rm -rf q-system` by
        directory containment.

    THE COST IS THE SAME ONE ROUND 8 PRICED, and it is only ever charged
    alongside an unanchorable `.claude/` write: mentioning the baseline in such
    a command blocks. The escape hatch is unchanged and free -- two Bash calls,
    between which Layer 2 runs and re-arms on the clean tree, which is exactly
    what the handoff assumes. Reading or deleting the baseline in a command with
    NO unanchorable `.claude/` write is untouched, pinned as allows in phase 3.
    """
    cwd = cwd or os.getcwd()
    for text in [command] + extract_substitutions(command):
        for stmt in split_outside_quotes(strip_heredocs(text), STATEMENT_OPS):
            for stage in split_outside_quotes(stmt, ("|",)):
                if LAYER2_BASELINE_NAME in stage:
                    return True
                # THE NAME, NOT THE POSITION (review finding, round 13 BLOCKER).
                # This used to ask `_program_names` whether a rebaseliner sat in
                # the program position, and an environment assignment in front of
                # it answered no. Fixing the parser fixes that ONE spelling; the
                # next one is `nice`, then `timeout 20`, then `command`, then
                # `nohup`, each with its own operand grammar to get right.
                #
                # So this test now has no grammar at all, exactly like the
                # baseline-filename test one line above (round 11). The direction
                # of failure is why that is safe HERE and was round 2's blocker in
                # `_is_sanctioned`: matching text there GRANTS an exemption
                # (fail-open); matching text here WITHDRAWS a handoff
                # (fail-closed). Same rule, opposite consequence.
                #
                # The cost is the one round 8 priced and round 11 already charged:
                # naming one of these four files in a command that ALSO makes an
                # unanchorable `.claude/` write blocks. The escape hatch is
                # unchanged and free -- two Bash calls, with Layer 2 in between.
                if any(name in stage for name in REBASELINERS):
                    return True
                try:
                    tokens = shlex.split(stage, comments=True)
                except ValueError:
                    tokens = stage.split()
                assigns = dict(a.groups() for a in
                               (ASSIGN.match(t) for t in tokens) if a)
                if any(_could_name_baseline(t, cwd, assigns) for t in tokens):
                    return True
    return False


def _stage(seg, assigns, cwd_box, session_cwd=None, layer2_blind=False):
    """One pipeline stage. Returns a blocking reason (str), or [new_cwd] to
    carry a `cd` forward to the stages and statements after it.

    `session_cwd` is the SESSION's cwd, never the post-`cd` one: a `cd` into an
    unrelated tree must not make that tree guarded (see guarded_roots)."""
    effective_cwd = cwd_box[0]
    ok = [effective_cwd]
    try:
        tokens = shlex.split(seg, comments=True)
    except ValueError:
        tokens = seg.split()
    if not tokens:
        return ok

    # Redirection into a .claude path is a write no matter the program.
    # No leading-whitespace requirement: `printf pwned>.claude/settings.json`
    # is valid shell and walked straight past the first version of this regex
    # (review finding, round 2). Excluding & and < from the target keeps `2>&1`
    # and here-strings from matching as paths.
    for redir in re.finditer(r">>?\s*([^\s;&|<>]+)", seg):
        raw = unquote(redir.group(1))
        # No backstop left -> a target this parser cannot read character-for-
        # character is refused, whether or not a `.claude` tail is visible in it
        # (review finding, round 9). `printf pwned > ${!V}/rules/pwn.md` shows
        # nothing to match against; that is the point of it.
        if layer2_blind and NOT_A_LITERAL.search(_subst(raw, assigns)):
            return ("redirects into a target this parser cannot read as a literal "
                    "path, while the same command re-baselines Layer 2: %s"
                    % redir.group(1))
        target = resolve(raw, effective_cwd, assigns)
        if target and hits_claude(target, session_cwd):
            return "redirects output into .claude/: %s" % redir.group(1)
        if target is None:
            tail = literal_claude_tail(raw, assigns) or ""
            if unwatched_by_layer2(tail):
                return ("redirects into a .claude/ file Layer 2 does not watch: %s"
                        % redir.group(1))
            # Watched, but this command erases the baseline that would catch it.
            if layer2_blind and protected_position(tail):
                return ("redirects into .claude/ while re-baselining Layer 2: %s"
                        % redir.group(1))

    # Leading VAR=value assignments, so a path in a variable still resolves.
    while tokens:
        m = ASSIGN.match(tokens[0])
        if not m:
            break
        assigns[m.group(1)] = m.group(2)
        tokens.pop(0)
    if not tokens:
        return ok

    prog = os.path.basename(tokens[0])
    args = tokens[1:]

    # NO BACKSTOP -> ONLY A PLAIN LITERAL IS READABLE (review finding, round 9).
    #
    # Everywhere else in this file, a token this parser cannot anchor is HANDED
    # OFF to Layer 2 on the stated ground that the write lands and the hash
    # moves. A same-command re-baseline falsifies that ground (round 8). Round 8
    # acted on it only where a literal `.claude` tail was still visible; round 9
    # showed the tail can be hidden in the variable too, at which point there is
    # nothing left to pattern-match and the only safe answer is to stop reading
    # tokens this parser cannot read.
    #
    # So inside a re-baselining command the verdict depends on NO expansion
    # semantics at all: a plain literal is judged as always, anything else is
    # refused. That is what makes the class finite instead of one more round of
    # out-guessing bash.
    #
    # Bounded three ways so the cost stays affordable: readers are exempt (a
    # `grep .claude/rules/*.md` beside a re-baseline still works), the sanctioned
    # entrypoints are exempt, and flag tokens and text payloads carrying a
    # newline are skipped exactly as they are in _unanchored_unwatched(). The
    # escape hatch is unchanged: run the two halves as SEPARATE Bash calls.
    if layer2_blind and prog not in READ_ONLY and not _is_sanctioned(tokens):
        unreadable = next((a for a in args
                           if not a.startswith("-") and "\n" not in a
                           and NOT_A_LITERAL.search(_subst(a, assigns))), None)
        if unreadable is not None:
            return ("%r takes an argument this parser cannot read as a literal "
                    "path (%s), while the same command re-baselines Layer 2"
                    % (prog, unreadable))

    # `cd .claude && touch x` -- the write target is relative to the NEW cwd.
    # A target we cannot resolve leaves the cwd UNKNOWN rather than pretending it
    # is the session cwd; see resolve().
    if prog == "cd" and args:
        return [resolve(args[0], effective_cwd, assigns) or UNKNOWN_CWD]

    if _is_sanctioned(tokens):
        return ok

    # A PROGRAM TEXT this parser cannot read, in a stage that mentions .claude/
    # (review finding, round 10). `awk 'BEGIN{system("touch .claude/x")}'` and
    # `sed -n 'w .claude/x' f` both write, and neither shows a path token to
    # resolve or a write flag to match -- the target is inside the script.
    #
    # Deliberately NOT a parse of awk/sed: this parser cannot read those
    # languages, so it refuses to authorize based on them. Same posture round 9
    # reached for shell expansions, one layer over.
    #
    # Scoped to `seg` (this ONE pipeline stage), not the whole statement, which
    # is what keeps the escape hatch open and pinned as an allow:
    #     cat .claude/settings.json | awk '{print $1}'
    # stage 2 mentions no .claude, so it passes; the path is stage 1's, where
    # `cat` is a genuine reader.
    if prog in SCRIPT_ARG_INTERPRETERS and ".claude" in seg:
        return ("%r runs a program text this parser cannot read, and that text "
                "mentions .claude/" % prog)

    # A token carrying a NEWLINE is a text payload, not a path: a commit message,
    # a --body, a heredoc line. Real filesystem arguments do not contain one.
    # Resolving them as paths is what blocked `git commit -m "<message quoting
    # the guard's own stderr>"` -- the message embeds the literal string
    # `/repo/.claude/settings.json`, so the whole message resolved to a path with
    # `.claude` as a component (ASK-291, measured live).
    #
    # NAMED GAP, not an oversight: `touch $'.claude/x\ny'` now walks past this
    # check. That is Layer 1 behaving as its own header describes -- COVERAGE,
    # NOT A BOUNDARY -- and Layer 2 still catches it, because the file lands and
    # the hash moves. The two shapes that carry a payload rather than a path,
    # redirects and interpreter code strings, are matched against the raw segment
    # further down and are NOT affected by this: `python3 -c "<multi-line code
    # touching .claude>"` stays blocked, and probe_guard.py pins it.
    # A flag token is not skipped outright any more (review finding, round 10):
    # its ATTACHED value is a path when it is one. See _flag_values().
    candidates = []
    for a in args:
        if "\n" in a:
            continue
        candidates.extend(_flag_values(a) if a.startswith("-") else [a])
    paths = [resolve(a, effective_cwd, assigns) for a in candidates]
    touches = [p for p in paths if p and hits_claude(p, session_cwd)]
    touches += _unanchored_unwatched(args, effective_cwd, assigns, layer2_blind)

    # A bare write inside an already-.claude cwd has no .claude token at all.
    if not touches and hits_claude(effective_cwd, session_cwd) and prog not in READ_ONLY:
        return "runs %r with cwd inside .claude/" % prog

    # An interpreter carries its target INSIDE a code string, where
    # component-wise path resolution cannot see it:
    #   python3 -c "open('.claude/settings.json','w')"
    # Found while writing the tests for this guard, not from the brief.
    # SCAR (2026-08-03, same false block as the pipeline rule, second site): this
    # matched ANY `.claude` text in the raw segment, so `python3 some-script.py
    # --desc "...mentions .claude/..."` was refused. An interpreter running a
    # SCRIPT FILE passes its remaining args to that script; those args are
    # already resolved component-wise above, and this rule is only needed for the
    # inline-code shape the comment names, where no path token exists to resolve.
    if prog in SHELL_SINKS and ".claude" in seg and \
            any(t in INLINE_CODE_FLAGS for t in args):
        return "%r carries a .claude/ path inside its code/argument string" % prog

    if not touches:
        return ok

    if prog in SHELL_SINKS:
        return "%r re-enters the shell with a .claude/ path: %s" % (prog, touches[0])

    if prog == "git":
        sub = args[0] if args and not args[0].startswith("-") else ""
        if sub in GIT_READ_ONLY:
            return ok
        return "git %s targets .claude/: %s" % (sub or "?", touches[0])

    # No inner write-form table any more (review finding, round 10): a member of
    # READ_ONLY has no file-writing channel in any form, so there is nothing left
    # to match against. A program that grew one leaves the set instead.
    if prog in READ_ONLY:
        return ok

    return "%r would write inside .claude/: %s" % (prog, touches[0])


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # never break the session on a malformed hook payload
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return 0
    cwd = payload.get("cwd") or os.getcwd()

    reason = analyse(command, cwd)
    if reason:
        sys.stderr.write(
            "BLOCKED by claude-path-write-guard (ASK-282): %s\n"
            ".claude/ wires every hook, rule and agent; an agent that writes there can "
            "disable its own gates. Use the sanctioned path: a proposal applied by "
            "apply-claude-changes.sh (additive-only, ratcheted, auto-reverting).\n" % reason)
        if _voids_layer2(command, cwd):
            sys.stderr.write(
                "This command also VOIDS Layer 2 -- it re-baselines it (%s) or it "
                "reaches its baseline file (%s) -- so a .claude/ path this parser "
                "cannot anchor has no backstop left and fails closed instead of being "
                "handed off (ASK-291 rounds 8 and 11). If the block is unexpected, run "
                "the two halves as SEPARATE Bash calls -- Layer 2 then runs between "
                "them, which is what the handoff assumes.\n"
                % (", ".join(REBASELINERS), LAYER2_BASELINE_REL))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
