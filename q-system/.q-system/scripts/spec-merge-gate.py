#!/usr/bin/env python3
"""A PR that implements a dsse issue spec does not merge until that spec reads closed.

    spec-merge-gate.py <pr-number> [--dir <checkout>]

Run from (or with --dir) a checkout of the PR's repo; gh resolves the repo there.
Exit 0: allowed (silent). Exit 2: refused, one line on stdout naming the spec.
Exit 3: could not tell (a gh read failed). Every caller treats non-zero as no merge.

WHY (ASK-4947). chief PR #395 merged on 2026-11-14 while its spec
`.prd-os/issues/gs-runtime-checkout.md` still read `status: in-progress`.
kipi-dsse /issue-start (depends_on, kipi-dsse #745) then refused every issue that
depended on it, until a separate closeout PR (#433) closed the spec. No fleet merge
site looked at the spec. This is the one check they all call: pr-owner.py's
gh_write, pr-verdict-lib.sh's automerge_arm (linear-worker.sh, converge.sh,
rearm-degraded-approvals.sh) and lessons-daily.sh.

WHICH SPECS A PR IMPLEMENTS
- A spec file in the PR's diff, unless the diff removes it.
- A spec whose id the branch name or the title names, as a whole token.
- A spec whose id the body names, but only when it reads in-progress (or any
  status other than open or closed). A body cites specs it does not implement:
  "depends on X" (closed already) and "follow-up filed as Y" (open). Refusing on
  those would hold every PR that links a follow-up. An in-progress spec named in a
  body is the #395 shape exactly (its body named `gs-runtime-checkout`).

THE SPLIT EXEMPTION. /prd-split files new specs as `status: open` in a PR that
touches nothing but `.prd-os/`. A spec in the diff that reads open is not being
implemented when the PR is .prd-os-only, or when this PR adds the file (a code PR
filing its follow-up). An open spec the branch or title names is still refused:
that PR says it implements it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

SPEC_DIR = ".prd-os/issues/"
SPEC_RE = re.compile(r"^\.prd-os/issues/([^/]+)\.md$")


def spec_status(text: str) -> str:
    """The `status:` value in the leading frontmatter block, or "" when there is none."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        if line.strip() == "---":
            return ""
        m = re.match(r"^status:\s*(\S+)", line)
        if m:
            return m.group(1).strip("'\"").lower()
    return ""


def names(text: str, spec_id: str) -> bool:
    """True when spec_id appears in text as a whole token (ids carry - and _)."""
    return re.search(r"(?<![\w-])" + re.escape(spec_id) + r"(?![\w-])", text or "") is not None


def verdict(pr: dict, files: list[tuple[str, str]], spec_ids: set[str], read_status) -> str:
    """"" when the PR may merge, else the refusal line. Pure: read_status(id) -> status str.

    pr: {"number", "head", "branch", "title", "body"}. files: (status, path) from the
    PR's file list, status as GitHub names it (added, modified, removed, renamed).
    spec_ids: the spec ids that exist at the PR head.
    """
    prd_only = bool(files) and all(p.startswith(".prd-os/") for _, p in files)
    in_diff: dict[str, str] = {}
    for st, path in files:
        m = SPEC_RE.match(path)
        if m and st != "removed":
            in_diff[m.group(1)] = st
    named = {s for s in spec_ids if names(pr.get("branch", ""), s) or names(pr.get("title", ""), s)}
    in_body = {s for s in spec_ids if names(pr.get("body", ""), s)} - named - set(in_diff)

    bad = []
    for sid in sorted(set(in_diff) | named | in_body):
        status = read_status(sid)
        if status == "closed":
            continue
        if sid in in_body and status == "open":
            continue
        if sid in in_diff and sid not in named and status == "open" and (prd_only or in_diff[sid] == "added"):
            continue
        bad.append(f"{SPEC_DIR}{sid}.md reads status: {status or '(none)'}")
    if not bad:
        return ""
    return (f"spec-merge-gate: REFUSED PR #{pr['number']} at {pr['head'][:8]}: " + "; ".join(bad)
            + ". Close the spec (/issue-closeout) on this branch, then merge.")


# ---------------------------------------------------------------- gh reads


class CannotTell(Exception):
    pass


def gh(args: list[str], cwd: str) -> str:
    try:
        p = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=60, cwd=cwd,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CannotTell(f"gh {' '.join(args[:2])} could not run ({exc})")
    if p.returncode != 0:
        err = " ".join((p.stderr or p.stdout or "").split())[:200]
        if "HTTP 404" in err:
            raise FileNotFoundError(err)
        raise CannotTell(f"gh {' '.join(args[:3])} exited {p.returncode} ({err})")
    return p.stdout


def check(n: str, cwd: str) -> tuple[int, str]:
    # A REPO WITH NO SPEC DIR HAS NO SPEC TO HOLD. Asked of the checkout, with no
    # gh call: most fleet repos and every fake-gh test repo have no .prd-os/issues,
    # and a gh round trip there could only fail closed on a question with no
    # subject. Edge kept on purpose: a PR that creates a repo's first spec dir is
    # judged on the next repo that has one, since its new specs are added and open.
    if not os.path.isdir(os.path.join(cwd, SPEC_DIR)):
        return 0, ""
    try:
        view = json.loads(gh(["pr", "view", n, "--json", "number,headRefOid,headRefName,title,body"], cwd) or "{}")
        head = view.get("headRefOid") or ""
        if not head:
            raise CannotTell(f"gh pr view {n} gave no head commit")
        raw = gh(["api", "--paginate", f"repos/{{owner}}/{{repo}}/pulls/{n}/files",
                  "--jq", ".[] | [.status, .filename] | @tsv"], cwd)
        files = [tuple(line.split("\t", 1)) for line in raw.splitlines() if "\t" in line]
        try:
            listing = gh(["api", f"repos/{{owner}}/{{repo}}/contents/.prd-os/issues?ref={head}",
                          "--jq", ".[].name"], cwd)
        except FileNotFoundError:
            listing = ""  # no spec dir at the head: nothing to implement
        spec_ids = {x[:-3] for x in listing.split() if x.endswith(".md")}

        def read_status(sid: str) -> str:
            try:
                return spec_status(gh(["api", "-H", "Accept: application/vnd.github.raw",
                                       f"repos/{{owner}}/{{repo}}/contents/{SPEC_DIR}{sid}.md?ref={head}"], cwd))
            except FileNotFoundError:
                return "missing"

        pr = {"number": n, "head": head, "branch": view.get("headRefName") or "",
              "title": view.get("title") or "", "body": view.get("body") or ""}
        why = verdict(pr, files, spec_ids, read_status)
    except (CannotTell, FileNotFoundError, ValueError) as exc:
        return 3, f"spec-merge-gate: COULD NOT TELL for PR #{n}, so no merge: {exc}"
    return (2, why) if why else (0, "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pr")
    ap.add_argument("--dir", default=".")
    a = ap.parse_args(argv)
    # lessons-daily.sh holds the PR as the URL gh pr create printed.
    m = re.fullmatch(r"https://github\.com/[^/]+/[^/]+/pull/(\d+)/?", a.pr)
    if m:
        a.pr = m.group(1)
    if not a.pr.isdigit():
        print(f"spec-merge-gate: '{a.pr}' is not a PR number, so no merge")
        return 3
    rc, line = check(a.pr, a.dir)
    if line:
        print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main())
