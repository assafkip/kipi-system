#!/usr/bin/env python3
"""model_route.py -- the one reader of q-system/.q-system/model-routing.json (ASK-4013).

Which model a fleet job runs on is DATA, with the evidence beside each row. This
module classifies a ticket or a PR from things code can read (repo, changed or
DoR-named files, ticket text) and returns the model the table gives that class.

    model_route.py pick --job worker --issue ASK-123 [--repo SLUG] [--tree PATH]
    model_route.py pick --job review --files-from FILE [--repo SLUG]
    model_route.py pick --job second-runner
    model_route.py classify --files a.py b.sh [--repo SLUG] [--text "..."]

`pick` always prints one model id and exits 0. Every failure (unreadable table,
Linear unreachable, no file list) resolves to the table's Opus default and says
why on stderr. Why fail toward Opus: the founder's stated risk is code quality on
PRs and tickets, so the cheap model is the one a row has to earn, never the one a
broken read lands on.

Why one reader: before this, three call sites each carried a literal and the
worker's main run named none, so its model was whatever its parent exported.
test_model_routing.py fails when a governed site names a model again.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLE = HERE.parent / "model-routing.json"
# Last-resort id when the table itself cannot be read. It is the table's own
# default today; test_model_routing.py pins that the two agree.
FLOOR = "claude-opus-5"

CODE_EXT = re.compile(r"\.(py|sh|bash|js|mjs|ts|tsx|go|rb)$")
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test[_-][^/]*$|_test\.py$")


def load(table_path: Path | None = None) -> dict:
    return json.loads(Path(table_path or TABLE).read_text())


def _say(msg: str) -> None:
    print(f"model_route: {msg}", file=sys.stderr)


def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def dor_files(description: str) -> list:
    """Backticked paths on the DoR's Files field, in order. [] when there is none.

    linear-route.py's parser, not a second one (PR #664 round 1, minor): the first
    cut here needed a bullet before the next field, so on a bare-field DoR it read
    on into **Not doing:** and routed a ticket by the paths it must not touch."""
    return _load_script("linear_route", "linear-route.py").dor_file_paths(description or "")


_PROJECT_REF = re.compile(r"\$\{?CLAUDE_PROJECT_DIR\}?\"?/([\w./-]+\.(?:py|sh))")
_PLUGIN_REF = re.compile(r"\$\{?CLAUDE_PLUGIN_ROOT\}?\"?/([\w./-]+\.(?:py|sh))")


def _commands(node):
    if isinstance(node, dict):
        if isinstance(node.get("command"), str):
            yield node["command"]
        for v in node.values():
            yield from _commands(v)
    elif isinstance(node, list):
        for v in node:
            yield from _commands(v)


def wired_hooks(root) -> set:
    """Repo-relative paths of every script a hook config in `root` runs.

    From the configs, not from names (PR #664 round 1, major): this repo names
    its enforcement hooks *-lint.py, *-check.py, *-door.py, and a name matcher
    missed 38 of the 50 that .claude/settings.json wires."""
    root = Path(root)
    out = set()
    cfgs = [(root / ".claude" / "settings.json", None)]
    cfgs += [(p, p.parent.parent) for p in sorted(root.glob("plugins/*/hooks/hooks.json"))]
    for cfg, plugin in cfgs:
        try:
            data = json.loads(cfg.read_text())
        except (OSError, ValueError):
            continue
        for cmd in _commands(data.get("hooks", data)):
            out.update(_PROJECT_REF.findall(cmd))
            if plugin is not None:
                out.update(str((plugin / m).relative_to(root)) for m in _PLUGIN_REF.findall(cmd))
    return out


def classify(repo: str = "", files=(), text: str = "", table: dict | None = None,
             hooks: set | None = None) -> str:
    """The first class, in the table's risk order, whose rule matches.

    `hooks` is the set of scripts the repo's hook configs run (wired_hooks); a
    change to any of them is a guard change whatever the file is called."""
    t = table or load()
    files = [f for f in files if f]
    if not files:
        return "unknown"
    if hooks is None:
        hooks = wired_hooks(HERE.parents[2])
    code = [f for f in files if CODE_EXT.search(f) and not TEST_PATH.search(f)]
    for c in t["classes"]:
        rule = c["match"]
        if rule.get("wired_hooks") and any(f in hooks for f in files):
            return c["name"]
        if "path" in rule and any(re.search(rule["path"], f) for f in files):
            return c["name"]
        if "code_basename" in rule and any(re.search(rule["code_basename"], Path(f).name)
                                           for f in files if CODE_EXT.search(f)):
            return c["name"]
        if "text" in rule and re.search(rule["text"], text or "", re.I):
            return c["name"]
        if "repo" in rule and repo in rule["repo"]:
            return c["name"]
        if "code_files" in rule:
            lo, hi = rule["code_files"]
            if lo <= len(code) <= hi:
                return c["name"]
        if "all" in rule and all(re.search(rule["all"], f) for f in files):
            return c["name"]
    return "unknown"


def pick(job: str, cls: str = "*", table_path: Path | None = None) -> str:
    try:
        t = load(table_path)
    except (OSError, ValueError) as exc:
        _say(f"table unreadable ({exc}); using {FLOOR}")
        return FLOOR
    spec = t.get("jobs", {}).get(job)
    if spec is None:
        _say(f"no job {job!r} in the table; using the default")
        return t["default"]
    rows = spec.get("classes")
    if rows is None:
        return spec["model"]
    row = rows.get(cls) or rows.get("unknown")
    return row["model"] if row else t["default"]


def _issue(ident: str) -> dict:
    """title and description of one issue, read-only, through linear-sync's graphql().

    Through linear-sync and not a URL of its own: the worker's tests point
    KIPI_LINEAR_API_URL at a local fake, and this read must follow them there
    rather than reach the live board from a test."""
    spec = importlib.util.spec_from_file_location("linear_sync", HERE / "linear-sync.py")
    ls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ls)
    data = ls.graphql("query($id:String!){issue(id:$id){title description}}", {"id": ident})
    return (data.get("data") or data).get("issue") or {}


def _diff_files(path: str) -> list:
    """Changed paths from a unified diff or a plain one-path-per-line list."""
    text = Path(path).read_text(errors="replace")
    heads = re.findall(r"^diff --git a/(\S+) b/", text, re.M)
    return heads or [l.strip() for l in text.splitlines() if l.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--job", required=True)
    p.add_argument("--issue")
    p.add_argument("--repo", default="")
    p.add_argument("--tree", help="the worker's tree, for the client-repo path rule")
    p.add_argument("--files-from")
    c = sub.add_parser("classify")
    c.add_argument("--files", nargs="*", default=[])
    c.add_argument("--repo", default="")
    c.add_argument("--text", default="")
    a = ap.parse_args(argv)
    if a.verb == "classify":
        print(classify(a.repo, a.files, a.text))
        return 0
    try:
        t = load()
    except (OSError, ValueError) as exc:
        _say(f"table unreadable ({exc}); using {FLOOR}")
        print(FLOOR)
        return 0
    if "classes" not in t["jobs"].get(a.job, {}):
        print(pick(a.job))
        return 0
    files, text, repo = [], "", a.repo
    # a tree under an engagement root is a client repo whatever its slug says
    if a.tree and any(m in a.tree for m in t.get("client_path_markers", [])):
        repo = "client-path"
    try:
        if a.files_from:
            files = _diff_files(a.files_from)
        elif a.issue:
            i = _issue(a.issue)
            text = f"{i.get('title') or ''}\n{i.get('description') or ''}"
            files = dor_files(i.get("description") or "")
    except Exception as exc:  # noqa: BLE001 -- any read failure is the Opus default, said aloud
        _say(f"could not read the {'diff' if a.files_from else 'issue'} ({type(exc).__name__}: {exc}); class unknown")
    # the hooks the TARGET repo wires, when the caller names its checkout
    hooks = wired_hooks(a.tree) if a.tree and Path(a.tree).is_dir() else None
    cls = classify(repo, files, text, t, hooks)
    model = pick(a.job, cls)
    _say(f"job={a.job} class={cls} files={len(files)} -> {model}")
    print(model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
