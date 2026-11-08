"""Part 3 of the Sonnet evaluation (ASK-4038): the non-code jobs, each through its OWN code.

Every job runs its real decision function on 10 real inputs from its own queue or
ledger, once per model, then a defined check compares the two. Nothing is written
to Linear: only read paths and the pure decision functions are called.

  alert-triage  linear-alert-triage.decide()        same PROMOTE/HOLD as Opus?
  dor           linear-dor-drafter.draft_one()      passes the drafter's own check, has
                                                    every DoR field, names real paths,
                                                    and a blind Opus judge rates it equal
  triage        linear-triage.judge_batch()         same category as Opus?
  lessons       lessons-distill.distill_with_claude passes the scrub gate and the lesson
                                                    validator, and a blind Opus judge rates it equal

The three lean_call jobs pass no --model today, so they run on the CLI default; the
run forces each arm's model by inserting --model into lean_call's argv.

At most 4 calls at a time, memory checked before each batch.

    part3_run.py <job> [--n 10]
"""
import concurrent.futures as cf
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import time

EVAL = os.path.expanduser(os.environ.get('KIPI_EVAL_DIR', '~/.config/kipi/eval'))  # results live outside the repo
OUT = os.path.join(EVAL, 'part3')
S = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts')
sys.path.insert(0, S)
MODELS = ['claude-opus-5', 'claude-sonnet-5-5']
JUDGE = 'claude-opus-5'
ROOTS = [os.path.expanduser(p) for p in ('~/projects/kipi-system', '~/projects/consulting', '~/projects/chief')]

import lean_call  # noqa: E402  the shared module every lean job imports
_orig_run = lean_call.run
FORCE = {'model': None}


def _forced_run(argv, *a, **k):
    if FORCE['model']:
        argv = [argv[0], '--model', FORCE['model'], *argv[1:]]
    return _orig_run(argv, *a, **k)


lean_call.run = _forced_run


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(S, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def mem_ok(floor=0.30):
    for _ in range(30):
        out = subprocess.run(['/usr/bin/memory_pressure'], capture_output=True, text=True, timeout=20).stdout
        m = re.search(r'System-wide memory free percentage:\s*(\d+)%', out)
        if m and int(m[1]) / 100 >= floor:
            return True
        print(f'waiting: memory {m[1] if m else "?"}% free, under {floor:.0%}', flush=True)
        time.sleep(60)
    return False


def pool(fn, items, workers=4):
    if not mem_ok():
        raise SystemExit('STOP: memory under the floor for 30 min')
    with cf.ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, items))


def save(job, rec):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f'{job}.jsonl'), 'a') as fh:
        fh.write(json.dumps(rec) + '\n')


def judge_pair(context, a, b, what):
    """Blind pairwise judge: Opus sees two outputs as A and B, never which model wrote which."""
    prompt = (f"You are judging two {what} written for the same input. They come from two writers; you are not told which.\n"
              f"Judge on: is it correct for the input, is it executable or usable as written, does it invent anything, "
              f"does it follow the stated format. Ignore length and style.\n"
              f"Answer with ONE line of JSON: {{\"better\": \"A\" | \"B\" | \"equal\", \"why\": \"one sentence\"}}.\n"
              f"\n=== INPUT\n{context[:6000]}\n\n=== A\n{a[:6000]}\n\n=== B\n{b[:6000]}\n")
    FORCE['model'] = None  # the judge names its model itself
    r = lean_call.run(['claude', '-p', prompt, '--model', JUDGE], capture_output=True, text=True, timeout=300,
                      stdin=subprocess.DEVNULL, env={k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY'})
    m = re.search(r'\{.*\}', r.stdout or '', re.S)
    try:
        return json.loads(m.group(0)) if m else {'better': None, 'why': (r.stdout or '')[:200]}
    except ValueError:
        return {'better': None, 'why': (r.stdout or '')[:200]}


# ---------------------------------------------------------------- alert-triage
def job_alert_triage(n):
    lat = load('linear_alert_triage', 'linear-alert-triage.py')
    ls = lat._load('linear_sync', 'linear-sync.py')
    p, _refused = lat.lane_pool(ls)
    p, _pre = lat.run_prepass(ls, p, False)   # apply=False: the pre-pass writes nothing
    batch = p[:n]
    res = {}
    for model in MODELS:
        lat.TRIAGE_MODEL = model
        t0 = time.time()
        res[model] = pool(lambda i: lat.decide(i), batch)
        print(f'alert-triage {model}: {round(time.time() - t0)}s', flush=True)
    agree = 0
    for k, i in enumerate(batch):
        o, s = res[MODELS[0]][k], res[MODELS[1]][k]
        same = bool(o and s and o[0] == s[0])
        agree += same
        save('alert-triage', dict(issue=i['identifier'], opus=o[0] if o else None, sonnet=s[0] if s else None,
                                  same=same, opus_body=(o[1][:600] if o else None), sonnet_body=(s[1][:600] if s else None)))
    print(f'alert-triage: same decision {agree} of {len(batch)}')


# ---------------------------------------------------------------- dor drafter
FIELDS = ('Outcome', 'Files', 'Check', 'Blast radius', 'Not doing')


def path_hits(body):
    paths = [p for p in re.findall(r'`([^`\s]+)`', body or '') if '/' in p and not p.startswith(('http', '~', '$'))]
    real = [p for p in paths if any(os.path.exists(os.path.join(r, p)) for r in ROOTS)]
    return len(real), len(paths)


def job_dor(n):
    dd = load('linear_dor_drafter', 'linear-dor-drafter.py')
    ls = dd._linear()
    tid = ls.graphql('query{teams(filter:{key:{eq:"%s"}}){nodes{id}}}' % dd.TEAM_KEY, {})["teams"]["nodes"][0]["id"]
    # The live queue held 3 items on 2026-11-08, all redrafts. So the inputs are 10
    # PAST tickets that reached Done with a DoR: the DoR section is cut out with the
    # drafter's own split_dor_section, which leaves the text a first draft starts from.
    q = """query($a:String){issues(first:50,after:$a,orderBy:updatedAt,filter:{
      project:{name:{eq:"kipi-system"}}, state:{type:{eq:"completed"}},
      description:{contains:"Definition of Ready"}}){nodes{identifier title description project{name}}}}"""
    nodes = (ls.graphql(q, {"a": None}).get("issues") or {}).get("nodes") or []
    plan = []
    for i in nodes:
        before, heading, _section, after = dd.split_dor_section(i.get("description") or "")
        stripped = (dd.strip_owned_marker(before).rstrip() + "\n\n" + after).strip()
        if heading and len(stripped) > 200:
            plan.append({**i, "description": stripped})
        if len(plan) >= n:
            break
    res = {}
    for model in MODELS:
        FORCE['model'] = model
        t0 = time.time()
        res[model] = pool(lambda i: dd.draft_one(i, 300), plan)
        print(f'dor {model}: {round(time.time() - t0)}s', flush=True)
    for k, i in enumerate(plan):
        (ob, oreason), (sb, sreason) = res[MODELS[0]][k], res[MODELS[1]][k]
        rec = dict(issue=i['identifier'])
        for tag, body, why in (('opus', ob, oreason), ('sonnet', sb, sreason)):
            rec[f'{tag}_passes_drafter_check'] = body is not None
            rec[f'{tag}_reason'] = why
            rec[f'{tag}_fields'] = [f for f in FIELDS if body and re.search(rf'\*\*{f}:?\*\*', body)]
            rec[f'{tag}_paths_real'], rec[f'{tag}_paths'] = path_hits(body)
            rec[f'{tag}_body'] = (body or '')[:4000]
        if ob and sb:
            flip = random.Random(i['identifier']).random() < 0.5
            a, b = (sb, ob) if flip else (ob, sb)
            v = judge_pair(f"Ticket {i['identifier']}: {i.get('title')}\n{(i.get('description') or '')[:4000]}", a, b,
                           'Definition of Ready sections')
            rec['judge'] = v
            rec['judge_sonnet_was'] = 'A' if flip else 'B'
            rec['sonnet_equal_or_better'] = v.get('better') in ('equal', rec['judge_sonnet_was'])
        save('dor', rec)
        print(f"dor {i['identifier']}: opus ok={ob is not None} sonnet ok={sb is not None} "
              f"fields o={len(rec['opus_fields'])} s={len(rec['sonnet_fields'])} judge={rec.get('judge', {}).get('better')}"
              f" sonnet_was={rec.get('judge_sonnet_was')}", flush=True)


# ---------------------------------------------------------------- linear-triage
def job_triage(n):
    lt = load('linear_triage', 'linear-triage.py')
    from pathlib import Path
    ls = lt._load(Path(S) / 'linear-sync.py', 'ls')
    team_id = ls.graphql('query{teams(filter:{key:{eq:"ASK"}}){nodes{id}}}', {})["teams"]["nodes"][0]["id"]
    issues = lt.fetch_open(ls, team_id, 'kipi-system')
    issues, _in_flight = lt.partition_in_flight(issues, lt.open_pr_by_issue(lt.fetch_open_prs()))
    batch = issues[:n]
    chunks = [batch[i:i + 6] for i in range(0, len(batch), 6)]
    res = {}
    for model in MODELS:
        FORCE['model'] = model
        t0 = time.time()
        got = pool(lambda c: lt.judge_batch(c, 300), chunks, workers=2)
        res[model] = {v['id']: v for vs, _why in got for v in vs}
        print(f'triage {model}: {round(time.time() - t0)}s, {len(res[model])} verdicts', flush=True)
    agree = 0
    for i in batch:
        o, s = res[MODELS[0]].get(i['identifier']), res[MODELS[1]].get(i['identifier'])
        same = bool(o and s and o['category'] == s['category'])
        agree += same
        save('triage', dict(issue=i['identifier'], opus=o and o['category'], sonnet=s and s['category'], same=same,
                            opus_why=o and o.get('why'), sonnet_why=s and s.get('why')))
    print(f'triage: same category {agree} of {len(batch)}')


# ---------------------------------------------------------------- lessons distill
def job_lessons(n):
    ld = load('lessons_distill', 'lessons-distill.py')
    repo = os.path.expanduser('~/projects/kipi-system')
    ledger = json.load(open(os.path.join(repo, 'lesson-candidates', '.processed.json')))
    instances = ld.load_instances(os.path.join(repo, 'instance-registry.json'))
    published = {h: v for h, v in ledger.items() if v.get('status') == 'published'}
    srcs = [(h, path, text) for _name, path, h, text in ld.new_sources(instances, {}) if h in published]
    srcs.sort(key=lambda s: (published[s[0]].get('date') or '', s[0]), reverse=True)
    # inputs already judged stay judged: the extension takes the next n unseen sources
    seen_path = os.path.join(OUT, 'lessons.jsonl')
    seen = {json.loads(l)['source'] for l in open(seen_path)} if os.path.exists(seen_path) else set()
    srcs = [s for s in srcs if s[0] not in seen][:n]
    roster = ld.scrub_mod.codenames_from_registry(os.path.join(repo, 'instance-registry.json'))
    val = load('lessons_validator', 'lessons-validator.py')
    res = {}
    for model in MODELS:
        FORCE['model'] = model
        t0 = time.time()
        res[model] = pool(lambda s: ld.distill_with_claude(ld.rca_title(s[2]), ld.structural_cause(s[2])), srcs, workers=2)
        print(f'lessons {model}: {round(time.time() - t0)}s', flush=True)

    def passes(d):
        if not d:
            return False, 'no valid distillation'
        scrubbed, _hits = ld.scrub_mod.scrub(f"{d['title']}\n{d['body']}", roster)
        if not ld.scrub_mod.is_clean(scrubbed, roster):
            return False, 'scrub gate: client-data signal left'
        if val.TOKEN_RE.search(d['title']) or d['kind'] not in val.ALLOWED_KINDS:
            return False, 'lessons-validator: title token or kind'
        return True, ''

    for k, (h, path, text) in enumerate(srcs):
        o, s = res[MODELS[0]][k], res[MODELS[1]][k]
        (op, owhy), (sp, swhy) = passes(o), passes(s)
        rec = dict(source=h, opus_pass=op, opus_why=owhy, sonnet_pass=sp, sonnet_why=swhy, opus=o, sonnet=s)
        if o and s:
            flip = random.Random(h).random() < 0.5
            fa = json.dumps(s if flip else o); fb = json.dumps(o if flip else s)
            v = judge_pair(f"{ld.rca_title(text)}\n{ld.structural_cause(text)[:3000]}", fa, fb,
                           'reusable how-only engineering lessons (no names, no paths, no specifics that identify the source)')
            rec['judge'] = v
            rec['judge_sonnet_was'] = 'A' if flip else 'B'
            rec['sonnet_equal_or_better'] = v.get('better') in ('equal', rec['judge_sonnet_was'])
        save('lessons', rec)
        print(f"lessons {h}: opus pass={op} sonnet pass={sp} judge={rec.get('judge', {}).get('better')} sonnet_was={rec.get('judge_sonnet_was')}", flush=True)


if __name__ == '__main__':
    job = sys.argv[1]
    n = int(sys.argv[sys.argv.index('--n') + 1]) if '--n' in sys.argv else 10
    {'alert-triage': job_alert_triage, 'dor': job_dor, 'triage': job_triage, 'lessons': job_lessons}[job](n)
