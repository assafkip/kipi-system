#!/usr/bin/env python3
"""PreToolUse gate: refuse the two command shapes that BYPASS the merge machinery.

Pairs with: no skill. This is the executable half of a rule that existed only as
prose ("No `--admin`, ever") in four plan docs and nowhere in code.

WHY THIS EXISTS (measured 2026-08-14, ASK-TBD / sp-6dc1b64c)

    gh api repos/:owner/:repo/branches/main/protection
      required checks : ['validate', 'kipi/reviewer-approved']
      enforce_admins  : False
    gh api repos/:owner/:repo --jq .permissions
      {"admin": true, "push": true}      # the credential every agent holds

`enforce_admins:false` exempts an IDENTITY, not a check. So `gh pr merge --admin`
merged to main past BOTH required checks, and a probe of the only layer that could
have refused it (destructive-op-deny.sh) returned ALLOW for every push and merge
form while its own controls returned DENY. The rule against it was written down
four times and enforced zero times.

WHAT THIS DENIES, AND WHY IT IS ONLY THESE TWO

The founder's hard constraint is "I do not want to be the merge step - ever."
So this must not add an approval step to merging. It denies only the shapes that
route AROUND machinery that already works without a human:

    gh pr merge --auto ...   ALLOW  GitHub holds it until required checks pass.
                                    This is the path linear-worker.sh already uses.
    gh pr merge --admin ...  DENY   The only way to defeat kipi/reviewer-approved.
    git push <protected>     DENY   Skips the PR, so skips both required checks.
                                    Scoped to protected repos: a fleet-marker
                                    tree (q-system/) or the protected remote
                                    set. Elsewhere the checks do not exist, so
                                    the push is not a bypass (sp-9154c64d).
    everything else          ALLOW  not-applicable

The effect is to make the autonomous path the ONLY path, which is what the founder
asked for. A gate that denied every merge would stop the worker and get switched
off (destructive-op-deny.sh states that principle in its own comments; the
design-auto-invoke scar is a gate that was off protecting nothing).

WHY ARGV AND NOT THE RAW STRING

destructive-op-deny.sh deliberately matches raw command strings and accepts that it
fires on prose that merely QUOTES a banned command, because any parser that decides
"this string is only prose" is a new bypass surface on a hook guarding production
deletes. That trade is right for THAT hook and wrong for this one: the blast radius
here is a refused merge, not a deleted volume, and `--body "do not use --admin"` is
an ordinary thing to type. Its own comment names the fix it wanted -- "a payload
field carrying the parsed command WORDS rather than the raw string" -- so this gate
does the parse with shlex and matches tokens. A parse FAILURE falls back to the raw
string, so a malformed command cannot launder a bypass through a broken tokenizer.

WHY UNRESOLVABLE MEANS ALLOW

A deny is only correct when this can PROVE the target is a protected branch on a
GitHub remote. When the repo directory cannot be determined (a `cd $WORK/seed` whose
variable is script-local, a `-C` path that does not exist), it allows. Lesson
`a-hook-that-fails-closed-on-a-missing-script-blocks-the-fix-too`: a PreToolUse gate
whose failure mode is "block everything" also blocks the tools needed to repair it.
The residual hole is named in section 6 of the plan rather than papered over.

WHAT THIS GATE CANNOT DO, AND WHY IT IS NOT WORTH TRYING (round 6, measured)

    eval "git push origin main"                  ALLOW
    eval $CMD                                    ALLOW
    source /tmp/script.sh                        ALLOW
    echo "git push origin main" | bash           ALLOW
    python3 -c "import os; os.system(...)"       ALLOW
    `echo git` push origin main                  ALLOW

8 of 11 payload-executing constructs walk straight through, and `eval $CMD` is
the one that ends the argument: the command string does not exist until Bash
expands the variable, so NO amount of static analysis of the tool-call text can
see it. Deciding what an arbitrary shell string will execute is undecidable, and
the only way to close `eval` here would be to deny every eval, source, and
`| bash` -- which breaks ordinary work and gets the gate switched off.

So this gate is a FAST LOCAL SPEED BUMP, not the authority. It catches the
shapes an agent actually types, immediately, with an explanation. It does not
and cannot catch a determined bypass.

THE AUTHORITY BELONGS ON THE SERVER. `enforce_admins: true` on the protected
branch makes `--admin` fail at the GitHub API no matter how the command was
spelled, wrapped, evaled or generated. That is one setting, it cannot be evaded
by any shell trick, and it is the single-authority answer this file spent five
rounds approximating. Measured 2026-08-14: enforce_admins is currently false and
the agent credential is an admin, which is what makes `--admin` work at all.

Contract: PreToolUse hook JSON on stdin. Deny = permissionDecision JSON on stdout,
exit 0 (the same shape as destructive-op-deny.sh emit_deny). Allow = exit 0, silent.
Self-test: python3 test_merge_bypass_gate.py
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

# Hardcoded, not queried. A PreToolUse hook runs on every Bash call under a 5s
# timeout; a network round-trip to read branch protection would make every command
# in the session wait on GitHub, and would fail open whenever the network is down.
# These are the two names the fleet actually protects.
PROTECTED_BRANCHES = {"main", "master"}

# The PUSH deny is scoped to repos that actually carry the PR machinery
# (required checks 'validate' + 'kipi/reviewer-approved'). Measured 2026-08-19
# (sp-9154c64d): the unscoped form blocked creating `main` on a brand-new
# personal repo (assafkip/adhd-output-style) that has no checks at all -- a
# refusal whose remedy ("let the machinery merge it") cannot exist there. A
# gate that fires where its own remedy is impossible teaches routing around
# gates. The MERGE side stays global on purpose: `--admin` is never the safe
# shape anywhere, and --auto costs nothing to type.
#
# TWO protected signals, either one denies (PR #226 review, major):
#   1. The FLEET MARKER: this hook ships to every kipi instance via
#      settings-template.json, and every instance carries q-system/ in its
#      root. A remote allowlist alone turned the deny off on all of them the
#      day it landed -- including instances with required checks and
#      enforce_admins:false, the exact scar configuration. The marker is
#      local, needs no enumeration, and cannot rot as instances are added.
#   2. The REMOTE SET: owner/name pairs for protected repos with no fleet
#      marker in the tree. Default assafkip/kipi-system; override via
#      MERGE_GATE_PROTECTED_REPOS (comma-separated), read per call so the
#      test suites can pin their own. Matching is case-folded and tolerates
#      a .git suffix (GitHub treats both as the same repo). An override that
#      is SET but yields no valid owner/name entry fails CLOSED -- the same
#      direction as the URL parser beside it.
# A GitHub URL whose owner/name cannot be parsed stays protected.
_DEFAULT_PROTECTED_REPOS = "assafkip/kipi-system"
_GH_URL_RE = re.compile(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def _protected_set() -> frozenset[str] | None:
    """Normalized owner/name set, or None when an explicit override is all
    malformed (the fail-closed sentinel)."""
    raw = os.environ.get("MERGE_GATE_PROTECTED_REPOS")
    entries = (raw if raw is not None else _DEFAULT_PROTECTED_REPOS).split(",")
    valid = set()
    for entry in entries:
        e = entry.strip().lower().removesuffix(".git").strip("/")
        if e.count("/") == 1 and all(e.split("/")):
            valid.add(e)
    if raw is not None and not valid:
        return None
    return frozenset(valid)


def _protected_repo(url: str, repo_dir: str) -> bool:
    if (Path(repo_dir) / "q-system").is_dir():
        return True  # fleet instance: the machinery is right there in the tree
    m = _GH_URL_RE.search((url or "").lower())
    if not m:
        return True  # a github URL this cannot parse stays protected
    repos = _protected_set()
    if repos is None:
        return True  # explicit override, zero valid entries: stay closed
    return f"{m.group(1)}/{m.group(2)}" in repos

# Shell separators that start a new command. `|` is included so `foo | git push ...`
# is examined rather than swallowed as an argument of foo.
_SEPARATORS = {";", ";;", "&&", "||", "|", "|&", "&", "\n"}

# Wrappers that run another command. Stripping them is not cosmetic: `sudo gh pr
# merge --admin` was ALLOW because the gate asked whether token 0 was `gh`.
_WRAPPERS = {"sudo", "doas", "nohup", "command", "stdbuf", "nice", "ionice",
             "time", "timeout", "xargs", "setsid", "script", "caffeinate"}
# Shells that take a whole command as a single quoted argument.
_DASH_C_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}


def _tokenize(command: str) -> tuple[list[str], bool]:
    """Tokens with shell OPERATORS as tokens in their own right.

    `shlex.split` does NOT separate `;`, so `true;gh pr merge --admin` came back
    as ['true;gh', 'pr', 'merge', '--admin'] and a gate keyed on token 0 never saw
    a gh command at all. One character defeated the whole thing (Codex round 4,
    filed minor, measured here as a full bypass on BOTH the merge and push sides).
    `punctuation_chars` is exactly the shlex mode for this and it is what the
    segment splitter always assumed it was being handed.

    Falls back on an unbalanced quote to a split that at least breaks on the
    operators, so a malformed command cannot launder a bypass through a broken
    tokenizer.
    """
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex), True
    except ValueError:
        rough = command
        for op in (";", "&", "|"):
            rough = rough.replace(op, f" {op} ")
        return rough.split(), False


def _dash_c_payload(seg: list[str]) -> str | None:
    """The command string inside `bash -c '<command>'`, or None."""
    if not seg or Path(seg[0]).name not in _DASH_C_SHELLS:
        return None
    for i, tok in enumerate(seg[1:], start=1):
        # `-lc`, `-ic`, `-xc` are ONE flag cluster ending in c, and each carries a
        # command payload exactly like `-c`. Matching only the exact token `-c`
        # meant `bash -lc '<cmd>'` was never recognised as a shell payload, which
        # defeated BOTH the merge and push sides (Codex round 5).
        if (tok.startswith("-") and not tok.startswith("--")
                and tok.endswith("c") and i + 1 < len(seg)):
            return seg[i + 1]
    return None


# Commands that PRINT or READ their arguments and cannot execute them. `echo git
# push` and `ls git push` were both DENIED (Codex round 6, minor) because the
# token scan asks only whether the word appears. Being wrong about a name here
# costs a false DENY, never a bypass, so the list stays short and obvious --
# anything that can run a child (find -exec, sed -e, xargs, awk) is NOT on it.
_NON_EXECUTING = {
    "echo", "printf", "ls", "cat", "grep", "egrep", "fgrep", "rg", "man",
    "head", "tail", "wc", "which", "type", "basename", "dirname", "file",
    "stat", "less", "more", "sort", "uniq", "diff", "jq", "column", "tee",
}


def _tool_position(seg: list[str], tool: str) -> str:
    """THE ONE authority on whether this gate can see a tool's arguments.

    'absent' | 'plain' (tool is the command) | 'hidden' (tool is in there but
    something else is the command, so the real argv is not visible here).

    WHY ONE FUNCTION. Round 4 gave the MERGE side a token scan so a wrapper could
    not hide `gh`, and left the PUSH side keyed on token 0. Round 5 then found
    exactly that: `myrunner git push origin main` was ALLOW while the same shape
    with gh was DENY. The rule was right and it was implemented at one of the two
    places that needed it. A safety property maintained at N sites is waiting for
    the round that finds the N+1th, so both verdicts now ask this.
    """
    if not any(Path(t).name == tool for t in seg):
        return "absent"
    if Path(seg[0]).name == tool:
        return "plain"
    if Path(seg[0]).name in _NON_EXECUTING:
        # The word is an argument to something that prints or reads it. Not a
        # hidden invocation.
        return "absent"
    return "hidden"


def _logical_lines(command: str) -> list[str]:
    """Split on real newlines, honouring backslash continuations.

    A newline is WHITESPACE to shlex, never a separator token, so
    `true\ngit push origin main` tokenized as one segment beginning with `true`
    and the push check (which asked about token 0) never fired. Splitting before
    tokenizing is what makes each line its own command.
    """
    joined = re.sub(r"\\\n", " ", command)
    return [ln for ln in joined.split("\n") if ln.strip()]


def _strip_wrappers(seg: list[str]) -> tuple[list[str], str | None]:
    """Peel leading wrapper commands, returning the inner argv and the wrapper.

    The wrapper NAME is returned rather than discarded, because a wrapped merge is
    refused for being wrapped -- `sudo gh pr merge --auto` is not the plain form,
    and nobody sudos gh. Reporting which wrapper was seen makes the refusal
    explainable instead of mysterious.
    """
    found = None
    i = 0
    while i < len(seg):
        name = Path(seg[i]).name
        if name not in _WRAPPERS:
            break
        found = found or name
        i += 1
        # Consume the wrapper's own options and any bare numeric argument
        # (`timeout 5 gh ...`), so the inner command lands at position 0.
        while i < len(seg) and (seg[i].startswith("-") or seg[i].replace(".", "", 1).isdigit()):
            i += 1
    return seg[i:], found

# git flags taking a separate value, so the value is never mistaken for a positional
# (`git push --repo X origin main` must read origin as the remote, not X).
_GIT_VALUE_FLAGS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec",
                    "--signed", "--force-with-lease", "-C", "--git-dir",
                    "--work-tree", "--namespace"}


def _split_segments(tokens: list[str]) -> list[list[str]]:
    """Split a token list into separate commands on shell separators."""
    segments: list[list[str]] = [[]]
    for tok in tokens:
        if tok in _SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(tok)
    return [s for s in segments if s]


def _strip_env_prefix(seg: list[str]) -> list[str]:
    """Drop leading VAR=value assignments and `env`, so `FOO=1 git push` still reads."""
    i = 0
    while i < len(seg):
        tok = seg[i]
        if tok == "env":
            i += 1
        elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            i += 1
        else:
            break
    return seg[i:]


def _resolve_dir(raw: str, base: str) -> str | None:
    """Resolve a directory argument, or None when it cannot be known.

    expandvars is what separates the two cases that matter. `cd $HOME/projects/x`
    is knowable and must stay gated. `cd $WORK/seed` inside a test script is a
    script-local variable this process never had, so it stays literal, and an
    unresolved `$` means the answer is None -> allow. Guessing there would deny a
    push to a throwaway local repo.
    """
    if not raw:
        return None
    expanded = os.path.expandvars(os.path.expanduser(raw))
    if "$" in expanded:
        return None
    p = Path(expanded)
    if not p.is_absolute():
        p = Path(base) / p
    try:
        resolved = p.resolve()
    except OSError:
        return None
    return str(resolved) if resolved.is_dir() else None


def _remote_url(repo_dir: str, remote: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", repo_dir, "remote", "get-url", remote],
                           capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _current_branch(repo_dir: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", repo_dir, "rev-parse", "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    branch = r.stdout.strip()
    return branch if r.returncode == 0 and branch and branch != "HEAD" else None


def _is_github(url: str | None) -> bool:
    return bool(url) and "github.com" in url


# gh is Go/cobra, so a bool flag accepts BOTH `--admin` and `--admin=<value>`, and
# the value is read by strconv.ParseBool. Measured against the real binary before
# fixing (Codex major, PR #155):
#
#   $ gh pr merge --admin=notabool 999999
#   invalid argument "notabool" for "--admin" flag: strconv.ParseBool: ...
#   $ gh pr merge --admin=true 999999 --squash
#   GraphQL: Could not resolve to a PullRequest with the number of 999999.
#
# The first proves the `=` spelling is accepted; the second proves `--admin=true`
# clears flag parsing and reaches the merge. Matching the bare token `--admin` let
# every truthy spelling through the gate whose whole job is to refuse them.
#
# ParseBool's exact vocabulary, not a lowercase-and-compare: `T` and `t` are true
# while `TrUe` is an ERROR to gh, so treating any case-fold of "true" as truthy
# would be a different set than the one the tool implements.
#
# ROUND 3 CHANGED THE RULE, NOT THE PATTERN LIST. Two reviews found two evasions
# of the denylist above, and the probe written to confirm the second found a third
# that was never reported:
#
#   gh pr merge --admin                        DENY    round 1 shipped this
#   gh pr merge --admin=true                   ALLOW   round 2, the = spelling
#   gh -R owner/repo pr merge --admin          ALLOW   round 3, reported
#   gh --repo owner/repo pr merge --admin      ALLOW   round 3, same class
#   gh --hostname github.com pr merge --admin  ALLOW   found by the probe
#
# The last three are not more flags to add. ANY gh global flag taking a SEPARATE
# value pushes that value into the positional stream and shifts the subcommand out
# from under a positional check. That is gh's grammar: this repo neither owns it
# nor can enumerate it. Three spellings in three rounds is the signal to stop
# patching and invert the rule.
#
# A DENYLIST fails OPEN on the shape you did not think of. An ALLOWLIST fails
# CLOSED. Anything that is not exactly the safe invocation is refused, so a
# grammar feature nobody here has heard of is denied by construction rather than
# by having been anticipated. Same principle as the capability token: authority
# granted narrowly and explicitly, never inferred from the absence of a known-bad
# marker.
#
# THE SAFE SHAPE:  gh pr merge --auto [method] [pr-ref]
# No global flags, no env prefix. `--auto` is REQUIRED because it is the only
# merge that defers to the required checks -- GitHub holds the PR until they pass.
# It is also exactly what linear-worker.sh and converge.sh already run, so
# requiring it breaks no measured caller.
#
# HONEST COST: a gh command carrying a bare `merge` token that is not this shape
# is refused and must be rephrased. That is a real false positive. It is the right
# direction for the most irreversible action in the fleet, and the deny message
# names the shape to use.
_GH_MERGE_ALLOWED_FLAGS = {
    "--auto",                       # required: the deferral to required checks
    "--squash", "-s", "--merge", "-m", "--rebase", "-r",
    "--delete-branch", "-d",
}
# Used ONLY to keep non-merge pr commands out of the trigger. Listing one wrong or
# missing one costs a false DENY, never a false ALLOW.
_GH_PR_OTHER_SUBCOMMANDS = {
    "create", "list", "view", "checkout", "close", "comment", "diff", "edit",
    "ready", "reopen", "status", "lock", "unlock", "review", "update-branch",
}
_PR_REF = re.compile(r"^(?:\d+|https://github\.com/[^/]+/[^/]+/pull/\d+)$")

_SAFE_SHAPE = ("the only merge this gate permits is:\n"
               "    gh pr merge --auto [--squash] [<n>]\n"
               "  no global flags (-R / --repo / --hostname), no env prefix, "
               "no other flags.")


def _merge_verdict(seg: list[str], note: str | None = None) -> str | None:
    """An unsafe `gh ... merge` invocation -> reason. Anything else -> None.

    The trigger is deliberately broad -- a `gh` token ANYWHERE plus a `merge`
    token -- because over-triggering costs a rephrase while under-triggering costs
    an unchecked merge into main. Keying it on token 0 was the round-4 hole: any
    wrapper or an unsplit `;` moved gh off position 0 and the trigger went quiet.
    Scanning for the token and THEN demanding position 0 keeps the fail-closed
    direction: being unable to see the shape is a refusal, not a pass.
    """
    if not seg:
        return None
    where = _tool_position(seg, "gh")
    if where == "absent" or "merge" not in seg:
        return None
    if where == "hidden":
        return ("a `gh ... merge` appears here but not as the command itself, so "
                "this gate cannot see its real arguments.\n  " + _SAFE_SHAPE)
    args = seg[1:]
    # `gh pr list --search merge` and friends: a different pr subcommand in the
    # subcommand slot means this was never a merge. Recognised only in the
    # no-global-flag form; with a global flag present it falls through to the
    # shape check and is refused, which is the safe direction.
    if len(args) >= 2 and args[0] == "pr" and args[1] in _GH_PR_OTHER_SUBCOMMANDS:
        return None

    if note:
        return (f"{note} on a gh merge can change what it does without changing a "
                "single argument (GH_REPO / GH_HOST retarget it; a wrapper hides "
                f"it).\n  " + _SAFE_SHAPE)
    if args[:2] != ["pr", "merge"]:
        return ("this is not the plain `gh pr merge` form. A global flag that "
                "takes a value (-R, --repo, --hostname) shifts the subcommand, "
                "which is how two earlier bypasses worked, so every form but the "
                "plain one is refused.\n  " + _SAFE_SHAPE)

    rest = args[2:]
    unknown = [t for t in rest
               if t not in _GH_MERGE_ALLOWED_FLAGS and not _PR_REF.match(t)]
    if unknown:
        return (f"unrecognised argument(s) on a merge: {unknown}. Refusing rather "
                "than guessing what they do -- `--admin` in every spelling lands "
                "here.\n  " + _SAFE_SHAPE)
    if "--auto" not in rest:
        return ("a merge without --auto does not defer to the required checks. "
                "--auto lets GitHub hold the PR until 'validate' and "
                "'kipi/reviewer-approved' pass.\n  " + _SAFE_SHAPE)
    return None


def _push_verdict(seg: list[str], cwd: str) -> str | None:
    """`git push` landing on a protected branch of a GitHub remote -> reason."""
    if not seg:
        return None
    # Same authority the merge side uses. Round 5 found this side still keyed on
    # token 0, so a wrapper hid the push while the identical shape with gh was
    # already refused. One rule, asked in both places.
    where = _tool_position(seg, "git")
    if where == "absent" or "push" not in seg:
        return None
    if where == "hidden":
        return ("a `git ... push` appears here but not as the command itself, so "
                "this gate cannot see which branch it targets.\n  "
                "Run the push as the command itself, without a wrapper.")

    repo_dir = cwd
    args: list[str] = []
    i = 1
    saw_push = False
    while i < len(seg):
        tok = seg[i]
        if tok == "-C" and i + 1 < len(seg):
            # `git -C <dir> push ...` targets ANOTHER repo. Resolving origin in the
            # session cwd instead would deny a push to a temp repo while missing a
            # push to the real one.
            resolved = _resolve_dir(seg[i + 1], cwd)
            if resolved is None:
                return None
            repo_dir = resolved
            i += 2
            continue
        if not saw_push:
            if tok == "push":
                saw_push = True
            i += 1
            continue
        args.append(tok)
        i += 1

    if not saw_push:
        return None

    # Positionals only: <remote> [<refspec>...]
    positionals: list[str] = []
    j = 0
    while j < len(args):
        tok = args[j]
        if tok in _GIT_VALUE_FLAGS:
            j += 2
            continue
        if tok.startswith("-"):
            j += 1
            continue
        positionals.append(tok)
        j += 1

    remote = positionals[0] if positionals else "origin"
    refspecs = positionals[1:]

    # A URL typed straight on the command line never reaches `remote get-url`.
    url = remote if re.match(r"^(https?://|git@|ssh://)", remote) else _remote_url(repo_dir, remote)
    if not _is_github(url):
        return None
    if not _protected_repo(url, repo_dir):
        # No fleet marker in the tree and not in the protected remote set:
        # there are no 'validate' / 'kipi/reviewer-approved' checks to skip,
        # so the deny's remedy does not exist there (sp-9154c64d).
        return None

    if refspecs:
        # `src:dst` lands on dst; a bare name lands on itself.
        targets = [rs.split(":")[-1] for rs in refspecs]
    else:
        branch = _current_branch(repo_dir)
        if branch is None:
            return None
        targets = [branch]

    hit = [t for t in targets if t.lstrip("+").split("/")[-1] in PROTECTED_BRANCHES]
    if not hit:
        return None
    return (f"pushing straight to {hit[0]!r} on a GitHub remote skips the pull "
            "request, and both required checks live on the PR.")


def classify(command: str, cwd: str, _depth: int = 0) -> tuple[str, str]:
    """THE decision. One constructor, so the property has one place to be wrong.

    Lesson `a-safety-property-enforced-at-n-sites-is-not-a-chokepoint`: a rule
    maintained by N cooperating checks is waiting for the round that finds the
    N+1th seam. The hook body below only renders what this returns.
    """
    if not command or not command.strip():
        return "allow", ""
    if _depth > 4:
        # A wrapper chain deep enough to hit this is not a command anyone types.
        return "deny", ("nested shell wrappers too deep to analyse.\n  " + _SAFE_SHAPE)

    # Newlines first: shlex treats a newline as WHITESPACE, never a separator, so
    # a two-line command arrived as ONE segment whose first token was line 1's
    # command and neither verdict ever saw line 2 (Codex round 5).
    parsed = True
    segments: list[list[str]] = []
    for line in _logical_lines(command):
        toks, ok = _tokenize(line)
        parsed = parsed and ok
        segments.extend(_split_segments(toks))

    cur_dir = cwd
    for raw_seg in segments:
        seg = _strip_env_prefix(raw_seg)
        if not seg:
            continue
        # An env prefix is not cosmetic on a merge: GH_REPO / GH_HOST retarget gh
        # without changing one argument, so the same argv can merge in a different
        # repo. The prefix was previously stripped and forgotten.
        note = "an environment prefix" if len(seg) != len(raw_seg) else None

        # ORDER IS LOAD-BEARING: strip wrappers BEFORE looking for a `-c` payload.
        # The first version checked the payload first, so `sudo bash -c '<cmd>'`
        # found no shell at position 0 (it found `sudo`), stripped the wrapper, and
        # never looked again -- ALLOW. Caught by this file's own reproducer, not by
        # the probe that only tried each evasion on its own. Evasions compose.
        seg, wrapper = _strip_wrappers(seg)
        if not seg:
            continue
        if wrapper:
            note = f"a `{wrapper}` wrapper"

        # `bash -c '<command>'` hides an entire command inside one quoted token.
        # Recurse on the payload instead of pretending the outer word is the whole
        # story. Found by Codex round 4, filed minor, measured as a full bypass:
        # `bash -c 'gh pr merge 155 --admin'` was ALLOW.
        payload = _dash_c_payload(seg)
        if payload is not None:
            decision, reason = classify(payload, cur_dir, _depth + 1)
            if decision == "deny":
                return "deny", reason
            continue

        if Path(seg[0]).name == "cd" and len(seg) > 1:
            resolved = _resolve_dir(seg[1], cur_dir)
            cur_dir = resolved if resolved else cur_dir
            continue
        reason = _merge_verdict(seg, note)
        if reason:
            return "deny", reason
        reason = _push_verdict(seg, cur_dir)
        if reason:
            return "deny", reason

    if not parsed and "--admin" in command and re.search(r"\bpr\s+merge\b", command):
        return "deny", ("`gh pr merge --admin` appears in a command this gate could "
                        "not tokenize (unbalanced quote). Refusing rather than "
                        "guessing.")
    return "allow", ""


REMEDY = (
    "  Let the machinery merge it:  gh pr merge --auto --squash <n>\n"
    "  GitHub then merges it itself once 'validate' and 'kipi/reviewer-approved' "
    "are green. No human in the loop, which is the point.\n"
    "  If a check is wrong, fix the check. Do not route around it."
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    cwd = payload.get("cwd") or os.getcwd()

    decision, reason = classify(command, cwd)
    if decision == "allow":
        return 0

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"merge-bypass-gate: {reason}\n{REMEDY}",
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
