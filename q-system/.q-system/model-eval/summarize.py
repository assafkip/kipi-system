"""Build q-system/.q-system/model-eval-evidence.json from the raw eval results (ASK-4038).

The evidence file is what model_route.decide() reads. It is DERIVED: every number
here comes from the result files under this directory, never typed by hand.

    summarize.py <repo-root>
"""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score_part1 as S1
import score_part3 as S3

EVAL = os.path.expanduser(os.environ.get('KIPI_EVAL_DIR', '~/.config/kipi/eval'))  # results live outside the repo


def part1():
    rows = []
    for f in sorted(glob.glob(os.path.join(EVAL, 'part1', 'results-*.jsonl'))):
        rows += [json.loads(l) for l in open(f)]
    matches = json.load(open(os.path.join(EVAL, 'part1', 'matches.json')))
    classes = json.load(open(os.path.join(EVAL, 'part1', 'classes.json')))
    skip = set(matches.get('not_reviewed_environment', {}))
    per = {}
    for r in rows:
        key = f"{r['repo']}:{r['pr']}"
        if key in skip:
            continue
        c = classes[key]
        d = per.setdefault(c, {'prs': 0, 'opus_majors': 0, 'caught': 0, 'opus_request_changes': 0,
                               'sonnet_approved_those': 0, 'sonnet_secs': []})
        d['prs'] += 1
        d['opus_majors'] += len(r['opus_majors'])
        d['caught'] += sum(1 for i in range(len(r['opus_majors'])) if matches.get(f'{key}#{i}'))
        if r['opus_verdict'] == 'REQUEST CHANGES':
            d['opus_request_changes'] += 1
            v = (r.get('verdict') or '')
            d['sonnet_approved_those'] += v.startswith('APPROVE')
        d['sonnet_secs'].append(r['secs'])
    for d in per.values():
        s = sorted(d.pop('sonnet_secs')); d['sonnet_median_secs'] = s[len(s) // 2]
    return {'model': 'claude-sonnet-5-5', 'baseline': 'claude-opus-5', 'per_class': per,
            # counts only: the evidence ships in a public repo and PR keys name client repos
            'not_reviewed_environment': len(skip),
            'check': 'Sonnet re-reviews the PR at the head sha Opus reviewed; a catch is the same defect raised at any severity (hand-read, part1/matches.json)'}


def part2():
    rows = []
    for f in sorted(glob.glob(os.path.join(EVAL, 'part2', 'results-*.jsonl'))):
        rows += [json.loads(l) for l in open(f)]
    # a judge that ran later (judge_missing.py) amends its arm; results stay append-only
    amend = os.path.join(EVAL, 'part2', 'judge-amend.jsonl')
    fixes = {(a['ticket'], a['arm']): a for a in map(json.loads, open(amend))} if os.path.exists(amend) else {}
    import part2_run as P2
    for r in rows:
        a = fixes.get((r['ticket'], r['arm']))
        if a:
            r['verdict'], r['findings'] = a['verdict'], a['findings']
        # re-read the saved review with the current parser: a heading-form verdict
        # ("## Verdict / APPROVE WITH NITS.") was recorded as none by the first one
        rv = os.path.join(EVAL, 'part2', 'ctx', r['token'], 'review.txt')
        if not a and r['committed'] and os.path.exists(rv) and os.path.getsize(rv):
            r['findings'], r['verdict'], _ok = P2.findings(open(rv, errors='replace').read())
    per = {}
    for r in rows:
        d = per.setdefault(r['cls'], {}).setdefault(r['arm'], {'runs': 0, 'committed': 0, 'tests_pass': 0, 'tests_fail': 0,
                                                                'r1_approve': 0, 'gating': 0, 'majors': 0, 'minors': 0,
                                                                'refused': 0})
        d['runs'] += 1
        d['committed'] += r['committed']
        d['refused'] += bool(r['refused'])
        d['tests_pass'] += r['tests_pass'] is True
        d['tests_fail'] += r['tests_pass'] is False
        d['r1_approve'] += (r['verdict'] or '').startswith('APPROVE')
        d['gating'] += sum(1 for x in r['findings'] if x['sev'] in ('blocker', 'major') and not x['nonblocking'])
        d['majors'] += sum(1 for x in r['findings'] if x['sev'] in ('blocker', 'major'))
        d['minors'] += sum(1 for x in r['findings'] if x['sev'] == 'minor')
    return {'models': {'sonnet': 'claude-sonnet-5-5', 'opus': 'claude-opus-5'}, 'judge': 'claude-opus-5 (blind: no model or branch in its prompt)',
            'per_class': per}


def part3():
    s = json.load(open(os.path.join(EVAL, 'part3', 'summary.json')))
    out = {}
    for job, key, kind in (('alert-triage', 'alert-triage', 'decision'), ('fleet-triage', 'triage', 'decision'),
                           ('dor-drafting', 'dor', 'content'), ('lesson-distill', 'lessons', 'content')):
        d = dict(s[key]); d['kind'] = kind
        if kind == 'content':
            d['sonnet_gate'] = d.pop('sonnet_passes_check', d.pop('sonnet_passes_gate', None))
            d['opus_gate'] = d.pop('opus_passes_check', d.pop('opus_passes_gate', None))
        out[job] = d
    return out


if __name__ == '__main__':
    root = sys.argv[1]
    ev = {'_': 'ASK-4038. Measured Sonnet vs Opus evidence, derived from the raw eval results by summarize.py; '
               'model_route.decide() reads it with the table rule. Do not edit by hand: re-run the eval.',
          'measured': '2026-11-08', 'review': part1(), 'worker': part2(), 'jobs': part3()}
    p = os.path.join(root, 'q-system', '.q-system', 'model-eval-evidence.json')
    with open(p, 'w') as fh:
        json.dump(ev, fh, indent=1, sort_keys=True)
        fh.write('\n')
    print(json.dumps({'review': {c: (d['caught'], d['opus_majors']) for c, d in ev['review']['per_class'].items()},
                      'jobs': {j: {k: v for k, v in d.items() if k in ('n', 'same', 'judged', 'sonnet_better', 'equal')} for j, d in ev['jobs'].items()},
                      'worker_classes': list(ev['worker']['per_class'])}, indent=1))
