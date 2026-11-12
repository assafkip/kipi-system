#!/usr/bin/env python3
"""reuse-gate: a new script must answer the kipi-system tools that already do its job.

Rule-ID: RULE-2026-11-12-REUSE   (ticket ASK-4582)

WHY (founder, 2026-11-12, verbatim): "reuse kipi system mechinary instead of building
new - always - put that in code".

THE SCAR (ASK-3834 run, 2026-11-11): an orchestrator wrote new scripts under
~/.config/kipi/ask-3834/ that duplicated kipi machinery: stall watchers while
lane-watchdog.py exists, merge-chain watchers while pr-owner.py exists, a
commit-lock.sh. Nothing looked for an existing tool before a new one was written.

THE RULE (deterministic, no model call):
  A Write (or an Edit/MultiEdit that creates a file) of a NEW executable script
  (.py .sh .js .ts, or content that starts with #!) is refused unless its first
  40 lines carry one of:
    Reuses-kipi: <path in kipi-system>             a FILE at origin/main
    Kipi-checked: <slug>, <slug> -- <why none fits>
  Kipi-checked must name every kipi capability this gate lists for the file, by
  slug or path. With nothing listed it must say `Kipi-checked: none -- <reason>`,
  so the lookup always happens. The separator may also be an em or en dash: the
  founder's output rule bans the double hyphen, and an agent obeying it should
  not lose a round. The refusal's own <placeholder> text pasted back counts as
  nothing. A Reuses-kipi path that is not a file refuses even beside a valid one:
  a false citation never passes. A citation may be relative to the kipi-system
  root, prefixed with kipi-system/ or ~/projects/kipi-system/, or absolute inside
  any kipi tree (a worktree, the marketplace clone).

PASSES UNTOUCHED: a rewrite of a file that exists. Test files: new-view-gate's
own is_test_path, imported, so the two gates agree on what a test is; it is wider
than the brief's list (also test-*, *-test.*, spec/, *.spec.*) on purpose.
Kipi-system's own tree: the checkout, any worktree of it, any clone whose origin
is assafkip/kipi-system, judged on the RESOLVED path so a symlink into it counts;
those files ARE kipi machinery. Temp space: /tmp, /private/tmp, /var/folders,
/private/var/folders, any scratchpad/ part. $TMPDIR is not added: a broad one
would exempt a whole tree (review of #755).

THE LOOKUP reuses q-system/.q-system/scripts/capability-map-gen.py; it is not a
second scanner. The generator runs once per kipi-system origin/main sha, over a
`git archive` export of that sha in a temp dir under the cache (the export_base
shape in capability-gate.py), and a compact copy of its capability list is cached
at ~/.cache/kipi/reuse-gate/<sha>.json. An export, not a checkout the gate keeps:
review of #755 showed a kept checkout can wedge (a stale index.lock after a
killed checkout, a lost worktree registration after the repo moves) and then fail
open for every later sha. An export has no state to wedge, and it stays out of
the shared checkout's worktree list. The fast path is one ref read and one JSON
read. A miss costs one export and one generator run: 0.84 s + 7.2 s measured on
kipi-system 2026-11-11, which is why hooks.json gives this hook 60 s. origin/main
is the local ref as of the last fetch; the hook never fetches.

  Overlap: lowercased words of 4+ letters (camelCase split, a trailing s folded,
  stopwords dropped) from the new file's basename and its first docstring or
  comment line, against each capability's name and path. Ranked by shared words
  (a basename word counts double), then machinery before rules, then path. The
  top 8 are listed, and exactly those 8 are what Kipi-checked must name, so the
  author can always satisfy the gate from what it printed.

FAILS OPEN when the map cannot be had: kipi-system not found, no origin/main ref,
the export fails, the generator fails or times out, or its output does not parse.
A gate that fails closed on its own infrastructure would block every new script
in the fleet because a map broke. The warning goes to stderr AND to stdout as a
hook systemMessage, because on exit 0 Claude Code shows stderr to no one (review
of #755). A failed sha is recorded as <sha>.err and is not regenerated on every
write (a 55 s stall per write would be worse than the gap); the next origin/main
sha retries from a fresh export. Nothing reads the .err files yet: ASK-4595.
Malformed hook input and internal errors also pass, with the same warning.

HONEST BOUNDARY: this proves the overlapping kipi tools were NAMED, not that a
named tool truly does not fit; that judgment stays with the agent and its review.
The map holds what capability-map-gen.py collects: Python engines of 40+ lines,
skills, commands, settings.json hooks, agents, rules. A shell script that is not
wired as a hook is not in it. A script created through Bash (heredoc, cp, tee) is
not seen: new-view-gate, whose coverage this matches, has the same boundary.

Test seams (env): KIPI_REUSE_GATE_REPO, KIPI_REUSE_GATE_CACHE, KIPI_REUSE_GATE_GEN,
KIPI_REUSE_GATE_TEMP_ROOTS (colon list; replaces the whole temp policy).
Kill switch for the founder's shell only: REUSE_GATE_OFF=1.

Contract: PreToolUse(Write|Edit|MultiEdit), hook JSON on stdin. exit 0 = pass,
exit 2 = block (stderr goes to the model). stdlib only.
"""
from __future__ import annotations

# Only what the fast path needs is imported here. This hook runs on EVERY Write
# and Edit in the fleet; module-level subprocess/tempfile/fcntl/importlib cost
# 16 ms over bare startup per call (measured 2026-11-11, new-view-gate: 4 ms).
# The slow path imports them where it uses them.
import json
import os
import re
import sys
from pathlib import Path

RULE_ID = "RULE-2026-11-12-REUSE"
FOUNDER = ('Founder, 2026-11-12: "reuse kipi system mechinary instead of building new - '
           'always - put that in code".')
HERE = Path(__file__).resolve().parent
SCRIPT_EXT = (".py", ".sh", ".js", ".ts")
HEADER_LINES = 40
MAX_LISTED = 8
KEEP_CACHES = 10
# Export + generator stay inside hooks.json's 60 s: 15 + 40, measured 0.84 + 7.2.
EXPORT_TIMEOUT = 15
GEN_TIMEOUT = 40
GEN_REL = "q-system/.q-system/scripts/capability-map-gen.py"
DEFAULT_REPO = "~/projects/kipi-system"
DEFAULT_CACHE = "~/.cache/kipi/reuse-gate"
DEFAULT_TEMP = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
KIPI_ORIGIN = re.compile(r"[:/]assafkip/kipi-system(?:\.git)?/?$")
SHA = re.compile(r"[0-9a-f]{40}")
REUSES_RE = re.compile(r"Reuses-kipi:\s*(\S+)")
CHECKED_RE = re.compile(r"Kipi-checked:\s*(.*)$")
# The reason separator: --, or an em or en dash (escaped, so this file holds none).
SEP_RE = re.compile(r"\s*(?:--|\u2014|\u2013)\s*")
# The refusal's template text, e.g. <slug> or <why none fits>, pasted back verbatim.
PLACEHOLDER_RE = re.compile(r"<[^<>]*>")
# Machinery first on a tie: measured 2026-11-11, a path-only tiebreak put
# .claude/rules/*.md ahead of the script that does the job (linear-sync).
LAYER_RANK = {"L5": 0, "L2": 1, "L1": 2, "L3": 3, "L4": 4, "L0": 5, "L6": 6}
# Generic words that would make every capability overlap. Measured on the real map
# 2026-11-11: before path words (system, scripts, hooks...) were dropped, "voice
# check" overlapped 100 capabilities and the useful ones were not in the top 8.
_STOPWORDS = """
with from that this into what when then than have each over only none also does used
uses using will been about after before their there they them your more most some such
very just make made must should would could every given against once time runs
file files script scripts python bash shell main util utils helper helpers tool tools
test tests json yaml data path paths config init list read write output project projects
kipi system core plugins plugin hooks hook skills skill commands command claude agents
agent rules rule engine engines domain settings readme root
""".split()


class MapUnavailable(Exception):
    """The capability map cannot be had; the gate fails open."""


def _fold(word: str) -> str:
    # tickets/ticket and worktrees/worktree missed each other in the 2026-11-11
    # measurement. One fold, applied to both sides, so the pair always meets.
    return word[:-1] if len(word) > 4 and word.endswith("s") else word


STOP = {_fold(w) for w in _STOPWORDS}


def tokens(text: str) -> set:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text or "")
    return {f for f in (_fold(w) for w in re.findall(r"[a-z]{4,}", text.lower())) if f not in STOP}


def slug(text: str) -> str:
    # capability-map-gen.py's dedupe() slug, so a slug copied from a map matches.
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


# --- what the write is -------------------------------------------------------


def creation(tool: str, inp: dict, cwd: str):
    """(path, content) when this call creates a new file, else None."""
    path = inp.get("file_path") or ""
    if not isinstance(path, str) or not path:
        return None
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(cwd or os.getcwd(), path)
    path = os.path.normpath(path)
    if os.path.lexists(path):
        return None
    if tool == "Write":
        content = inp.get("content")
    elif tool == "Edit":
        # An Edit with old text on a missing file fails in the tool itself.
        if inp.get("old_string"):
            return None
        content = inp.get("new_string")
    elif tool == "MultiEdit":
        edits = [e for e in (inp.get("edits") or []) if isinstance(e, dict)]
        if not edits or edits[0].get("old_string"):
            return None
        # Apply every edit in order: a header added by a later edit was a false
        # block when only edits[0] was read (review of #755).
        content = edits[0].get("new_string") or ""
        for e in edits[1:]:
            old, new = e.get("old_string") or "", e.get("new_string") or ""
            if old and isinstance(old, str) and isinstance(new, str):
                content = content.replace(old, new, -1 if e.get("replace_all") else 1)
    else:
        return None
    return path, content if isinstance(content, str) else ""


def is_script(path: str, content: str) -> bool:
    return path.lower().endswith(SCRIPT_EXT) or content.startswith("#!")


def is_test_path(path: str) -> bool:
    # Imported, not copied: two gates with two definitions of "a test" is the
    # parity defect capability-map-gen.py's is_excluded_tree scar describes.
    import importlib.util
    spec = importlib.util.spec_from_file_location("new_view_gate", HERE / "new-view-gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.is_test_path(path)


def is_temp(path: str) -> bool:
    override = os.environ.get("KIPI_REUSE_GATE_TEMP_ROOTS")
    if override is not None:
        roots, scratch = [r for r in override.split(":") if r], False
    else:
        roots, scratch = list(DEFAULT_TEMP), True
    for cand in {path, os.path.realpath(path)}:
        for root in roots:
            root = root.rstrip("/")
            if root and (cand == root or cand.startswith(root + "/")):
                return True
        if scratch and "scratchpad" in Path(cand).parts:
            return True
    return False


# --- git, read from disk where a subprocess is not needed --------------------


def git_repo_of(start: Path):
    """(top dir, common .git dir) of the nearest repo holding `start`, or (None, None)."""
    d = start
    while not d.exists() and d.parent != d:
        d = d.parent
    while True:
        dotgit = d / ".git"
        if dotgit.is_dir():
            return d, dotgit
        if dotgit.is_file():
            text = dotgit.read_text(errors="ignore").strip()
            if not text.startswith("gitdir:"):
                return None, None
            gd = Path(text[len("gitdir:"):].strip())
            gd = gd if gd.is_absolute() else d / gd
            common = gd / "commondir"
            if common.is_file():
                c = Path(common.read_text(errors="ignore").strip())
                return d, (c if c.is_absolute() else gd / c)
            return d, gd
        if d.parent == d:
            return None, None
        d = d.parent


def git_common_dir(start: Path):
    return git_repo_of(start)[1]


def origin_url(common: Path) -> str:
    try:
        text = (common / "config").read_text(errors="ignore")
    except OSError:
        return ""
    m = re.search(r'^\s*\[remote\s+"origin"\]\s*$(.*?)(?=^\s*\[|\Z)', text, re.M | re.S)
    u = re.search(r"^\s*url\s*=\s*(\S+)", m.group(1), re.M) if m else None
    return u.group(1) if u else ""


def kipi_top(path: str, repo: Path):
    """Root of the kipi-system tree holding `path`, or None.

    Judged on the RESOLVED path: a symlink into kipi-system was gated by the outer
    repo when the walk followed the path as written (review of #755)."""
    top, common = git_repo_of(Path(os.path.realpath(path)).parent)
    if common is None:
        return None
    if (repo / ".git").exists():
        mine = git_common_dir(repo)
        if mine is not None and os.path.realpath(mine) == os.path.realpath(common):
            return top
    return top if KIPI_ORIGIN.search(origin_url(common)) else None


def in_kipi_tree(path: str, repo: Path) -> bool:
    return kipi_top(path, repo) is not None


def _env():
    # A hook can run under a git hook's env; GIT_DIR there would aim every call
    # below at the wrong repo.
    return {k: v for k, v in os.environ.items()
            if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}


def _git(cwd, *args, timeout=30) -> str:
    import subprocess
    try:
        p = subprocess.run(["git", "-C", str(cwd), "-c", "core.hooksPath=/dev/null", *args],
                           capture_output=True, text=True, timeout=timeout, env=_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MapUnavailable(f"git {args[0]}: {type(exc).__name__}")
    if p.returncode != 0:
        last = (p.stderr.strip().splitlines() or [f"exit {p.returncode}"])[-1]
        raise MapUnavailable(f"git {args[0]} failed: {last}")
    return p.stdout.strip()


def origin_main(repo: Path) -> str:
    if not (repo / ".git").exists():
        raise MapUnavailable(f"kipi-system not found at {repo}")
    common = git_common_dir(repo)
    try:
        s = (common / "refs" / "remotes" / "origin" / "main").read_text().strip()
        if SHA.fullmatch(s):
            return s
    except OSError:
        pass
    # Loose ref first: when both exist, the loose one is current (measured on the
    # shared checkout 2026-11-11: loose c39d180, packed 653a360).
    try:
        for line in (common / "packed-refs").read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == "refs/remotes/origin/main" and SHA.fullmatch(parts[0]):
                return parts[0]
    except OSError:
        pass
    try:
        out = _git(repo, "rev-parse", "--verify", "-q", "refs/remotes/origin/main^{commit}")
    except MapUnavailable:
        out = ""
    if not SHA.fullmatch(out):
        raise MapUnavailable(f"no origin/main ref in {repo}")
    return out


def exists_at(repo: Path, sha: str, rel: str) -> bool:
    """A FILE at sha. A directory does not count: the brief says "naming an existing
    kipi-system file", and `cat-file -e` passed `Reuses-kipi: q-system` (review of #755)."""
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return False
    import subprocess
    p = subprocess.run(["git", "-C", str(repo), "cat-file", "-t", f"{sha}:{rel}"],
                       capture_output=True, text=True, timeout=10, env=_env())
    return p.returncode == 0 and p.stdout.strip() == "blob"


# --- the capability map: generate once per sha, one writer --------------------


def _atomic_write(path: Path, text: str):
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _read_cache(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    caps = data.get("capabilities") if isinstance(data, dict) else None
    return caps if isinstance(caps, list) else None


def _export(repo: Path, sha: str, dest: Path):
    """`git archive` of sha, unpacked into dest. No checkout, no worktree entry."""
    import subprocess
    arch = None
    try:
        arch = subprocess.Popen(["git", "-C", str(repo), "archive", "--format=tar", sha],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env())
        try:
            tar = subprocess.run(["tar", "-x", "-C", str(dest)], stdin=arch.stdout,
                                 capture_output=True, timeout=EXPORT_TIMEOUT)
        finally:
            arch.stdout.close()
        arch_err = arch.stderr.read().decode(errors="ignore")
        arch.wait(timeout=EXPORT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        if arch is not None:
            arch.kill()
        raise MapUnavailable(f"git archive {sha[:7]}: {type(exc).__name__}")
    if arch.returncode or tar.returncode:
        why = arch_err.strip() or tar.stderr.decode(errors="ignore").strip() or "nonzero exit"
        raise MapUnavailable(f"git archive {sha[:7]} failed: {why.splitlines()[-1][:200]}")


def _generate(repo: Path, cache: Path, sha: str) -> list:
    import tempfile
    # No local cleanup: _prune removes the export, under the same lock, after
    # every success and every failure. A second cleanup path was dead code that
    # mutation could not kill (round 1 of #755).
    tree = Path(tempfile.mkdtemp(dir=str(cache), prefix=".tree-"))
    _export(repo, sha, tree)
    return _run_generator(tree)


def _run_generator(tree: Path) -> list:
    import subprocess
    gen = Path(os.environ.get("KIPI_REUSE_GATE_GEN") or tree / GEN_REL)
    out = tree / ".reuse-gate-map.json"
    try:
        p = subprocess.run([sys.executable, "-I", str(gen), "--root", str(tree), "--repo",
                            "kipi-system", "--out", str(out), "--skeleton", str(tree)],
                           capture_output=True, text=True, timeout=GEN_TIMEOUT, env=_env())
    except subprocess.TimeoutExpired:
        raise MapUnavailable(f"capability-map-gen.py timed out after {GEN_TIMEOUT}s")
    if p.returncode != 0:
        last = (p.stderr.strip().splitlines() or [f"exit {p.returncode}"])[-1]
        raise MapUnavailable(f"capability-map-gen.py failed: {last[:200]}")
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
        caps = [{"name": str(c["name"]), "entry": str(c["entry"]), "layer": str(c["layer"])}
                for c in data["capabilities"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MapUnavailable(f"capability-map-gen.py output did not parse: {type(exc).__name__}")
    if not caps:
        raise MapUnavailable("capability-map-gen.py listed no capabilities")
    return caps


def _prune(cache: Path):
    """Keep the newest caches and errors; drop what a killed run left behind.

    Runs under the lock, so no export or temp file here belongs to a live run.
    Review of #755: leftovers were never cleaned, and .err files piled up one per
    sha because pruning ran only after a success."""
    import shutil
    for pattern in ("*.json", "*.err"):
        files = sorted(cache.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
        for old in files[KEEP_CACHES:]:
            try:
                old.unlink()
            except OSError:
                pass
    for old in list(cache.glob(".tree-*")) + list(cache.glob(".tmp-*")):
        try:
            if old.is_dir():
                shutil.rmtree(old, ignore_errors=True)
            else:
                old.unlink()
        except OSError:
            pass


def load_caps(repo: Path, cache: Path, sha: str) -> list:
    import fcntl
    import time
    hit = cache / f"{sha}.json"
    caps = _read_cache(hit)
    if caps is not None:
        return caps
    err = cache / f"{sha}.err"

    def earlier():
        line = (err.read_text(errors="ignore").splitlines() or ["unknown"])[0]
        return MapUnavailable(f"map for {sha[:7]} failed earlier: {line}")

    if err.is_file():
        raise earlier()
    try:
        cache.mkdir(parents=True, exist_ok=True)
        lock = open(cache / ".lock", "w")
    except OSError as exc:
        raise MapUnavailable(f"cache dir {cache} unusable: {type(exc).__name__}")
    with lock:
        # Two sessions creating scripts at once must not both run the generator
        # and race on the cache dir: one lock, re-check after taking it.
        fcntl.flock(lock, fcntl.LOCK_EX)
        caps = _read_cache(hit)
        if caps is not None:
            return caps
        if err.is_file():
            raise earlier()
        _prune(cache)
        try:
            caps = _generate(repo, cache, sha)
        except MapUnavailable as exc:
            _atomic_write(err, f"{exc}\n")
            _prune(cache)
            raise
        _atomic_write(hit, json.dumps({
            "sha": sha, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "generator": GEN_REL, "capabilities": caps}))
        _prune(cache)
        return caps


# --- overlap ------------------------------------------------------------------


def views(caps: list) -> list:
    """One view per kipi path: label, slug ids, tokens, rank."""
    by_path = {}
    for c in caps:
        if not isinstance(c, dict):
            continue
        name = re.sub(r"\s*\[[0-9a-f]{6}\]$", "", c.get("name") or "")
        entry, layer = c.get("entry") or "", c.get("layer") or ""
        if " -> " in entry:
            # A hook's entry is ".claude/settings.json -> <script> [Event/Matcher]".
            entry = entry.split(" -> ", 1)[1].split(" [")[0]
            entry = re.sub(r"^\$\{?\w+\}?/", "", entry)
        if layer.startswith("L3"):
            # Drop "(PostToolUse/Edit|Write)": "post" matched 30+ hooks by event name.
            name = re.sub(r"\s*\(.*\)$", "", name)
        label = re.sub(r"\.(py|sh)$", "", name.partition(" ")[2] or name)
        rank = LAYER_RANK.get(layer[:2], 9)
        prev = by_path.get(entry)
        if prev and prev["rank"] <= rank:
            continue
        base = os.path.basename(entry.rstrip("/")).lower()
        ids = {slug(label), slug(name), entry.lower().rstrip("/")}
        if base not in ("skill.md", "readme.md"):
            ids |= {base, os.path.splitext(base)[0], slug(os.path.splitext(base)[0])}
        by_path[entry] = {"label": slug(label) or slug(name), "entry": entry, "rank": rank,
                          "ids": ids - {""}, "tokens": tokens(label) | tokens(entry)}
    return list(by_path.values())


def first_doc_line(content: str) -> str:
    lines = content.splitlines()[:HEADER_LINES]
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]
    in_doc = False
    for raw in lines:
        s = raw.strip()
        if not s or REUSES_RE.search(s) or CHECKED_RE.search(s):
            continue
        if in_doc:
            return s.strip("\"'")
        q = next((q for q in ('"""', "'''") if s.lstrip("rRuU").startswith(q)), None)
        if q:
            rest = s.lstrip("rRuU")[3:].split(q)[0].strip()
            if rest:
                return rest
            in_doc = True
            continue
        if s.startswith(("#", "//", "/*", "*")):
            text = s.lstrip("#/* ").strip()
            if not text or "coding" in text or text.startswith(("shellcheck", "eslint", "@ts-")):
                continue
            return text
        if s.startswith(("from __future__", "'use strict'", '"use strict"', "set -")):
            continue
        return ""
    return ""


def overlaps(path: str, content: str, caps: list) -> list:
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", os.path.basename(path))
    base_t = tokens(stem)
    doc_t = tokens(first_doc_line(content)) - base_t
    hits = []
    for v in views(caps):
        score = 2 * len(base_t & v["tokens"]) + len(doc_t & v["tokens"])
        if score:
            hits.append((-score, v["rank"], v["entry"], v, sorted((base_t | doc_t) & v["tokens"])))
    hits.sort(key=lambda h: h[:3])
    return [dict(h[3], shared=h[4]) for h in hits[:MAX_LISTED]]


# --- the decision -------------------------------------------------------------


def norm_kipi_path(p: str, repo: Path) -> str:
    """A citation as a path relative to the kipi-system root.

    Review of #755: a trailing period or comment closer, a kipi-system/ prefix, and
    an absolute path from a kipi worktree or the marketplace clone were all refused
    as "does not exist", though each named a real kipi file."""
    p = p.strip().strip("`'\",;()[]")
    p = re.sub(r"(?:\*/|-->|[.:;,])+$", "", p)
    if p.startswith("~"):
        p = os.path.expanduser(p)
    if p.startswith("/"):
        top = kipi_top(p, repo)
        if top is not None:
            try:
                return Path(os.path.realpath(p)).relative_to(os.path.realpath(top)).as_posix()
            except ValueError:
                pass
        for pre in (os.path.realpath(repo) + "/", str(repo) + "/",
                    os.path.expanduser(DEFAULT_REPO) + "/"):
            if p.startswith(pre):
                return p[len(pre):].rstrip("/")
        return p
    for pre in ("./", "kipi-system/"):
        if p.startswith(pre):
            p = p[len(pre):]
    return p.rstrip("/")


def warn_open(msg: str):
    """A fail-open warning someone can see. On exit 0 Claude Code shows no stderr,
    so the same line also goes out as a hook systemMessage (review of #755)."""
    print(msg, file=sys.stderr)
    print(json.dumps({"systemMessage": msg}))


def block(path: str, why: str, listed: list, sha: str) -> int:
    out = [f"BLOCKED by reuse-gate ({RULE_ID}): {path} is a new script, and {why}", FOUNDER]
    if listed:
        out.append(f"kipi-system tools that overlap it (origin/main {sha[:7]}):")
        for v in listed:
            out.append(f"  - {v['label']}  {v['entry']}  (shared: {', '.join(v['shared'])})")
    else:
        out.append(f"No kipi-system capability overlaps its name or first doc line "
                   f"(origin/main {sha[:7]}).")
    out += [
        f"Put ONE of these in its first {HEADER_LINES} lines:",
        "    Reuses-kipi: <path in kipi-system>   (the kipi FILE this calls or extends; it must exist at origin/main)",
        "    Kipi-checked: <slug>, <slug> -- <why none fits>   (name every tool listed above, by slug or path)",
        "    Kipi-checked: none -- <reason>   (only when nothing is listed above)",
    ]
    print("\n".join(out), file=sys.stderr)
    return 2


def gate(tool: str, inp: dict, cwd: str) -> int:
    made = creation(tool, inp, cwd)
    if not made:
        return 0
    path, content = made
    if not is_script(path, content) or is_test_path(path) or is_temp(path):
        return 0
    repo = Path(os.path.expanduser(os.environ.get("KIPI_REUSE_GATE_REPO") or DEFAULT_REPO))
    if in_kipi_tree(path, repo):
        return 0
    cache = Path(os.path.expanduser(os.environ.get("KIPI_REUSE_GATE_CACHE") or DEFAULT_CACHE))
    try:
        sha = origin_main(repo)
        caps = load_caps(repo, cache, sha)
    except MapUnavailable as exc:
        warn_open(f"reuse-gate: kipi capability map unavailable ({exc}), failing open: "
                  f"{path} was not checked against kipi-system.")
        return 0
    listed = overlaps(path, content, caps)
    head = content.splitlines()[:HEADER_LINES]
    reuses = [m.group(1) for ln in head for m in [REUSES_RE.search(ln)] if m]
    checked = [m.group(1) for ln in head for m in [CHECKED_RE.search(ln)] if m]

    if reuses:
        missing = [r for r in reuses if not exists_at(repo, sha, norm_kipi_path(r, repo))]
        if missing:
            return block(path, f"Reuses-kipi names {', '.join(missing)}, which is not a file in "
                               f"kipi-system at origin/main {sha[:7]}.", listed, sha)
        return 0
    if not checked:
        return block(path, f"its first {HEADER_LINES} lines carry no Reuses-kipi or Kipi-checked "
                           "line.", listed, sha)
    items, reasons = set(), []
    for c in checked:
        parts = SEP_RE.split(c, 1)
        reason = parts[1].strip() if len(parts) > 1 else ""
        # The refusal's own template pasted back passed as a header (review of #755).
        if reason and not PLACEHOLDER_RE.fullmatch(reason):
            reasons.append(reason)
        for it in re.split(r"[,\s]+", parts[0]):
            it = norm_kipi_path(it, repo).lower()
            if it and not PLACEHOLDER_RE.fullmatch(it):
                items.add(it)
    if not reasons:
        return block(path, "its Kipi-checked line has no reason after `--`.", listed, sha)
    if not listed and "none" not in items:
        return block(path, "nothing in kipi-system overlaps it, so its header must say "
                           "`Kipi-checked: none -- <reason>`.", listed, sha)
    unnamed = [v for v in listed if not (v["ids"] & items)]
    if unnamed:
        return block(path, "its Kipi-checked line does not name: "
                           f"{', '.join(v['label'] for v in unnamed)}.", listed, sha)
    return 0


def main() -> int:
    if os.environ.get("REUSE_GATE_OFF") == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_input"), dict):
        return 0
    try:
        return gate(payload.get("tool_name") or "", payload["tool_input"], payload.get("cwd") or "")
    except Exception as exc:
        # Fail open, but not invisibly (new-view-gate's sp-df1f13a5 scar).
        warn_open(f"reuse-gate: internal error, failing open: {type(exc).__name__}: {exc}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
