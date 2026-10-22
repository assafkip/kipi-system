#!/usr/bin/env python3
"""Block a private term from reaching a PUBLIC repo: staged content, message, or PR.

Scar (2026-08-13): a pre-push scan of 15 commits found a captured production
alert sitting in a test fixture that carried a CLIENT NAME and the founder's
absolute home path, plus two commit subjects naming clients. This repo is public
with 102 stars and 23 forks. gitleaks passed all of it, because a client name is
not a secret in the credential sense. Nothing else looked.

Scar (2026-10-22, ASK-2058): the founder ruled "this repo should not have any
private info", and a scan built from the consulting registries found client
names on 128 files of main, client contact emails in a test, an introducer's
name in a lint test, and a personal voice corpus under q-system/output. The list
this guard read held ten hand-typed tokens. Every name the registries knew and
the token file did not had walked straight past it. So the list is now read from
the registries themselves, at call time, the same way the consulting name gate
reads them: a client onboarded next month is covered without anyone editing a
file.

The offending strings are described by CLASS above and deliberately NOT quoted
here. Quoting them would republish the exact data this file exists to keep out
of a public repo. That is not hypothetical: for one commit this docstring did
quote them verbatim (caught 2026-08-14, ASK-746). A privacy exclusion names the
data class, never the data.

Rewriting history does not remove objects that forks already hold, and GitHub
keeps dangling commits reachable by SHA. The fix that pays is preventing the
next one.

## The list never ships

Putting client names in a public repo to block client names is self-defeating.
Every source lives OUTSIDE the repo and is read at hook time:

  ~/.config/kipi/client-tokens         one token per line, '#' comments allowed
  ~/.config/kipi/private-terms.json    which private registries to read, and how
                                       (token_files, json_sources, dir_sources,
                                       exclude; see load_terms)

CI cannot read a laptop, so CI reads the same expanded list from the repo secret
PRIVATE_TERMS. `--sync-ci-secret` pushes it, from the lefthook pre-push stage,
only when its digest changed. A CI log of a public repo is itself public, so the
CI mode never prints a term: it prints the file, the line and the KIND.

Absent list => WARN and pass, never block, locally. A fresh clone by someone who
is not the founder has no clients to protect, and a gate that fails closed on a
missing local file blocks every contributor for nothing (scar: a-hook-that-
fails-closed-on-a-missing-script-blocks-the-fix-too). In CI the opposite holds
for this repo's own events: a missing secret there means the backstop is off,
so it fails, except on a fork PR, which GitHub never hands secrets.

## Bypass

Intentional (a public case study with recorded permission): put the bypass token
on its OWN LINE in the commit message (or the PR body, for CI), with a reason:

    client-name-guard-skip: case study, permission recorded 2026-08-01

Naming the token in prose bypasses nothing. The guard reads a TRAILER, not a
mention, and the line must start at column 0 so an indented quote of this very
docstring is not an invocation.

## One stage, and why (ASK-747)

There is ONE local scan and it runs at commit-msg. That is the only stage where
both facts hold at once:

  * the REAL message for THIS commit arrives as the argument -- no persistence,
    no cross-commit leak, and it is present for `git commit -m` exactly as for an
    editor commit;
  * `git diff --cached` still returns the staged content, because the commit
    object does not exist yet.

The earlier pre-commit stage could not see the message, so it could not honour
a legitimate bypass; COMMIT_EDITMSG persists across commits and is absent for
`git commit -m`. Both were measured, not argued (PR #194).

## Merges (ASK-2058, sp-7156177c)

`git diff --cached` compares the index with HEAD only, so on a merge every line
arriving from the other parent reads as ADDED. With client names on main, that
refused EVERY merge of origin/main into a branch, and the only way through was
--no-verify, which disarms every hook in the repo. PR #435 fixed it by excusing
lines already on ANY parent, and review blocked it: a local, never-pushed branch
is not public, so merging it is exactly the step that makes its content
publishable. The rule here: a line is excused only when a merge parent that is
ALREADY PUBLIC (contained in a remote-tracking branch) carries it. Every SHA in
MERGE_HEAD counts, so an octopus merge cannot flip the verdict on parent order.

Usage:
    client-name-guard.py --message <file>    # commit-msg: the one local scan
    client-name-guard.py --ci --base <sha> --head <sha>   # CI backstop
    client-name-guard.py --sync-ci-secret    # pre-push: refresh the CI secret
"""

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

KIPI_CONFIG = Path.home() / ".config" / "kipi"
TOKENS_FILE = KIPI_CONFIG / "client-tokens"
SOURCES_FILE = KIPI_CONFIG / "private-terms.json"
CI_SECRET = "PRIVATE_TERMS"
SKIP = "client-name-guard-skip"

# Shorter than this false-positives on prose. The original list used the same
# cutoff (len > 3) and measured 0 false positives over 59 posts and 133 lessons.
MIN_LEN = 4

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")

# A BYPASS IS AN ACT, NOT A WORD (ASK-747).
#
# This was `if SKIP in text`, which cannot tell an author INVOKING the bypass
# from prose that merely NAMES it. The guard's own introducing commit proved it:
# that message documented the token, both stages printed `bypassed`, and the
# guard never scanned the commit that introduced it.
#
# ANCHORED AT COLUMN 0, deliberately, so an indented quote of the usage block
# above is not an invocation and a git comment line cannot match.
_BYPASS_LINE = re.compile(rf"^{re.escape(SKIP)}(?::[ \t]*\S.*?)?[ \t]*$")


def bypass_reason(message):
    """The trailer authorising a bypass, or None.

    Reads the MESSAGE ONLY. Content is never consent: a diff can contain any
    text at all, including this file.
    """
    for line in (message or "").splitlines():
        if _BYPASS_LINE.match(line):
            return line.strip()
    return None


# --- the term list ---------------------------------------------------------

def variants(term):
    """Every separator spelling of a term, lowercased.

    Closed under composition, the consulting name gate's lesson (mrm-5): derive
    from the raw string AND the normalised base, or a squashed slug that keeps
    one original hyphen slips through ("ab-cd ef" -> "ab-cdef").
    """
    low = " ".join(term.strip().lower().split())
    base = " ".join(re.sub(r"[-_]+", " ", low).split())
    out = set()
    for seed in (low, base):
        for v in (seed, seed.replace(" ", "-"), seed.replace(" ", "_"),
                  seed.replace(" ", "")):
            out.add(v)
    return out


def _token_lines(path):
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _emails(node):
    """Every email-shaped string anywhere in a record, keys included."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and _EMAIL_RE.match(k.strip()):
                yield k.strip()
            yield from _emails(v)
    elif isinstance(node, list):
        for v in node:
            yield from _emails(v)
    elif isinstance(node, str) and _EMAIL_RE.match(node.strip()):
        yield node.strip()


def _json_source(src, add, warn):
    """Terms from one registry, as private-terms.json describes it.

    Keys: path, records (top-level key, list or dict of records), keys (record
    fields that name the org; a "dir/name" value contributes its last segment),
    people (field holding [{name, email}]), person_keys (fields that are a
    person's name), skip_when / only_when ({field: [values]}), multiword_only
    (drop one-word org names: a scraped company list is mostly ordinary words),
    short_names_ok (keep one-word person names, for recorded relationships).
    """
    path = Path(os.path.expanduser(src.get("path", "")))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warn(f"private source unreadable, skipped: {path} ({exc.__class__.__name__})")
        return
    recs = data.get(src["records"]) if src.get("records") else data
    if isinstance(recs, dict):
        items = list(recs.items())
    elif isinstance(recs, list):
        items = [(None, r) for r in recs]
    else:
        warn(f"private source has no records list, skipped: {path}")
        return
    skip = src.get("skip_when") or {}
    only = src.get("only_when") or {}
    multi = bool(src.get("multiword_only"))
    short_ok = bool(src.get("short_names_ok"))
    for key, rec in items:
        if not isinstance(rec, dict):
            continue
        if any(rec.get(k) in vals for k, vals in skip.items()):
            continue
        if only and not all(rec.get(k) in vals for k, vals in only.items()):
            continue
        for field in src.get("keys", []):
            for val in _strings(rec.get(field)):
                val = val.rstrip("/").rsplit("/", 1)[-1]
                if multi and len(re.sub(r"[-_]+", " ", val).split()) < 2:
                    continue
                add(val, "org")
        people = []
        for p in rec.get(src["people"], []) if src.get("people") else []:
            if isinstance(p, dict) and isinstance(p.get("name"), str):
                people.append(p["name"])
        for field in src.get("person_keys", []):
            people.extend(_strings(rec.get(field)))
        for name in people:
            name = name.split("(", 1)[0].strip()
            if len(name.split()) >= 2 or (short_ok and len(name) >= 3):
                add(name, "person")
        for email in _emails(rec):
            add(email, "email")
        if key and _EMAIL_RE.match(str(key)):
            add(key, "email")


# The exclusions the last load_terms applied. base_payload ships them to CI,
# because CI re-expands every spelling and would otherwise regrow an excluded
# one from a sibling ("the lab" from "the_lab"). Measured on this branch's
# first full-tree run, 2026-10-22: exactly that false positive.
_LAST_EXCLUDE = set()


def load_terms(warn=lambda m: print(f"client-name-guard: WARN {m}")):
    """{variant: kind} from every private source, or None when none exists.

    None means "this machine has nothing to protect" and the local scan passes.
    An empty dict means sources exist but yielded nothing, which also passes.
    """
    terms = {}
    exclude = set()
    found_source = False

    def add(term, kind):
        for v in variants(term):
            if len(v) >= MIN_LEN and v not in terms:
                terms[v] = kind

    env = os.environ.get(CI_SECRET)
    if env:
        found_source = True
        try:
            payload = json.loads(env)
        except ValueError:
            payload = {"terms": {"org": [l for l in env.splitlines() if l.strip()]}}
        for kind, items in (payload.get("terms") or {}).items():
            for t in items:
                add(t, kind)
        exclude.update(payload.get("exclude") or [])

    if TOKENS_FILE.exists():
        found_source = True
        for t in _token_lines(TOKENS_FILE):
            add(t, "org")

    if SOURCES_FILE.exists():
        found_source = True
        try:
            cfg = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        except ValueError as exc:
            warn(f"{SOURCES_FILE} is not valid JSON ({exc}); registry terms skipped")
            cfg = {}
        for f in cfg.get("token_files", []):
            p = Path(os.path.expanduser(f))
            if p.exists():
                for t in _token_lines(p):
                    add(t, "org")
            else:
                warn(f"private source missing, skipped: {p}")
        for src in cfg.get("json_sources", []):
            _json_source(src, add, warn)
        for d in cfg.get("dir_sources", []):
            root = Path(os.path.expanduser(d.get("path", "")))
            if not root.is_dir():
                warn(f"private source missing, skipped: {root}")
                continue
            skip = set(d.get("exclude", []))
            for child in sorted(root.iterdir()):
                if child.is_dir() and child.name not in skip and not child.name.startswith("."):
                    add(child.name, "org")
        exclude.update(cfg.get("exclude", []))

    if not found_source:
        return None
    # An exclusion drops EXACTLY the spelling listed. A two-word client name can
    # also be an ordinary phrase ("the lab") while its folder spelling
    # ("the_lab") is not, so expanding an exclusion to every separator spelling
    # would unblock the folder name too.
    dropped = {" ".join(x.lower().split()) for x in exclude}
    global _LAST_EXCLUDE
    _LAST_EXCLUDE = dropped
    return {t: k for t, k in terms.items() if t not in dropped}


def export_payload(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def base_payload():
    """The term list as CI receives it: kind -> sorted spellings.

    Already expanded and filtered on this machine, so private-terms.json never
    has to reach CI. CI expands each spelling again in load_terms, which only
    adds separator spellings of the same words, and then drops the shipped
    exclusions, so an excluded spelling cannot regrow there.
    """
    terms = load_terms(warn=lambda m: print(f"client-name-guard: WARN {m}", file=sys.stderr))
    if not terms:
        return None
    by_kind = {}
    for t, k in terms.items():
        by_kind.setdefault(k, []).append(t)
    return {"terms": {k: sorted(v) for k, v in sorted(by_kind.items())},
            "exclude": sorted(_LAST_EXCLUDE)}


# --- scanning --------------------------------------------------------------

def hits(text, terms):
    """{term: kind} for every term present on a word-ish boundary.

    Substring prefilter first: with registry-sized lists a single alternation
    regex over a merge-sized diff took 107 s on this repo (measured 2026-10-22),
    and a gate that slow gets switched off. `in` is C-speed and rules out almost
    every term before a regex is built.
    """
    low = text.lower()
    found = {}
    for t, kind in terms.items():
        if t in low and re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low):
            found[t] = kind
    return found


def _git(*args):
    # DECODE WITH REPLACEMENT, NOT STRICTLY. One undecodable byte in a diff (a
    # deleted loose object rendered inline, hit 2026-08-29) raised under strict
    # decoding and killed the commit with a traceback instead of a verdict. The
    # terms are ASCII, so replacement can only hide what was unreadable anyway.
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _added_lines(diff_text):
    """[(file, line_no, text)] for every added line of a unified diff."""
    out, path, line_no = [], None, 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            p = raw[4:]
            path = p[2:] if p.startswith("b/") else (None if p == "/dev/null" else p)
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line_no = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            out.append((path, line_no, raw[1:]))
            line_no += 1
        elif raw.startswith(" "):
            line_no += 1
    return out


def _staged_added(rev=None):
    args = ["diff", "--cached", "-U0", "--no-color", "--no-ext-diff"]
    if rev:
        args.append(rev)
    r = _git(*args)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "git diff --cached failed")
    return _added_lines(r.stdout)


def _blob(spec):
    """Raw bytes of a blob (":path" = the index, "<rev>:path"), or None."""
    r = subprocess.run(["git", "cat-file", "blob", spec], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def _blob_id(spec):
    r = _git("rev-parse", "--verify", "--quiet", spec)
    return r.stdout.strip() if r.returncode == 0 else None


# Members past this size are skipped rather than inflated in a commit hook.
_ZIP_MEMBER_CAP = 50 * 1024 * 1024


def binary_text(data):
    """The searchable text of a binary blob (ASK-2058 review blocker 1).

    Its raw bytes, decoded with replacement, catch a name stored as plain bytes
    (a PDF string, a database page, a pickle). A zip container (.docx, .xlsx,
    .pptx, .zip) deflates its text, so every member is inflated and scanned too:
    the architecture .docx files in this repo carried client names exactly that
    way. HONEST LIMIT: text drawn as pixels in an image is not text, and nothing
    here reads it.
    """
    chunks = [data]
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.file_size <= _ZIP_MEMBER_CAP:
                        chunks.append(z.read(info))
        except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError, EOFError):
            pass
    return "\n".join(c.decode("utf-8", errors="replace") for c in chunks)


def _changed_files(*diff_args):
    """[(path, is_binary)] for every path the diff adds or modifies.

    Deletions are excluded: removing a file that carried a name is the fix.
    --no-renames so a rename reads as an add of the NEW path, whose name is the
    thing that becomes public. -z so an odd filename cannot split a record.
    """
    st = _git("diff", *diff_args, "--name-status", "--no-renames", "-z")
    if st.returncode != 0:
        raise RuntimeError(st.stderr.strip() or "git diff --name-status failed")
    parts = st.stdout.split("\0")
    paths = []
    for i in range(0, len(parts) - 1, 2):
        if parts[i][:1] in ("A", "M", "T", "C"):
            paths.append(parts[i + 1])
    ns = _git("diff", *diff_args, "--numstat", "--no-renames", "-z")
    if ns.returncode != 0:
        raise RuntimeError(ns.stderr.strip() or "git diff --numstat failed")
    binary = set()
    for rec in ns.stdout.split("\0"):
        f = rec.split("\t")
        if len(f) == 3 and f[0] == "-" and f[1] == "-":
            binary.add(f[2])
    return [(p, p in binary) for p in paths]


def merge_parents():
    """Every SHA in MERGE_HEAD, or [] when this commit is not a merge.

    The FILE, not `git rev-parse MERGE_HEAD`: rev-parse returns only the first
    SHA, so an octopus merge's verdict used to depend on parent order (review
    minor on PR #435).
    """
    r = _git("rev-parse", "--git-path", "MERGE_HEAD")
    if r.returncode != 0:
        return []
    p = Path(r.stdout.strip())
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text().splitlines() if re.fullmatch(r"[0-9a-f]{40,64}", l.strip())]


def is_public(sha):
    """True when a remote-tracking branch already contains this commit.

    This repo is public, so anything on any pushed branch is already out. A
    commit that only exists locally is not, however it got there. A stale
    remote-tracking ref can only make this answer False more often, which makes
    the scan stricter, never looser.
    """
    r = _git("branch", "-r", "--contains", sha, "--format=%(refname)")
    return r.returncode == 0 and bool(r.stdout.strip())


def staged_added_lines():
    """The lines this commit adds that are not already public.

    An ordinary commit: added lines vs HEAD. A merge: of those, drop each line a
    PUBLIC parent already carries. A local parent excuses nothing. Fails CLOSED
    on a git error: we only get here with an armed list.
    """
    added = _staged_added()
    parents = merge_parents()
    if not parents:
        return "\n".join(t for _, _, t in added)
    keep = {t for _, _, t in added}
    for parent in parents:
        if is_public(parent):
            keep &= {t for _, _, t in _staged_added(parent)}
    return "\n".join(t for _, _, t in added if t in keep)


def staged_paths_and_binaries():
    """(path names, [(path, binary text)]) this commit adds that are not public.

    The ASK-2058 review found both holes with one reproducer each: a name in a
    binary blob and a name in a file's PATH passed the line scan, because
    neither is an added text line. On a merge, a path a PUBLIC parent already
    has, or a binary whose exact blob a public parent already has, is excused
    for the same reason an already-public line is.
    """
    public = [p for p in merge_parents() if is_public(p)]
    names, blobs = [], []
    for path, is_bin in _changed_files("--cached"):
        if any(_blob_id(f"{p}:{path}") for p in public):
            path_public = True
        else:
            path_public = False
            names.append(path)
        if not is_bin:
            continue
        staged_id = _blob_id(f":{path}")
        if path_public and any(_blob_id(f"{p}:{path}") == staged_id for p in public):
            continue
        data = _blob(f":{path}")
        if data is None:
            raise RuntimeError(f"cannot read the staged blob of {path}")
        blobs.append((path, binary_text(data)))
    return names, blobs


def _report_local(found_by_where):
    for where, names in found_by_where:
        print(f"BLOCK: private term in {where}: {', '.join(sorted(names))}")
    print("This repo is PUBLIC. Client names, people from client work, their")
    print("emails and client money never go public without recorded permission.")
    print("  fix   : rename to a placeholder (client-a, a client, a contact)")
    print(f"  intend: put '{SKIP}: <reason>' on its OWN LINE in the commit message")


def run_message(message_path):
    terms = load_terms()
    if terms is None:
        print(f"client-name-guard: no token list at {TOKENS_FILE} or {SOURCES_FILE}, "
              f"skipping (create one to arm this gate)")
        return 0
    if not terms:
        return 0
    message = message_path.read_text() if message_path.exists() else ""
    reason = bypass_reason(message)
    if reason:
        print(f"client-name-guard: bypassed via trailer {reason!r}")
        return 0
    try:
        content = staged_added_lines()
        names, blobs = staged_paths_and_binaries()
    except RuntimeError as exc:
        print(f"BLOCK: cannot read the staged diff ({exc}).")
        print("Refusing rather than reporting all clear. The list is armed, so")
        print("passing here would be an unverified claim that nothing leaked.")
        return 1
    surfaces = [("commit message", message), ("staged content", content),
                ("a staged file's path", "\n".join(names))]
    surfaces += [(f"binary file {p}", text) for p, text in blobs]
    found = [(where, hits(text, terms)) for where, text in surfaces]
    found = [(w, h) for w, h in found if h]
    if not found:
        return 0
    _report_local(found)
    return 1


# Paths a FULL-TREE scan skips (one per line, '#' comments). Path names only,
# never terms: this file is public. Used only by --tree, the fallback when a
# push carries no usable base; a range scan never consults it.
EXEMPT_FILE = Path(".github") / "private-terms-exempt.txt"


def _safe_path(path, terms):
    """The path, unless the path itself carries a term. Then a marker: the CI log
    is public, and printing the path would print the term."""
    return "<a path that carries a private term>" if hits(path or "", terms) else path


def _ci_terms():
    fork = os.environ.get("FORK_PR") == "true"
    terms = load_terms(warn=lambda m: print(f"client-name-guard: WARN {m}"))
    if not terms or not os.environ.get(CI_SECRET):
        if fork:
            print("::notice::client-name-guard: fork PR, no secrets; the push to main re-runs this scan")
            return None, 0
        print("::error::client-name-guard: PRIVATE_TERMS secret is missing or empty, so the "
              "backstop is off. Run `python3 q-system/.q-system/scripts/client-name-guard.py "
              "--sync-ci-secret` from a machine with the private sources.")
        return None, 1
    return terms, None


def _kinds(found):
    return ", ".join(sorted(set(found.values())))


def _scan_file(path, data, is_bin, terms, problems, line_hits=True):
    """Path name, then content (text lines with line numbers, or binary text)."""
    shown = _safe_path(path, terms)
    found = hits(path, terms)
    if found:
        print(f"::error::private term ({_kinds(found)}) in a file's path name")
        problems.append(f"{shown}: path name: {_kinds(found)}")
    if data is None:
        return
    if is_bin:
        found = hits(binary_text(data), terms)
        if found:
            print(f"::error file={shown}::private term ({_kinds(found)}) inside a binary file")
            problems.append(f"{shown}: binary content: {_kinds(found)}")
        return
    for n, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
        found = hits(line, terms)
        if found:
            print(f"::error file={shown},line={n}::private term ({_kinds(found)})")
            problems.append(f"{shown}:{n}: {_kinds(found)}")


def _finish(problems, terms, scope):
    if not problems:
        print(f"client-name-guard: clean ({len(terms)} terms, {scope})")
        return 0
    print("client-name-guard: BLOCK. Private terms (kind only; the term is never printed here):")
    for p in problems:
        print(f"  {p}")
    print("Run the local guard on your machine to see the term, then rename it to a placeholder.")
    return 1


def run_ci(base, head):
    """The backstop for every path a local hook never sees.

    A squash merge writes its commit message on GitHub from the PR title and
    body; an agent can commit with --no-verify or from a machine without the
    list. So CI scans the PR title and body, every commit message in the range,
    every added line, every added or modified path name, and the content of
    every added or modified binary, against the list in the PRIVATE_TERMS
    secret.

    It NEVER prints a term. This repo's CI logs are public, and a log line
    naming the matched client would be the leak this job exists to stop. A path
    that itself carries a term is printed as a marker, for the same reason.
    """
    terms, rc = _ci_terms()
    if terms is None:
        return rc

    body = os.environ.get("PR_BODY", "")
    if bypass_reason(body):
        print("client-name-guard: bypassed via trailer in the PR body")
        return 0

    problems = []
    for label in ("PR_TITLE", "PR_BODY"):
        found = hits(os.environ.get(label, ""), terms)
        if found:
            problems.append(f"{label.lower().replace('_', ' ')}: {_kinds(found)}")

    mb = _git("merge-base", base, head)
    if mb.returncode != 0:
        print(f"::error::client-name-guard: no merge base for {base}..{head}; refusing to report clean")
        return 1
    start = mb.stdout.strip()
    log = _git("log", "--format=%H%x00%B%x01", f"{start}..{head}")
    for rec in log.stdout.split("\x01"):
        if "\x00" not in rec:
            continue
        sha, msg = rec.strip("\n").split("\x00", 1)
        if bypass_reason(msg):
            continue
        found = hits(msg, terms)
        if found:
            problems.append(f"commit {sha[:10]} message: {_kinds(found)}")

    diff = _git("diff", "-U0", "--no-color", "--no-ext-diff", start, head)
    if diff.returncode != 0:
        print("::error::client-name-guard: git diff failed; refusing to report clean")
        return 1
    for path, line_no, text in _added_lines(diff.stdout):
        found = hits(text, terms)
        if found:
            shown = _safe_path(path, terms)
            print(f"::error file={shown},line={line_no}::private term ({_kinds(found)}) on an added line")
            problems.append(f"{shown}:{line_no}: {_kinds(found)}")

    try:
        changed = _changed_files(start, head)
    except RuntimeError as exc:
        print(f"::error::client-name-guard: {exc}; refusing to report clean")
        return 1
    for path, is_bin in changed:
        data = _blob(f"{head}:{path}") if is_bin else None
        if is_bin and data is None:
            print("::error::client-name-guard: cannot read a changed binary; refusing to report clean")
            return 1
        _scan_file(path, data, is_bin, terms, problems)

    return _finish(problems, terms, f"{start[:10]}..{head[:10]}")


def _tree_blobs(head):
    """(path, bytes) for every blob in the tree at head, through one cat-file."""
    ls = subprocess.run(["git", "ls-tree", "-r", "-z", head], capture_output=True)
    entries = []
    for rec in ls.stdout.split(b"\0"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1)
        mode, kind, sha = meta.split()
        if kind == b"blob":
            entries.append((path.decode("utf-8", errors="replace"), sha.decode()))
    proc = subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE)
    for path, sha in entries:
        proc.stdin.write(sha.encode() + b"\n")
        proc.stdin.flush()
        header = proc.stdout.readline().split()
        size = int(header[2])
        data = proc.stdout.read(size)
        proc.stdout.read(1)
        yield path, data
    proc.stdin.close()
    proc.wait()


def run_ci_tree(head):
    """Scan the WHOLE tree at head, and head's message (review blocker 2).

    The push fallback used to diff HEAD^..HEAD when GitHub's `before` was not a
    commit in the clone (a first push, a force-push), so a term added by any
    earlier commit of that push passed as clean. Whatever the push contained,
    the tree it produced is what is public now; scanning all of it cannot miss
    a commit. Paths in EXEMPT_FILE are skipped; they are listed by path, with
    the reason, because this file is public.
    """
    terms, rc = _ci_terms()
    if terms is None:
        return rc
    exempt = set()
    if EXEMPT_FILE.exists():
        exempt = {l.split("#", 1)[0].strip() for l in EXEMPT_FILE.read_text().splitlines()}
        exempt.discard("")
    problems = []
    msg = _git("log", "-1", "--format=%B", head).stdout
    if not bypass_reason(msg):
        found = hits(msg, terms)
        if found:
            problems.append(f"head commit message: {_kinds(found)}")
    scanned = 0
    for path, data in _tree_blobs(head):
        if path in exempt:
            continue
        scanned += 1
        _scan_file(path, data, b"\0" in data[:8000], terms, problems)
    return _finish(problems, terms, f"full tree at {head[:10]}, {scanned} files, {len(exempt)} exempt")


def sync_ci_secret():
    """Push the expanded list to the repo secret when it changed. Never blocks.

    Freshness for the backstop, not the gate itself: a failure here warns and
    exits 0, because refusing a push over a network hiccup is how hooks get
    removed. Only a PUBLIC repo gets the secret; a private instance has no CI
    reason to hold the list.
    """
    payload = base_payload()
    if payload is None:
        print("client-name-guard: no private sources on this machine; CI secret not synced")
        return 0
    blob = export_payload(payload)
    digest = hashlib.sha256(blob.encode()).hexdigest()
    url = _git("remote", "get-url", "origin").stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", url)
    if not m:
        return 0
    repo = m.group(1)
    stamp = KIPI_CONFIG / f"private-terms.ci-digest.{repo.replace('/', '_')}"
    if stamp.exists() and stamp.read_text().strip() == digest:
        return 0
    vis = subprocess.run(["gh", "repo", "view", repo, "--json", "visibility", "-q", ".visibility"],
                         capture_output=True, text=True)
    if vis.returncode != 0:
        print(f"client-name-guard: WARN cannot read {repo} visibility; CI secret not synced")
        return 0
    if vis.stdout.strip() != "PUBLIC":
        return 0
    r = subprocess.run(["gh", "secret", "set", CI_SECRET, "-R", repo], input=blob,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"client-name-guard: WARN gh secret set failed for {repo}: {r.stderr.strip()}")
        return 0
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(digest + "\n")
    print(f"client-name-guard: CI secret {CI_SECRET} refreshed on {repo} "
          f"({sum(len(v) for v in payload['terms'].values())} terms)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--message", type=Path,
                      help="the commit message file (lefthook commit-msg passes {1})")
    mode.add_argument("--ci", action="store_true",
                      help="CI backstop: scan --base..--head (or --tree), PR_TITLE, PR_BODY")
    mode.add_argument("--sync-ci-secret", action="store_true",
                      help="push the private list to the repo secret when it changed")
    ap.add_argument("--base")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--tree", action="store_true",
                    help="with --ci: scan the whole tree at --head instead of a range")
    args = ap.parse_args()
    if args.message is not None:
        return run_message(args.message)
    if args.ci:
        if args.tree:
            return run_ci_tree(args.head)
        if not args.base:
            ap.error("--ci needs --base or --tree")
        return run_ci(args.base, args.head)
    return sync_ci_secret()


if __name__ == "__main__":
    sys.exit(main())
