"""Score Part 1: for each re-reviewed PR, which of Opus's majors Sonnet also raised.

Auto-match (then read by hand, the decision is recorded in matches.json):
  same file, and either the lines are within 30 of each other or the claims share
  enough content words. Severity is ignored for a catch: a defect Sonnet raised at
  any severity counts as seen; the report also says at what severity.
Extra majors: Sonnet majors/blockers that match no Opus finding at any severity.
"""
import glob, json, os, re, sys
EVAL = os.path.expanduser(os.environ.get('KIPI_EVAL_DIR', '~/.config/kipi/eval'))  # results live outside the repo
STOP = set('the a an of to in on is and or for that this it its be by with as at from not no a when so but are was if then than into only one'.split())


def opus_all(review_md):
    t = open(review_md, errors='replace').read()
    fb = re.search(r'FINDINGS:\s*\n(.*?)END FINDINGS', t, re.S)
    rows = []
    for l in (fb[1].splitlines() if fb else []):
        p = [x.strip() for x in l.strip().split('|')]
        if len(p) >= 3 and p[0] in ('blocker', 'major', 'minor', 'nit'):
            rows.append({'sev': p[0], 'claim': p[1], 'loc': p[2]})
    return rows


def loc(s):
    m = re.match(r'([^\s:]+?)(?::(\d+))?(?:[-:,]\d+)?(?:\s|$|\|)', (s or '').strip() + ' ')
    return (m[1], int(m[2]) if m and m[2] else None) if m else (s, None)


def words(s):
    return {w for w in re.findall(r'[a-z_][a-z0-9_.-]{2,}', (s or '').lower()) if w not in STOP}


def same(a, b):
    fa, la = loc(a['loc']); fb, lb = loc(b['loc'])
    if not fa or not fb or os.path.basename(fa) != os.path.basename(fb):
        return 0.0
    if la and lb and abs(la - lb) <= 30:
        return 1.0
    wa, wb = words(a['claim']), words(b['claim'])
    return len(wa & wb) / max(1, len(wa | wb))


def main():
    rows = []
    for f in sorted(glob.glob(os.path.join(EVAL, 'part1', 'results-*.jsonl'))):
        rows += [json.loads(l) for l in open(f)]
    manual = json.load(open(os.path.join(EVAL, 'part1', 'matches.json'))) if os.path.exists(os.path.join(EVAL, 'part1', 'matches.json')) else {}
    elig = {f"{e['repo']}:{e['pr']}": e for e in json.load(open(os.path.join(EVAL, 'eligible.json')))}
    tot_m = tot_c = tot_x = 0; secs = []; outs = []
    for r in rows:
        key = f"{r['repo']}:{r['pr']}"
        r['opus_review'] = elig[key]['review']
        son = r['findings']
        opus_full = opus_all(r['opus_review']) if r.get('opus_review') else []
        caught = []
        for i, om in enumerate(r['opus_majors']):
            override = manual.get(f'{key}#{i}')
            if override is not None:
                caught.append(override); continue
            best = max(son, key=lambda s: same(om, s), default=None)
            caught.append(best['sev'] if best and same(om, best) >= 0.2 else None)
        extra = [s for s in son if s['sev'] in ('major', 'blocker')
                 and not any(same(s, o) >= 0.2 for o in (opus_full or r['opus_majors']))]
        xover = manual.get(f'{key}#extra')
        nx = xover if isinstance(xover, int) else len(extra)
        tot_m += len(r['opus_majors']); tot_c += sum(c is not None for c in caught); tot_x += nx
        secs.append(r['secs']); outs.append((r['tokens'] or {}).get('out', 0))
        print(f"{key:26s} opus_majors={len(r['opus_majors'])} caught={sum(c is not None for c in caught)} "
              f"(as {caught}) sonnet_majors={sum(s['sev'] in ('major','blocker') for s in son)} extra={nx} "
              f"verdict={r['verdict']} vs opus {r['opus_verdict']} {r['secs']//60}m head_match={r['head'] == r['opus_head']}")
        if '-v' in sys.argv:
            for om, c in zip(r['opus_majors'], caught):
                print(f"    OPUS  {'HIT ' if c else 'MISS'} {om['loc']}: {om['claim'][:150]}")
            for s in son:
                print(f"    SONNET {s['sev']:6s} {s['loc']}: {s['claim'][:150]}")
    if rows:
        print(f"\nTOTAL {len(rows)} PRs: Sonnet caught {tot_c} of {tot_m} Opus majors; extra Sonnet majors {tot_x}; "
              f"median {sorted(secs)[len(secs)//2]/60:.1f} min/review; median output tokens {sorted(outs)[len(outs)//2]}")


if __name__ == '__main__':
    main()
