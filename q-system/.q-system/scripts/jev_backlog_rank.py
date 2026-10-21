#!/usr/bin/env python3
"""ASK-2015: score Jev as a RANKER over the old Linear pile, against a free control.

The order of operations is the point. Jev is only allowed near the open pile if a
scored run shows it beating a control that costs nothing, and the control is given
every advantage before the comparison is made.

  score   build the answer key, score the free controls, score Jev, print metrics
  rank    order the open non-client pile -- REFUSES unless `score` passed the gate
  close   DRY RUN ONLY today. Writes the undo receipt for one verified batch;
          `--apply` refuses, because this module constructs no Linear client
  undo    PRINTS the restore plan for a closed batch. It restores nothing

The last two lines are deliberately narrow. Jev lost its gate, so no batch was
ever closed and the write half was never needed; a four-line contract at the top
of an 860-line module is what a reader trusts, so it says what the code does
rather than what the command is named after (round 2 review, PR #463).

Why a ranker and not a classifier: six prior runs of this vendor landed on one
pattern, "ordering works, cut points fail" (jev-evaluation-2026-09-21.md section 2).
So the headline metric here is AUC plus precision at the batch sizes a human will
actually verify, and every confidence floor prints minority-class recall beside it.
That last rule is not decoration: the email run printed accuracy 1.000 while
catching 0 of 41 replies (RULE-2026-09-19-A).

Why the gate margin is 0.05: Linear project routing was DROPPED on 2026-09-21 at
0.779 against a 0.745 grep control, on the grounds that the margin was "not worth
a vendor". That margin is therefore the documented floor for what does not count
as a win.

Client tickets never reach the vendor. The vendor's terms take a perpetual licence
over outputs, so the guard checks the project field AND the ticket text, because a
project-less ticket is not covered by a project list.

The client names themselves are NOT in this file. This repo is public, so the roots
live outside the tree in `~/.config/kipi/jev-client-roots`, and this module refuses
to run when that file is absent or empty.

That file is NOT the same list as `client-name-guard.py`'s `~/.config/kipi/
client-tokens`, and the difference is a measured scar rather than a preference.
On 2026-09-28 this module derived its roots from the commit guard's token list on
the reasoning that one list beats two. The guard's list answers "which names must
not go public"; three of the seven projects the DoR forbids sending were absent
from it, and the next scoring run put 18 tickets in front of the vendor, 6 of them
in a client project. Two questions with different consequences need two lists. The
guard's tokens are still read and UNIONED in, because a name that must not go
public is also a name that must not reach a vendor -- but the union can only widen
the refusal, never narrow it.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

HERE = Path(__file__).resolve().parent
QROOT = HERE.parents[1]                      # q-system/
RUN_DIR = QROOT / "output" / "jev-backlog-rank-2026-09-28"
API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"                          # pinned, never "latest"
STATE_CHARS = 1500                            # accuracy drops as state grows
WINDOW_DAYS = 45
MIN_MARGIN = 0.05
CLOSE_LABEL = "closed:jev-batch"
USD_PER_MTOK = 0.042                          # vendor list price
TEAM_KEY = "ASK"

CUT_FLOORS = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95)

MIN_ROOT_CHARS = 3            # a shorter root refuses; it never drops in silence
MIN_SCORED_CASES = 50         # below this the AUC is a rumour, not a verdict
MAX_ERROR_RATE = 0.05         # above this the scored set is a survivor sample

# Both outside this public repo. ROOTS_FILE is authoritative and required; the
# commit guard's token list is unioned in and is optional.
ROOTS_FILE = Path.home() / ".config" / "kipi" / "jev-client-roots"
CLIENT_GUARD = HERE / "client-name-guard.py"


class NotVerified(Exception):
    """A batch reached close() without Sana having verified it."""


class ClientTicket(Exception):
    """A client ticket reached a path that must never touch one."""


class NoReceipt(Exception):
    """undo was asked for a batch that has no receipt on disk."""


class GateNotPassed(Exception):
    """rank/close was asked for before Jev beat the control."""


class Case(NamedTuple):
    ident: str
    title: str
    desc: str
    label: int          # 1 = should be closed, 0 = should be kept
    source: str         # "sana" | "state"
    age_days: float
    is_alert: bool
    project: str


# --------------------------------------------------------------------------- #
# client guard
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_\-/]+", " ", (s or "").lower())).strip()


_ROOTS = None


def _read_roots_file(path: Path):
    """The REQUIRED roots, one per line. Comments and blanks out, nothing else.

    A line too short to be a usable root REFUSES rather than being dropped. An
    earlier version skipped it silently, which is the 2026-09-28 failure class
    exactly: the list still has entries so the empty-list refusal never fires,
    and the project behind the dropped line reaches the vendor. The message
    names the LINE NUMBER and never the content -- this repo is public.
    """
    if not path.exists():
        return []
    out = []
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = _norm(raw.split("#", 1)[0])
        if not line:
            continue
        if len(line) < MIN_ROOT_CHARS:
            raise SystemExit(
                f"{path}:{n}: client root is shorter than {MIN_ROOT_CHARS} "
                "characters. Refusing to run rather than dropping it: a dropped "
                "root is a client project whose tickets reach the vendor. "
                "Lengthen the root, or delete the line if it is not a client.")
        out.append(line)
    return out


def _guard_tokens():
    """The commit guard's tokens, unioned in. OPTIONAL, and never narrowing.

    Absent or unreadable is a no-op here: this list widens the refusal, and the
    required list is ROOTS_FILE. Swallowing the error is deliberate and narrow --
    it cannot reduce coverage, only fail to add to it.
    """
    try:
        sp = importlib.util.spec_from_file_location("cng", CLIENT_GUARD)
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        return [_norm(t) for t in (m.load_tokens() or [])]
    except Exception:                                    # noqa: BLE001
        print(f"WARN: could not read {CLIENT_GUARD.name} tokens; "
              f"running on {ROOTS_FILE} alone", file=sys.stderr)
        return []


def client_roots():
    """Every client name root, cached. Union of ROOTS_FILE and the guard's tokens.

    FAILS CLOSED on ROOTS_FILE. No list means no guard, and no guard means client
    text reaching a vendor whose terms take a perpetual licence over outputs.
    """
    global _ROOTS
    if _ROOTS is None:
        required = _read_roots_file(ROOTS_FILE)
        if not required:
            raise SystemExit(
                f"no client roots at {ROOTS_FILE}; refusing to run. One normalised "
                "root per line, the client projects that must never reach the "
                "vendor. Without it nothing stops client text being sent.")
        _ROOTS = tuple(sorted({r for r in required + _guard_tokens() if r}))
    return _ROOTS


def is_client(issue: dict) -> bool:
    """True when a ticket belongs to, or talks about, one of the client projects.

    Both halves are load-bearing. 510 of 2164 ASK tickets carry no project at all,
    so a project-only guard would leak client content to the vendor. A false
    positive here only costs one ticket of coverage; a false negative sends client
    text under a perpetual output licence, so the check errs toward client.

    Both halves match by SUBSTRING for that reason. A prefix matcher on the
    project field reads as tighter and is the wrong direction: "Q4 Acme Foundry
    migration" and "Migration for Acme Foundry" both name the client and neither
    starts with the root. That asymmetry shipped in this file once (round 2
    review, PR #463) and no test or mutant could see it, because the sweep pinned
    that a project check exists and never pinned its width.
    """
    roots = client_roots()
    proj = _norm((issue.get("project") or {}).get("name", ""))
    if proj and any(r in proj for r in roots):
        return True
    text = _norm(f"{issue.get('title', '')} {issue.get('description', '') or ''}")
    return any(r in text for r in roots)


# --------------------------------------------------------------------------- #
# answer key
# --------------------------------------------------------------------------- #
def _dt(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _is_alert(issue: dict) -> bool:
    return "<!-- kipi-alert-fingerprint:" in (issue.get("description") or "")


def _terminal_at(issue: dict):
    return _dt(issue.get("canceledAt")) or _dt(issue.get("completedAt"))


def _is_duplicate(issue: dict) -> bool:
    """A duplicate state, read from BOTH the type and the name.

    Team ASK emits type `duplicate`: 29 of 2164 issues, counted in the cached
    payload on 2026-09-28, every one of them named "Duplicate". So the type
    check alone is correct HERE and is not portable -- `duplicate` is not in
    Linear's documented type set, and a workspace whose Duplicate state is
    canceled-type would put all of them into the answer key labelled
    should-close. That is not a wrong label on a few rows, it is the headline
    AUC computed on a polluted key, with nothing failing.
    """
    st = issue.get("state") or {}
    return st.get("type") == "duplicate" or _norm(st.get("name", "")) == "duplicate"


def build_gold(issues, decisions, now=None, window_days=WINDOW_DAYS):
    """The answer key: Sana's rulings, then canceled-vs-worked inside the window.

    A Sana ruling outranks the board state. ASK-2015 names those 50-odd rulings as
    the key, and where a ruling and the state disagree the ruling is the judgment
    that was actually made about the ticket's value.

    `duplicate` is dropped on purpose (`_is_duplicate`, by type AND by name): it
    says two tickets describe one thing, not that the work was or was not worth
    doing. A Sana ruling on one still counts -- that is an explicit judgment.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    cut = now - dt.timedelta(days=window_days)
    ruling = {}
    for d in decisions:
        if d.get("kind") != "sana_decision":
            continue
        act = d.get("action")
        if act in ("close", "keep"):
            ruling[d["issue"]] = 1 if act == "close" else 0

    out = []
    for i in issues:
        if is_client(i):
            continue
        ident = i["identifier"]
        created = _dt(i.get("createdAt"))
        age = (now - created).total_seconds() / 86400 if created else 0.0
        common = dict(ident=ident, title=i.get("title") or "",
                      desc=i.get("description") or "", age_days=age,
                      is_alert=_is_alert(i),
                      project=(i.get("project") or {}).get("name") or "")
        if ident in ruling:
            out.append(Case(label=ruling[ident], source="sana", **common))
            continue
        stype = (i.get("state") or {}).get("type")
        if _is_duplicate(i) or stype not in ("canceled", "completed"):
            continue
        tat = _terminal_at(i)
        if not tat or tat < cut:
            continue
        out.append(Case(label=1 if stype == "canceled" else 0, source="state", **common))
    return out


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def auc(scores, labels):
    """P(a random positive outranks a random negative), ties counted as half.

    Ties at half credit are what make a constant scorer read 0.500 instead of
    accidentally winning; a control that returns one value for a whole group
    would otherwise look decisive.
    """
    pos = [s for s, l in zip(scores, labels) if l == 1]
    neg = [s for s, l in zip(scores, labels) if l == 0]
    if not pos or not neg:
        return None
    wins = sum((1.0 if p > n else 0.5 if p == n else 0.0) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def precision_at_k(ranked, labels, k):
    """Share of the top k that really should be closed. This is the batch metric.

    Undefined when the population is shorter than k, rather than a number under
    a label it does not have. "top 100" computed over 3 cases is a different
    statistic wearing the same name, and it is what a human reads when deciding
    how large a batch to verify.
    """
    if k <= 0 or len(ranked) < k:
        return None
    top = ranked[:k]
    return sum(labels[i] for i in top) / len(top)


def minority_class(labels):
    c = collections.Counter(labels.values() if isinstance(labels, dict) else labels)
    if len(c) < 2:
        return None
    return min(c, key=lambda k: (c[k], k))


def cutpoint_table(scores: dict, labels: dict, floors=CUT_FLOORS):
    """One row per confidence floor, each carrying minority-class recall.

    RULE-2026-09-19-A: a floor reported without minority recall is not reported.
    The email run printed accuracy 1.000 at a floor that caught 0 of 41 replies.
    """
    idents = [i for i in scores if i in labels]
    mc = minority_class({i: labels[i] for i in idents})
    rows = []
    for f in floors:
        sel = [i for i in idents if scores[i] >= f]
        n_min = sum(1 for i in idents if labels[i] == mc) if mc is not None else 0
        if mc is None or n_min == 0:
            rec = None
        elif mc == 1:
            rec = sum(1 for i in sel if labels[i] == 1) / n_min
        else:
            unsel = set(idents) - set(sel)
            rec = sum(1 for i in unsel if labels[i] == 0) / n_min
        rows.append({
            "floor": f,
            "n_selected": len(sel),
            "share_selected": (len(sel) / len(idents)) if idents else None,
            "precision": (sum(labels[i] for i in sel) / len(sel)) if sel else None,
            "minority_class": mc,
            "minority_n": n_min,
            "minority_recall": rec,
        })
    return rows


def render_cutpoints(rows) -> str:
    """Header names minority recall so no row can be quoted without it."""
    mc = rows[0]["minority_class"] if rows else None
    lab = {1: "should-close", 0: "should-keep"}.get(mc, "n/a")
    out = [f"floor | selected | share | precision | minority recall "
           f"(minority class = {mc} / {lab}, n={rows[0]['minority_n'] if rows else 0})"]
    for r in rows:
        def f(v, d=3):
            return "n/a" if v is None else f"{v:.{d}f}"
        out.append(f"  {r['floor']:4.2f} | {r['n_selected']:5d} | {f(r['share_selected'])}"
                   f" | {f(r['precision'])} | {f(r['minority_recall'])}")
    return "\n".join(out)


def beats_control(jev_auc, control_auc, margin=MIN_MARGIN):
    """The gate. Returns (passed, why).

    A tie is not a win. Beating a coin flip is not a win either. And the margin
    floor is the routing run's own numbers: 0.779 against 0.745 was judged not
    worth a vendor on 2026-09-21, so anything at or under that gap fails here.
    """
    if jev_auc is None:
        return False, "jev AUC undefined (one class only)"
    bar = max(control_auc if control_auc is not None else 0.0, 0.5) + margin
    if jev_auc > bar:
        return True, f"jev {jev_auc:.3f} > bar {bar:.3f} (control {control_auc}, margin {margin})"
    return False, (f"jev {jev_auc:.3f} does not clear bar {bar:.3f} "
                   f"(control {control_auc}, margin {margin})")


def gate_verdict(jev_auc, control_auc, n_scored, n_cases, n_errors,
                 margin=MIN_MARGIN, min_cases=MIN_SCORED_CASES,
                 max_error_rate=MAX_ERROR_RATE):
    """beats_control, behind two floors on the SUBSET that produced the numbers.

    Both floors can only force a FAIL; neither can grant a pass. They exist
    because a comparison is only as good as the set it ran on, and the set
    shrinks silently: a vendor error drops a ticket out of the scored pile, and
    an AUC over the survivors reads like an AUC over the pile. Two cases of 530
    can read 1.000, and a pass here opens `rank`, which sends the whole open
    backlog to a vendor holding a perpetual licence over outputs.
    """
    if n_scored < min_cases:
        return False, (f"only {n_scored} of {n_cases} cases scored; floor is "
                       f"{min_cases}. A verdict on this few is not a verdict")
    rate = (n_errors / n_cases) if n_cases else 1.0
    if rate > max_error_rate:
        return False, (f"vendor error rate {rate:.3f} is over the "
                       f"{max_error_rate:.3f} ceiling ({n_errors} of {n_cases}); "
                       "the scored set is a survivor sample, not the answer key")
    return beats_control(jev_auc, control_auc, margin)


# --------------------------------------------------------------------------- #
# free controls
# --------------------------------------------------------------------------- #
STALE_WORDS = ("failed", "failing", "exit 1", "red", "drift", "stale", "broke",
               "broken", "no longer", "retired", "dead")


def control_scores(cases, alert_weight):
    """The DoR's control: "is it an alert", plus age. Age normalised to [0,1]."""
    mx = max((c.age_days for c in cases), default=1.0) or 1.0
    return {c.ident: alert_weight * (1.0 if c.is_alert else 0.0) + c.age_days / mx
            for c in cases}


def best_control(cases, labels):
    """Sweep the alert weight and hand the control its best score.

    The control is free, so giving it the best of a weight sweep and making Jev
    beat THAT is the honest direction. A control tuned on the same data it is
    scored on is optimistic, which only makes the bar harder for the vendor.
    """
    best = None
    for w in (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 1e6):
        sc = control_scores(cases, w)
        a = auc([sc[c.ident] for c in cases], [labels[c.ident] for c in cases])
        if a is not None and (best is None or a > best[1]):
            best = (w, a, sc)
    return best


def keyword_scores(cases):
    """A second free baseline. Included because the routing claim died on exactly
    this: a grep control scored 0.745 against Jev's 0.779 and ended the idea."""
    out = {}
    for c in cases:
        t = f"{c.title} {c.desc}".lower()
        out[c.ident] = float(sum(1 for w in STALE_WORDS if w in t))
    return out


def majority_accuracy(labels):
    c = collections.Counter(labels.values())
    return c.most_common(1)[0][1] / len(labels) if labels else None


# --------------------------------------------------------------------------- #
# vendor
# --------------------------------------------------------------------------- #
QUESTION = {"type": "noul", "instructions": {"question":
            "Should this engineering ticket be closed without the work being done, "
            "because it is stale, already handled elsewhere, or not worth doing?"}}


def _key():
    k = os.environ.get("TYPESAFE_API_KEY")
    if k:
        return k.strip()
    p = Path.home() / ".config/kipi/typesafe.key"
    if not p.exists():
        raise SystemExit("no TYPESAFE_API_KEY and no ~/.config/kipi/typesafe.key")
    return p.read_text().strip()


def _state_of(case: Case) -> dict:
    return {"title": case.title, "description": case.desc[:STATE_CHARS]}


def _fingerprint(case: Case) -> str:
    """Cache key covers the model and the exact state sent, so a prompt or a
    truncation change cannot be served a stale answer."""
    blob = json.dumps({"m": MODEL, "q": QUESTION, "s": _state_of(case)}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _score_of(resp):
    """The p(close) inside a response, or None when there is not one."""
    a = ((resp or {}).get("answers") or {}).get("close") or {}
    v = a.get("noul")
    return None if v is None else float(v)


def _tokens_of(resp):
    return ((resp or {}).get("usage") or {}).get("input_tokens", 0)


def load_score_cache(cache_path: Path):
    """(usable, seen). ONLY a response carrying a score counts as a cache hit.

    Every row stays on disk as a receipt, including the errors. But an error is
    not an answer: treating one as a hit means a transient 503 removes that
    ticket from every future run, permanently and silently, and the gate then
    reports an AUC over the survivors as though the pile had been scored.

    A torn row is skipped and counted on stderr, the way load_decisions already
    does. This file is append-only from a thread pool, so a Ctrl-C or a second
    concurrent `score` block-buffering into the same handle leaves one partial
    line -- and an unguarded json.loads made that one byte cost every later run
    until a human opened the file in an editor.
    """
    usable, seen, torn = {}, {}, 0
    if not cache_path.exists():
        return usable, seen
    for line in cache_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            k = (r["id"], r["fp"])
        except (ValueError, KeyError, TypeError):
            torn += 1
            continue
        seen[k] = r["response"]
        if _score_of(r["response"]) is not None:
            usable[k] = r["response"]
    if torn:
        print(f"warning: skipped {torn} unparseable row(s) in {cache_path}; "
              "they will be re-sent", file=sys.stderr)
    return usable, seen


def _post(case: Case, key: str) -> dict:
    """One classify call, with its own retries. Returns the response or {"error"}."""
    body = json.dumps({"state": _state_of(case), "model": MODEL,
                       "questions": {"close": QUESTION}}).encode()
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                API, data=body,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.read()[:300]!r}"
            if e.code in (401, 422):
                # Fail loud, do not retry a rejected request into a quota hole.
                return {"error": last}
        except Exception as e:                           # noqa: BLE001
            last = str(e)
        time.sleep(2 ** attempt * 2)
    return {"error": last}


def jev_scores(cases, cache_path: Path, workers=6, verbose=True, send=None):
    """P(close) per ticket. Cached by (model, question, state); a receipt per call.

    `send` is the seam the tests use. The default is the real HTTP call, so a
    suite can exercise the cache and the accounting without a key and without
    reaching the vendor.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    usable, seen = load_score_cache(cache_path)
    if send is None:
        key = _key()

        def send(case):                                  # noqa: F811
            return _post(case, key)

    def ask(case):
        fp = _fingerprint(case)
        if (case.ident, fp) in usable:
            return None
        return case.ident, fp, send(case)

    sent, tok_run = 0, 0
    with ThreadPoolExecutor(workers) as ex, cache_path.open("a") as fh:
        for res in ex.map(ask, cases):
            if res is None:
                continue
            ident, fp, resp = res
            seen[(ident, fp)] = resp
            if _score_of(resp) is not None:
                usable[(ident, fp)] = resp
            fh.write(json.dumps({"id": ident, "fp": fp, "model": MODEL,
                                 "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                 "response": resp}) + "\n")
            sent += 1
            tok_run += _tokens_of(resp)
    if verbose:
        print(f"calls sent this run: {sent}")

    # Cost is reported two ways and never as the file's whole history: what this
    # run spent, and what scoring THESE cases cost including the cache hits.
    scores, errs, tok_cases = {}, [], 0
    for c in cases:
        k = (c.ident, _fingerprint(c))
        r = usable.get(k)
        if r is None:
            errs.append((c.ident, (seen.get(k) or {}).get("error") or "empty response"))
        else:
            scores[c.ident] = _score_of(r)
            tok_cases += _tokens_of(r)
    return scores, errs, {"sent": sent, "tokens_this_run": tok_run,
                          "tokens_for_cases": tok_cases}


# --------------------------------------------------------------------------- #
# Linear
# --------------------------------------------------------------------------- #
def _linear():
    sp = importlib.util.spec_from_file_location("th", HERE / "linear-triage-health.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m._load_linear()


ISSUES_Q = """query($after: String){issues(filter:{team:{key:{eq:"%s"}}},first:100,after:$after){
nodes{id identifier title description createdAt updatedAt completedAt canceledAt
 state{id name type} project{name} labels{nodes{name}}}
pageInfo{hasNextPage endCursor}}}""" % TEAM_KEY


def fetch_issues(ln=None, cache: Path | None = None, refresh=False):
    if cache and cache.exists() and not refresh:
        return json.loads(cache.read_text())
    ln = ln or _linear()
    rows, after = [], None
    while True:
        d = ln.graphql(ISSUES_Q, {"after": after})["issues"]
        rows += d["nodes"]
        if not d["pageInfo"]["hasNextPage"]:
            break
        after = d["pageInfo"]["endCursor"]
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rows))
    return rows


def load_decisions(path=None):
    p = Path(path or Path.home() / ".config/triage/observations.jsonl")
    if not p.exists():
        raise SystemExit(f"answer key missing: {p}")
    out = []
    for line in p.read_text().splitlines():
        if '"sana_decision"' not in line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:                                # noqa: BLE001
            continue
    return out


# --------------------------------------------------------------------------- #
# close / undo
# --------------------------------------------------------------------------- #
def close_batch(batch: dict, receipts_dir: Path, apply=False, client=None):
    """Close one already-verified batch, recording enough to put it back.

    Two refusals that are code, not prose: an unverified batch, and a client
    ticket. The receipt stores each ticket's PRE-close state id, because "it can
    be undone" means restoring the state it actually had, not guessing Backlog.
    """
    if not batch.get("verified"):
        raise NotVerified(f"batch {batch.get('batch')!r} carries verified={batch.get('verified')!r}")
    items = batch.get("items") or []
    for it in items:
        if is_client({"project": {"name": it.get("project", "")},
                      "title": it.get("title", ""), "description": it.get("desc", "")}):
            raise ClientTicket(f"{it.get('identifier')} is a client ticket")
    if apply and client is None:
        raise SystemExit("apply=True needs a Linear client")
    receipt = {
        "batch": batch["batch"],
        "label": CLOSE_LABEL,
        "applied": False,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "items": [{"identifier": it["identifier"],
                   "prior_state_id": it["state_id"],
                   "prior_state_name": it.get("state_name", ""),
                   "project": it.get("project", ""),
                   "applied": False} for it in items],
    }
    receipts_dir.mkdir(parents=True, exist_ok=True)
    path = receipts_dir / f"{batch['batch']}.json"

    def flush():
        path.write_text(json.dumps(receipt, indent=1))

    # The receipt lands BEFORE the first Linear write, and again after each one.
    # Order is the whole property: a close with no receipt is a ticket nobody can
    # put back, while a receipt with no close is a harmless no-op. A partial
    # failure therefore leaves an exact undo plan and a per-item record of which
    # tickets actually moved.
    flush()
    if apply:
        for it, row in zip(items, receipt["items"]):
            client(it)
            row["applied"] = True
            flush()
        receipt["applied"] = True
        flush()
    return receipt


def undo_plan(batch_id: str, receipts_dir: Path):
    p = receipts_dir / f"{batch_id}.json"
    if not p.exists():
        raise NoReceipt(f"no receipt for batch {batch_id!r} at {p}")
    rc = json.loads(p.read_text())
    return [{"identifier": it["identifier"], "state_id": it["prior_state_id"],
             "state_name": it["prior_state_name"]} for it in rc["items"]]


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
GATE_FILE = RUN_DIR / "gate.json"


def cmd_score(args):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    issues = fetch_issues(cache=RUN_DIR / "issues.json", refresh=args.refresh)
    decisions = load_decisions(args.observations)
    n_client = sum(1 for i in issues if is_client(i))
    n_client_proj = sum(1 for i in issues
                        if any(_norm((i.get("project") or {}).get("name", "")).startswith(r)
                               for r in client_roots()))
    cases = build_gold(issues, decisions)
    labels = {c.ident: c.label for c in cases}
    srcs = collections.Counter(c.source for c in cases)
    print(f"ASK issues fetched: {len(issues)}")
    print(f"client-excluded: {n_client} ({n_client_proj} by project, "
          f"{n_client - n_client_proj} by the text guard)")
    print(f"answer key: {len(cases)} cases | by source {dict(srcs)} | "
          f"close={sum(labels.values())} keep={len(labels) - sum(labels.values())}")
    if len(set(labels.values())) < 2:
        raise SystemExit("answer key has one class only; nothing to score")

    order = [c.ident for c in cases]
    maj = majority_accuracy(labels)
    bw, bauc, bsc = best_control(cases, labels)
    kw = keyword_scores(cases)
    kauc = auc([kw[i] for i in order], [labels[i] for i in order])
    print()
    print("FREE BASELINES")
    print(f"  majority class accuracy        : {maj:.3f}")
    print(f"  control (alert + age), AUC     : {bauc:.3f}   [best alert weight {bw}]")
    print(f"  keyword control, AUC           : {kauc:.3f}")
    for w in (0.0, 1e6):
        sc = control_scores(cases, w)
        a = auc([sc[i] for i in order], [labels[i] for i in order])
        tag = "age only" if w == 0.0 else "alert only, age as tiebreak"
        print(f"    {tag:30s}: {a:.3f}")

    jev, errs, usage = jev_scores(cases, RUN_DIR / "jev_raw.jsonl", verbose=True)
    print(f"jev scored: {len(jev)} | errors/unparsed: {len(errs)}")
    for i, e in errs[:5]:
        print(f"    ERROR {i}: {e}")
    scored = [c for c in cases if c.ident in jev]
    if not scored:
        raise SystemExit("jev returned nothing scoreable; refusing to report a number")
    jl = {c.ident: c.label for c in scored}
    jauc = auc([jev[c.ident] for c in scored], [c.label for c in scored])
    cauc_same = auc([bsc[c.ident] for c in scored], [c.label for c in scored])
    print()
    print("JEV vs CONTROL, on the same scored subset")
    print(f"  cases                          : {len(scored)}")
    print(f"  control (alert + age), AUC     : {cauc_same:.3f}")
    print(f"  jev {MODEL}, AUC          : {jauc:.3f}")
    ranked_j = sorted(jl, key=lambda i: -jev[i])
    ranked_c = sorted(jl, key=lambda i: -bsc[i])
    print("  precision at the batch sizes a human verifies:")
    for k in (20, 50, 100):
        pj, pc = precision_at_k(ranked_j, jl, k), precision_at_k(ranked_c, jl, k)
        if pj is None:
            print(f"    top {k:3d}: n/a, only {len(ranked_j)} cases scored")
        else:
            print(f"    top {k:3d}: jev {pj:.3f} | control {pc:.3f}")
    print()
    print("JEV CONFIDENCE FLOORS")
    print(render_cutpoints(cutpoint_table(jev, jl)))
    print()
    tok_run, tok_cases = usage["tokens_this_run"], usage["tokens_for_cases"]
    print(f"input tokens this run: {tok_run} | for these {len(scored)} cases: "
          f"{tok_cases} | cost usd: {round(tok_cases / 1e6 * USD_PER_MTOK, 4)}")

    passed, why = gate_verdict(jauc, cauc_same, len(scored), len(cases), len(errs))
    print()
    print(f"GATE: {'PASS' if passed else 'FAIL'} -- {why}")
    GATE_FILE.write_text(json.dumps({
        "at": dt.datetime.now(dt.timezone.utc).isoformat(), "model": MODEL,
        "cases": len(scored), "answer_key_cases": len(cases),
        "vendor_errors": len(errs),
        "error_rate": round(len(errs) / len(cases), 4) if cases else None,
        "min_cases": MIN_SCORED_CASES, "max_error_rate": MAX_ERROR_RATE,
        "jev_auc": jauc, "control_auc": cauc_same,
        "control_best_weight": bw, "keyword_auc": kauc, "majority_accuracy": maj,
        "margin": MIN_MARGIN, "passed": passed, "why": why,
        "precision_at": {str(k): precision_at_k(ranked_j, jl, k) for k in (20, 50, 100)},
        "cutpoints": cutpoint_table(jev, jl),
        "tokens_this_run": tok_run, "tokens_for_cases": tok_cases,
        "usd": round(tok_cases / 1e6 * USD_PER_MTOK, 4),
    }, indent=1))
    print(f"gate receipt: {GATE_FILE}")
    if not passed:
        print("FALLBACK (DoR): widen triage's backlog_old park rule. "
              "Jev is not used on the open pile.")
    return 0


def cmd_rank(args):
    if not GATE_FILE.exists():
        raise GateNotPassed(f"no gate receipt at {GATE_FILE}; run `score` first")
    gate = json.loads(GATE_FILE.read_text())
    if not gate.get("passed"):
        raise GateNotPassed(f"gate FAILED: {gate.get('why')}. "
                            "ASK-2015 allows ranking the open pile only on a pass.")
    issues = fetch_issues(cache=RUN_DIR / "issues.json", refresh=args.refresh)
    open_types = ("backlog", "unstarted", "started", "triage")
    now = dt.datetime.now(dt.timezone.utc)
    cases = []
    for i in issues:
        if is_client(i) or (i.get("state") or {}).get("type") not in open_types:
            continue
        created = _dt(i.get("createdAt"))
        cases.append(Case(ident=i["identifier"], title=i.get("title") or "",
                          desc=i.get("description") or "", label=-1, source="open",
                          age_days=(now - created).total_seconds() / 86400 if created else 0.0,
                          is_alert=_is_alert(i),
                          project=(i.get("project") or {}).get("name") or ""))
    print(f"open non-client tickets: {len(cases)}")
    jev, errs, usage = jev_scores(cases, RUN_DIR / "jev_open_raw.jsonl")
    print(f"scored {len(jev)} | errors {len(errs)} | usd "
          f"{round(usage['tokens_for_cases'] / 1e6 * USD_PER_MTOK, 4)}")
    ranked = sorted((c for c in cases if c.ident in jev), key=lambda c: -jev[c.ident])
    out = RUN_DIR / "open_ranked.jsonl"
    with out.open("w") as fh:
        for r, c in enumerate(ranked, 1):
            fh.write(json.dumps({"rank": r, "identifier": c.ident, "p_close": jev[c.ident],
                                 "project": c.project, "age_days": round(c.age_days, 1),
                                 "is_alert": c.is_alert, "title": c.title}) + "\n")
    print(f"wrote {out}")
    return 0


def cmd_close(args):
    if not GATE_FILE.exists() or not json.loads(GATE_FILE.read_text()).get("passed"):
        raise GateNotPassed("gate not passed; no close path is open")
    batch = json.loads(Path(args.batch).read_text())
    rc = close_batch(batch, RUN_DIR / "batches", apply=args.apply, client=None)
    print(json.dumps(rc, indent=1))
    return 0


def cmd_undo(args):
    print(json.dumps(undo_plan(args.batch_id, RUN_DIR / "batches"), indent=1))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score", help="score Jev against the free controls")
    s.add_argument("--observations", default=None)
    s.add_argument("--refresh", action="store_true", help="re-fetch Linear")
    s.set_defaults(fn=cmd_score)
    r = sub.add_parser("rank", help="rank the open pile (needs a passing gate)")
    r.add_argument("--refresh", action="store_true")
    r.set_defaults(fn=cmd_rank)
    c = sub.add_parser("close", help="write the undo receipt for one verified batch")
    c.add_argument("batch")
    c.add_argument("--apply", action="store_true",
                   help="refuses: no Linear client is constructed here")
    c.set_defaults(fn=cmd_close)
    u = sub.add_parser("undo", help="print the restore plan for a closed batch")
    u.add_argument("batch_id")
    u.set_defaults(fn=cmd_undo)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
