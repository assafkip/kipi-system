"""Part 1 of the Sonnet evaluation (ASK-4013 follow-up): reviewer recall.

For each picked PR, run the fleet reviewer (pr-review-agent.sh, normal review_worktree
path, no --post) with an explicit model, at the PR's head, which is the sha Opus
reviewed. ONE run at a time: the 2026-11-08 parallel fan-out filled the disk.
Each finished review is appended to results.jsonl at once, so a stop loses nothing.

    part1_run.py <eval-tree> <model> [--only repo:pr]
"""
import glob, json, os, re, subprocess, sys, time, shutil
EVAL = os.path.expanduser(os.environ.get('KIPI_EVAL_DIR', '~/.config/kipi/eval'))  # results live outside the repo
OUT = os.path.join(EVAL, 'part1')
# The PR list and local checkouts live in $KIPI_EVAL_DIR/part1-config.json, not here:
# this repo is public and the list names client engagement repos.
_CFG = json.load(open(os.path.join(EVAL, 'part1-config.json')))
LOCAL = _CFG['local']
PICK = [tuple(x) for x in _CFG['pick']]


def mem_free_frac():
    """The resource gate's own instrument (gate-locked/hooks/resource_gate.py): memory_pressure's free percentage."""
    out = subprocess.run(['/usr/bin/memory_pressure'], capture_output=True, text=True, timeout=20).stdout
    m = re.search(r'System-wide memory free percentage:\s*(\d+)%', out)
    return int(m[1]) / 100 if m else 0.0


def findings(md):
    t = open(md, errors='replace').read()
    fb = re.search(r'FINDINGS:\s*\n(.*?)END FINDINGS', t, re.S)
    rows = []
    for l in (fb[1].splitlines() if fb else []):
        p = [x.strip() for x in l.strip().split('|')]
        if len(p) >= 3 and p[0] in ('blocker', 'major', 'minor', 'nit'):
            rows.append({'sev': p[0], 'claim': p[1], 'loc': p[2], 'nonblocking': p[-1] == 'nonblocking'})
    # any casing and markup: "**VERDICT: X**", "## Verdict\n\nX.", "Verdict: **X**" (a heading form read as none)
    v = re.findall(r'(?i)verdict\W{0,12}(APPROVE WITH NITS|APPROVE|REQUEST CHANGES|BLOCK)', t)
    return rows, (v[-1] if v else None), bool(fb)


def usage_since(repo, pr, t0):
    """Tokens of the review session(s) for this PR's tree that started after t0, deduped on message id."""
    d = os.path.expanduser(f"~/.claude/projects/-Users-assafkipnis--config-kipi-review-trees-assafkip-{repo.replace('_', '-')}--pr-{pr}")
    seen, tot, model = set(), {'in': 0, 'out': 0, 'cw': 0, 'cr': 0}, None
    for f in glob.glob(d + '/*.jsonl'):
        if os.path.getmtime(f) < t0:
            continue
        for line in open(f, errors='replace'):
            try:
                r = json.loads(line)
            except Exception:
                continue
            m = r.get('message') or {}
            if r.get('type') != 'assistant' or not m.get('id') or m['id'] in seen:
                continue
            seen.add(m['id']); model = m.get('model') or model
            u = m.get('usage') or {}
            tot['in'] += u.get('input_tokens') or 0; tot['out'] += u.get('output_tokens') or 0
            tot['cw'] += u.get('cache_creation_input_tokens') or 0; tot['cr'] += u.get('cache_read_input_tokens') or 0
    return tot, model


def main():
    tree, model = sys.argv[1], sys.argv[2]
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    shard = sys.argv[sys.argv.index('--shard') + 1] if '--shard' in sys.argv else '0/1'
    si, sn = (int(x) for x in shard.split('/'))
    os.makedirs(OUT, exist_ok=True)
    # one results file per shard: each file has exactly one writer
    res_path = os.path.join(OUT, f'results-{si}of{sn}.jsonl' if '--claim' not in sys.argv else f'results-w{os.getpid()}.jsonl')
    done = {(r['repo'], r['pr'], r['model']) for r in map(json.loads, open(res_path))} if os.path.exists(res_path) else set()
    elig = {(r['repo'], r['pr']): r for r in json.load(open(os.path.join(EVAL, 'eligible.json')))}
    claims = os.path.join(OUT, 'claims')
    os.makedirs(claims, exist_ok=True)
    use_claims = '--claim' in sys.argv
    for n, (repo, pr) in enumerate(PICK):
        if not use_claims and n % sn != si:
            continue
        if only and only != f'{repo}:{pr}':
            continue
        if (repo, pr, model) in done:
            continue
        if use_claims:
            try:
                os.mkdir(os.path.join(claims, f'{repo}-{pr}'))  # atomic: exactly one worker wins a PR
            except FileExistsError:
                continue
        free = shutil.disk_usage(os.path.expanduser('~')).free / 2**30
        if free < 5:
            print(f'STOP: {free:.1f} GB free, under the 5 GB floor'); return 3
        # the fleet's resource gate refuses a new agent under 25% free memory; wait for it, 30 min max
        floor = float(os.environ.get('EVAL_MEM_FLOOR', '0.25'))
        for _ in range(30):
            if mem_free_frac() >= floor:
                break
            print(f'waiting: {mem_free_frac():.0%} memory free, under {floor:.0%}', flush=True)
            time.sleep(60)
        else:
            print('STOP: memory stayed under 25% free for 30 min'); return 4
        e = elig[(repo, pr)]
        outdir = os.path.join(OUT, 'reviews', model)
        os.makedirs(outdir, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY'}
        env['KIPI_REVIEW_OUT_DIR'] = outdir
        t0 = time.time()
        # stdout to a FILE, never a pipe: pr-review-agent.sh's run_bounded watchdog
        # `( sleep 2400; ... ) &` inherits stdout, so a captured pipe stays open for
        # the full 40 minutes after the review ends (measured 2026-11-08: a 90 s
        # review held its caller 40 min). wait() on the child is what we want.
        logp = os.path.join(OUT, 'logs', f'{repo}-{pr}-{model}.log')
        os.makedirs(os.path.dirname(logp), exist_ok=True)
        with open(logp, 'w') as lf:
            p = subprocess.run(['bash', os.path.join(tree, 'q-system/.q-system/scripts/pr-review-agent.sh'), str(pr),
                                '--issue', e.get('issue') or 'ASK-4013', '--repo', os.path.expanduser(LOCAL[repo]),
                                '--model', model], stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               env=env, timeout=3000)
        p.stdout = open(logp, errors='replace').read(); p.stderr = ''
        secs = round(time.time() - t0)
        mds = sorted(glob.glob(os.path.join(outdir, f'assafkip_{repo}__pr-{pr}-*.md')))
        rows, verdict, ok = findings(mds[-1]) if mds else ([], None, False)
        tok, seen_model = usage_since(repo, pr, t0)
        head = re.search(r'head sha under review: ([0-9a-f]{40})', p.stdout + p.stderr)
        rec = dict(repo=repo, pr=pr, model=model, seen_model=seen_model, rc=p.returncode, secs=secs,
                   head=head[1] if head else None, opus_head=e['head'], verdict=verdict, has_findings=ok,
                   findings=rows, opus_majors=e['majors'], opus_verdict=e['verdict'], tokens=tok,
                   review_md=mds[-1] if mds else None)
        with open(res_path, 'a') as fh:
            fh.write(json.dumps(rec) + '\n')
        print(f"{repo}:{pr} rc={p.returncode} {secs}s head_match={rec['head'] == e['head']} verdict={verdict} "
              f"findings={len(rows)} majors={sum(r['sev'] in ('major','blocker') for r in rows)} opus_majors={len(e['majors'])} "
              f"out={tok['out']} model={seen_model}", flush=True)
        if p.returncode not in (0, 1):
            print((p.stderr or p.stdout)[-1500:], flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
