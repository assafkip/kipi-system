"""Summarise Part 3. Re-parses a judge answer whose JSON landed inside `why` (the first
parse took a greedy match across two objects)."""
import json, os, re
EVAL = os.path.expanduser(os.environ.get('KIPI_EVAL_DIR', '~/.config/kipi/eval'))  # results live outside the repo
OUT = os.path.join(EVAL, 'part3')


def judge_of(rec):
    j = rec.get('judge') or {}
    if j.get('better') in ('A', 'B', 'equal'):
        return j['better']
    m = re.search(r'"better"\s*:\s*"(A|B|equal)"', j.get('why') or '')
    return m[1] if m else None


def rows(name):
    p = os.path.join(OUT, f'{name}.jsonl')
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


summary = {}
for job in ('alert-triage', 'triage'):
    r = rows(job)
    summary[job] = {'n': len(r), 'same': sum(x['same'] for x in r),
                    'misses': [x['issue'] for x in r if not x['same']]}
for job in ('dor', 'lessons'):
    r = rows(job)
    judged = [x for x in r if judge_of(x)]
    son_better = sum(judge_of(x) == x['judge_sonnet_was'] for x in judged)
    equal = sum(judge_of(x) == 'equal' for x in judged)
    s = {'n': len(r), 'judged': len(judged), 'sonnet_better': son_better, 'equal': equal,
         'opus_better': len(judged) - son_better - equal}
    if job == 'dor':
        s['opus_passes_check'] = sum(x['opus_passes_drafter_check'] for x in r)
        s['sonnet_passes_check'] = sum(x['sonnet_passes_drafter_check'] for x in r)
        s['opus_paths_real'] = f"{sum(x['opus_paths_real'] for x in r)}/{sum(x['opus_paths'] for x in r)}"
        s['sonnet_paths_real'] = f"{sum(x['sonnet_paths_real'] for x in r)}/{sum(x['sonnet_paths'] for x in r)}"
    else:
        s['opus_passes_gate'] = sum(x['opus_pass'] for x in r)
        s['sonnet_passes_gate'] = sum(x['sonnet_pass'] for x in r)
    summary[job] = s
json.dump(summary, open(os.path.join(OUT, 'summary.json'), 'w'), indent=1)
print(json.dumps(summary, indent=1))
