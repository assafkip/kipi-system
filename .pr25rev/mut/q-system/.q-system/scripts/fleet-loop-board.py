#!/usr/bin/env python3
"""Fleet Loop Board generator: the AUDHD comprehension hedge for autonomous loops.

Deterministic replacement for a hand-authored dashboard (review finding F2,
2026-07-21): a hand-curated HTML board goes stale and re-curating it by hand is
exactly the "LLM-instruction over script" anti-pattern the founder bans. This
reads the real sources and emits the HTML, so the numbers cannot drift from
truth and the tile cannot disagree with the panel (finding F1).

Sources (single-source-of-truth, no re-derivation):
  - `git log --since` for what shipped and its conventional-commit type.
  - `open-loops.py --report` for open threads (it already unions open-loops.json
    with genuinely-deferred prd-os findings; do NOT reimplement that filter).
  - EXITS below for loop-exit health (mirrors .claude/rules/loop-exits.md).

Output: q-system/output/fleet-loop-board.html (gitignored, regenerable).
Publish: re-run, then republish to the SAME artifact URL via the Artifact tool.

QROOT = q-system/ ; REPO = repo root. stdlib only. Fail-loud on a broken source
(a silent empty board is worse than an error).
"""
import html
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

WINDOW_DAYS = 14
RECENT_CAP = 7

SCRIPT_DIR = Path(__file__).resolve().parent          # q-system/.q-system/scripts/
QROOT = SCRIPT_DIR.parent.parent                       # q-system/
REPO = QROOT.parent                                    # repo root
OUT = QROOT / "output" / "fleet-loop-board.html"
OPEN_LOOPS = SCRIPT_DIR / "open-loops.py"

# Conventional-commit types that are routine maintenance (not worth a line-read).
ROUTINE_TYPES = {"fix", "chore", "lessons", "docs", "test", "refactor", "style", "ci", "build"}

# The 8 exits, each with a single honest status. Tile counts and panel render
# from THIS ONE list, so they can never disagree (finding F1). Mirrors
# .claude/rules/loop-exits.md; keep the two in sync.
EXITS = [
    ("Goal met",     "solid", "prd gates run"),
    ("Turn cap",     "solid", "token-guard VOLUME_CEILING"),
    ("Budget",       "proxy", "call/rate proxy, no $ meter"),
    ("Wall clock",   "proxy", "timeout 1800, autonomous only"),
    ("No progress",  "solid", "6 detectors"),
    ("Human stop",   "solid", "deny-hook, no self-grant"),
    ("Error cap",    "solid", "3, env stops at 1"),
    ("External",     "solid", "heartbeat poll"),
]

TYPE_TAGS = {"fix": "fix", "lessons": "lessons", "feat": "feat", "content": "feat"}
RAMP = [100, 74, 50, 34, 22, 16]  # accent-mix opacity by volume rank


def commit_type(subject):
    m = re.match(r"^([a-z]+)(\([^)]*\))?:", subject)
    return m.group(1) if m else "other"


def clean_subject(subject):
    stripped = re.sub(r"^[a-z]+(\([^)]*\))?:\s*", "", subject)
    return stripped[:1].upper() + stripped[1:] if stripped else subject


def commit_base_url():
    try:
        url = subprocess.run(["git", "-C", str(REPO), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    if not url:
        return None
    return re.sub(r"\.git$", "", url.replace("git@github.com:", "https://github.com/"))


def collect_commits():
    since = (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()
    out = subprocess.run(
        ["git", "-C", str(REPO), "log", f"--since={since}",
         "--format=%h\x1f%cd\x1f%s", "--date=format:%b %d"],
        capture_output=True, text=True, timeout=15, check=True).stdout
    rows = []
    for line in out.splitlines():
        if line.count("\x1f") != 2:
            continue
        h, d, s = line.split("\x1f")
        rows.append({"hash": h, "date": d, "subject": s, "type": commit_type(s)})
    counts = {}
    for r in rows:
        counts[r["type"]] = counts.get(r["type"], 0) + 1
    notable = [r for r in rows if r["type"] not in ROUTINE_TYPES]
    return {"total": len(rows), "counts": counts, "recent": rows[:RECENT_CAP],
            "notable": notable}


def collect_threads():
    out = subprocess.run([sys.executable, str(OPEN_LOOPS), "--report"],
                         capture_output=True, text=True, timeout=20,
                         cwd=str(REPO), env={"CLAUDE_PROJECT_DIR": str(REPO),
                                             "PATH": "/usr/bin:/bin"}).stdout
    threads = []
    for line in out.splitlines():
        if not line.startswith("- [ ] "):
            continue
        body = line[len("- [ ] "):]
        title, _, note = body.partition(" -> ")
        needs = "[needs you]" in title
        title = title.replace("[needs you]", "").strip()
        m = re.search(r"(https?://[^\s)]+|github\.com/[^\s)]+)", title + " " + note)
        url = None
        if m:
            url = m.group(1).rstrip(".,;")
            if not url.startswith("http"):
                url = "https://" + url
        threads.append({"title": title, "note": note.strip(), "url": url, "needs": needs})
    return threads


# ---- rendering (each fragment its own function; assemble in render) ----

STYLE = r"""
:root{--bg:#F5F7F6;--surface:#FFFFFF;--surface-2:#EDF1F0;--ink:#16211F;--ink-soft:#566360;--ink-faint:#8A9793;--line:#DBE2E0;--accent:#1F8B9C;--good:#3E9E63;--warn:#B67A26;--crit:#C25B52;--mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;--sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--r:10px}
@media (prefers-color-scheme:dark){:root{--bg:#0E1518;--surface:#141E22;--surface-2:#1B272C;--ink:#E8EEEC;--ink-soft:#97A6A2;--ink-faint:#647471;--line:#263338;--accent:#3BB6C8;--good:#55BE83;--warn:#E0A24E;--crit:#DE7A70}}
:root[data-theme="dark"]{--bg:#0E1518;--surface:#141E22;--surface-2:#1B272C;--ink:#E8EEEC;--ink-soft:#97A6A2;--ink-faint:#647471;--line:#263338;--accent:#3BB6C8;--good:#55BE83;--warn:#E0A24E;--crit:#DE7A70}
:root[data-theme="light"]{--bg:#F5F7F6;--surface:#FFFFFF;--surface-2:#EDF1F0;--ink:#16211F;--ink-soft:#566360;--ink-faint:#8A9793;--line:#DBE2E0;--accent:#1F8B9C;--good:#3E9E63;--warn:#B67A26;--crit:#C25B52}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5;-webkit-font-smoothing:antialiased}
.board{max-width:940px;margin:0 auto;padding:clamp(20px,4vw,44px) clamp(16px,4vw,32px) 56px;display:flex;flex-direction:column;gap:22px}
.head{display:flex;flex-direction:column;gap:14px}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
h1{font-family:var(--mono);font-size:clamp(24px,4.4vw,34px);letter-spacing:-.01em;margin:0;text-wrap:balance}
.sub{color:var(--ink-soft);font-size:15px;max-width:62ch;margin:0}
.stamp{font-family:var(--mono);font-size:12px;color:var(--ink-faint)}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;display:flex;flex-direction:column;gap:4px}
.stat .n{font-family:var(--mono);font-size:30px;font-variant-numeric:tabular-nums;line-height:1;letter-spacing:-.02em}
.stat .n small{color:var(--ink-faint);font-size:.5em;letter-spacing:0}
.stat .k{font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint)}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:clamp(16px,3vw,24px);display:flex;flex-direction:column;gap:16px}
.panel>h2{font-family:var(--mono);font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-soft);margin:0;display:flex;align-items:baseline;gap:10px}
.panel>h2 .count{color:var(--ink-faint);font-size:12px}
.lede{font-size:15.5px;line-height:1.55;margin:0}.lede b{color:var(--accent);font-weight:600}
.vol{display:flex;flex-direction:column;gap:8px}
.vol-bar{display:flex;height:12px;border-radius:6px;overflow:hidden;background:var(--surface-2)}
.vol-bar span{display:block;height:100%}
.vol-key{display:flex;flex-wrap:wrap;gap:6px 16px;font-family:var(--mono);font-size:12px;color:var(--ink-soft)}
.vol-key i{display:inline-flex;align-items:center;gap:6px;font-style:normal}
.swatch{width:10px;height:10px;border-radius:3px;display:inline-block}
.vol-key b{color:var(--ink);font-variant-numeric:tabular-nums}
.ship li{list-style:none;display:grid;grid-template-columns:62px 1fr auto;gap:14px;align-items:baseline;padding:10px 0;border-top:1px solid var(--line)}
.ship li:first-child{border-top:none}
.ship .d{font-family:var(--mono);font-size:12px;color:var(--ink-faint);font-variant-numeric:tabular-nums}
.ship .t{font-size:14.5px}
.tag{font-family:var(--mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;padding:2px 7px;border-radius:20px;border:1px solid var(--line);color:var(--ink-soft);white-space:nowrap}
.tag.fix{color:var(--accent);border-color:color-mix(in srgb,var(--accent) 40%,var(--line))}
.tag.lessons{color:var(--good);border-color:color-mix(in srgb,var(--good) 40%,var(--line))}
.tag.feat{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 40%,var(--line))}
ul{margin:0;padding:0}
.look{display:flex;flex-direction:column;gap:8px;padding:14px 16px;border-radius:8px;background:color-mix(in srgb,var(--warn) 10%,var(--surface));border:1px solid color-mix(in srgb,var(--warn) 34%,var(--line))}
.look .lbl{font-family:var(--mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--warn)}
.look a{color:var(--ink);text-decoration:none;font-size:14px;display:flex;gap:10px;align-items:baseline}
.look a:hover .h{text-decoration:underline}
.look .h{font-family:var(--mono);font-size:12px;color:var(--warn)}
.threads{display:flex;flex-direction:column;gap:10px}
.thread{display:grid;grid-template-columns:auto 1fr;gap:12px;align-items:start;padding:12px 14px;background:var(--surface-2);border-radius:8px;border-left:3px solid var(--line)}
.thread.live{border-left-color:var(--warn)}.thread.parked{border-left-color:var(--ink-faint)}
.pill{font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;padding:3px 8px;border-radius:5px;white-space:nowrap;font-weight:600}
.pill.live{background:color-mix(in srgb,var(--warn) 20%,transparent);color:var(--warn)}
.pill.parked{background:var(--surface);color:var(--ink-faint);border:1px solid var(--line)}
.thread .name{font-weight:600;font-size:14px}.thread a.name{color:var(--warn);text-decoration:none}
.thread a.name:hover{text-decoration:underline}
.thread .note{color:var(--ink-soft);font-size:13px;display:block;margin-top:2px}
.needs{font-family:var(--mono);font-size:10px;color:var(--warn);letter-spacing:.04em}
.exits{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.exit{display:flex;flex-direction:column;gap:5px;padding:11px 12px;border-radius:8px;background:var(--surface-2);border-top:3px solid var(--good)}
.exit.proxy{border-top-color:var(--warn)}
.exit .en{font-family:var(--mono);font-size:12.5px;font-weight:600;display:flex;align-items:center;gap:6px}
.exit .es{font-family:var(--mono);font-size:10.5px;color:var(--ink-faint);letter-spacing:.03em}
.mk{font-family:var(--mono)}.mk.ok{color:var(--good)}.mk.px{color:var(--warn)}
.flag{display:grid;grid-template-columns:auto 1fr;gap:12px;align-items:start;padding:14px 16px;border-radius:8px;background:color-mix(in srgb,var(--warn) 12%,var(--surface));border:1px solid color-mix(in srgb,var(--warn) 40%,var(--line))}
.flag .icn{font-family:var(--mono);color:var(--warn);font-weight:700}
.flag .txt{font-size:13.5px}.flag .txt b{color:var(--warn)}
footer{font-family:var(--mono);font-size:11.5px;color:var(--ink-faint);line-height:1.7;border-top:1px solid var(--line);padding-top:16px}
footer code{color:var(--ink-soft)}
a:focus-visible,.thread a:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:3px}
@media (prefers-reduced-motion:no-preference){.dot{animation:none}}
@media (max-width:640px){.stats{grid-template-columns:1fr}.exits{grid-template-columns:repeat(2,1fr)}.ship li{grid-template-columns:54px 1fr}.ship .tag{grid-column:2;justify-self:start}}
"""


def esc(s):
    return html.escape(str(s))


def render_volume(counts):
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    total = sum(counts.values()) or 1
    bar, key = [], []
    for i, (typ, n) in enumerate(ranked):
        op = RAMP[i] if i < len(RAMP) else 12
        col = "var(--accent)" if op == 100 else f"color-mix(in srgb,var(--accent) {op}%,var(--surface-2))"
        pct = round(n / total * 100, 2)
        bar.append(f'<span style="width:{pct}%;background:{col}"></span>')
        key.append(f'<i><span class="swatch" style="background:{col}"></span>{esc(typ)} <b>{n}</b></i>')
    return f'<div class="vol"><div class="vol-bar">{"".join(bar)}</div><div class="vol-key">{"".join(key)}</div></div>'


def render_recent(recent):
    rows = []
    for c in recent:
        tag = TYPE_TAGS.get(c["type"], "")
        tag_html = f'<span class="tag {tag}">{esc(c["type"])}</span>' if tag else f'<span class="tag">{esc(c["type"])}</span>'
        rows.append(f'<li><span class="d">{esc(c["date"])}</span><span class="t">{esc(clean_subject(c["subject"]))}</span>{tag_html}</li>')
    return f'<ul class="ship">{"".join(rows)}</ul>'


def render_look(notable, base_url):
    if not notable:
        return ('<div class="look"><span class="lbl">Worth a look</span>'
                '<span style="font-size:14px;color:var(--ink-soft)">Nothing but routine maintenance shipped. No non-fix changes to read.</span></div>')
    items = []
    for c in notable:
        link = f'{base_url}/commit/{c["hash"]}' if base_url else "#"
        items.append(f'<a href="{esc(link)}" target="_blank" rel="noopener"><span class="h">{esc(c["hash"])}</span><span>{esc(clean_subject(c["subject"]))}</span></a>')
    return (f'<div class="look"><span class="lbl">Worth a look &middot; the {len(notable)} non-routine change(s) to actually read</span>{"".join(items)}</div>')


def render_threads(threads):
    live = sum(1 for t in threads if t["needs"])
    out = []
    for t in threads:
        cls = "live" if t["needs"] else "parked"
        pill = "Live" if t["needs"] else "Parked"
        needs = ' <span class="needs">&middot; needs you</span>' if t["needs"] else ""
        if t["url"]:
            name = f'<a class="name" href="{esc(t["url"])}" target="_blank" rel="noopener">{esc(t["title"])}</a>'
        else:
            name = f'<span class="name">{esc(t["title"])}</span>'
        out.append(f'<div class="thread {cls}"><span class="pill {cls}">{pill}</span>'
                   f'<div>{name}{needs}<span class="note">{esc(t["note"])}</span></div></div>')
    head = f'<h2>Open threads <span class="count">{live} live &middot; {len(threads) - live} parked</span></h2>'
    return f'<section class="panel">{head}<div class="threads">{"".join(out)}</div></section>'


def render_health():
    solid = sum(1 for _, s, _ in EXITS if s == "solid")
    proxy = len(EXITS) - solid
    cells = []
    for name, status, note in EXITS:
        if status == "solid":
            cells.append(f'<div class="exit"><span class="en"><span class="mk ok">&check;</span> {esc(name)}</span><span class="es">{esc(note)}</span></div>')
        else:
            cells.append(f'<div class="exit proxy"><span class="en"><span class="mk px">&asymp;</span> {esc(name)}</span><span class="es">{esc(note)}</span></div>')
    flag = ('<div class="flag"><span class="icn">!</span><div class="txt">'
            '<b>Accepted-change rate: not instrumented.</b> The heartbeat loop merges its own PRs, '
            'so there is no signal for what fraction of its output you would accept. A busy loop is '
            'not a winning loop. This board is the stand-in until that rate is measured.</div></div>')
    head = f'<h2>Loop health <span class="count">{solid} solid &middot; {proxy} on proxies</span></h2>'
    return solid, proxy, f'<section class="panel">{head}<div class="exits">{"".join(cells)}</div>{flag}</section>'


def render(data):
    c = data["commits"]
    threads = data["threads"]
    solid, proxy, health = render_health()
    counts = c["counts"]
    lede = (f'Last {WINDOW_DAYS} days: '
            + ", ".join(f'<b>{n}</b> {esc(t)}' for t, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True))
            + f'. The {len(c["notable"])} non-routine change(s) below are the ones worth actually reading, the rest is maintenance.')
    live = sum(1 for t in threads if t["needs"])
    return f"""<title>Fleet Loop Board</title>
<style>{STYLE}</style>
<div class="board">
<header class="head">
<div class="eyebrow">Autonomous fleet &middot; comprehension board</div>
<h1>What the loops did while you weren't reading</h1>
<p class="sub">A 30-second read of what your autonomous loops shipped, what's still open, and whether every loop can actually stop. Numbers are generated from git + the open-loops ledger, not hand-written.</p>
<div class="stamp">Generated {date.today().isoformat()} &middot; git log + open-loops.py</div>
</header>
<section class="stats">
<div class="stat"><span class="n">{c["total"]}</span><span class="k">Shipped / {WINDOW_DAYS} days</span></div>
<div class="stat"><span class="n">{len(threads)}</span><span class="k">Open threads</span></div>
<div class="stat"><span class="n">{solid}<small> / {len(EXITS)}</small></span><span class="k">Exits fully wired</span></div>
</section>
<section class="panel">
<h2>Shipped lately <span class="count">last {WINDOW_DAYS} days</span></h2>
<p class="lede">{lede}</p>
{render_volume(counts)}
{render_recent(c["recent"])}
{render_look(c["notable"], data["base_url"])}
</section>
{render_threads(threads)}
{health}
<footer>
Generated {date.today().isoformat()} from <code>git log --since={WINDOW_DAYS}d</code> + <code>open-loops.py --report</code>. Regenerate: <code>python3 q-system/.q-system/scripts/fleet-loop-board.py</code><br>
Framework: <code>.claude/rules/loop-exits.md</code> &middot; the 8 exits every loop is audited against.
</footer>
</div>
"""


def main():
    data = {
        "commits": collect_commits(),
        "threads": collect_threads(),
        "base_url": commit_base_url(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(data), encoding="utf-8")
    c = data["commits"]
    solid = sum(1 for _, s, _ in EXITS if s == "solid")
    print(f"[fleet-loop-board] wrote {OUT}")
    print(f"  shipped(14d)={c['total']}  open-threads={len(data['threads'])}  "
          f"exits={solid}/{len(EXITS)} solid  notable={len(c['notable'])}")


if __name__ == "__main__":
    main()
