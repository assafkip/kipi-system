"""Part 2 of the Sonnet evaluation (ASK-4038): worker quality on the 3 lowest-risk classes.

For each ticket: replay it from its merged PR's base, once per arm (Sonnet, Opus),
each in its own `git worktree add --detach` under ~/.config/kipi/worktrees/eval-<token>,
then review each output with ONE Opus reviewer that never sees the model: the tree
is detached (no branch name), and the prompt names neither arm nor model. The
token-to-model map is kept in arms.json, which the judge never reads.

ONE model run at a time. Each result is appended to results.jsonl the moment it
exists, and the worktree is removed once its result is recorded.

    part2_run.py            run every pending (ticket, arm)
    part2_run.py --only ASK-n
"""
import json, os, random, re, shutil, subprocess, sys, time
EVAL = os.path.expanduser(os.environ.get('KIPI_EVAL_DIR', '~/.config/kipi/eval'))  # results live outside the repo
OUT = os.path.join(EVAL, 'part2')
TREES = os.path.expanduser('~/.config/kipi/worktrees')
SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts')
ARMS = {'sonnet': 'claude-sonnet-5-5', 'opus': 'claude-opus-5'}
JUDGE_MODEL = 'claude-opus-5'
# The tickets and local checkouts live in $KIPI_EVAL_DIR/part2-config.json, not here:
# this repo is public. Each ticket is (class, repo, merged PR, ticket id), 3 per class.
_CFG = json.load(open(os.path.join(EVAL, 'part2-config.json')))
LOCAL = _CFG['local']
TICKETS = [tuple(x) for x in _CFG['tickets']]
WORK_TIMEOUT = 2400
JUDGE_TIMEOUT = 2400
NO_MCP = ['--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}']


def sh(*a, cwd=None, check=True, timeout=600):
    r = subprocess.run(a, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(a[:4])}: rc={r.returncode} {r.stderr[-400:]}")
    return r.stdout.strip()


def mem_free_frac():
    """The resource gate's own instrument (gate-locked/hooks/resource_gate.py): memory_pressure's free percentage."""
    out = subprocess.run(['/usr/bin/memory_pressure'], capture_output=True, text=True, timeout=20).stdout
    m = re.search(r'System-wide memory free percentage:\s*(\d+)%', out)
    return int(m[1]) / 100 if m else 0.0


def resources_ok():
    if shutil.disk_usage(os.path.expanduser('~')).free / 2**30 < 5:
        print('STOP: under the 5 GB disk floor', flush=True)
        return False
    for _ in range(30):
        if mem_free_frac() >= 0.30:
            return True
        print(f'waiting: {mem_free_frac():.0%} memory free, under 30%', flush=True)
        time.sleep(60)
    print('STOP: memory stayed under 25% free for 30 min', flush=True)
    return False


def issue_text(ident):
    import importlib.util
    spec = importlib.util.spec_from_file_location('linear_sync', os.path.join(SCRIPTS, 'linear-sync.py'))
    ls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ls)
    i = ls.graphql('query($id:String!){issue(id:$id){title description}}', {'id': ident}).get('issue') or {}
    return i.get('title') or '', i.get('description') or ''


def usage(js):
    try:
        d = json.loads(js)
    except Exception:
        return {}
    u = d.get('usage') or {}
    return {'cost_usd': d.get('total_cost_usd'), 'turns': d.get('num_turns'), 'out': u.get('output_tokens'),
            'in': u.get('input_tokens'), 'cw': u.get('cache_creation_input_tokens'), 'cr': u.get('cache_read_input_tokens'),
            'result': (d.get('result') or '')[-6000:], 'is_error': d.get('is_error')}


def worker_prompt(ident, tree, title, desc):
    return f"""You are Sana, the kipi Systems Engineer, working Linear issue {ident}.

You are in a DEDICATED GIT WORKTREE at {tree}, on a detached HEAD at the commit the
work starts from. Work here and nowhere else. Do not create or switch branches.

This is an OFFLINE REPLAY. Linear and GitHub are not reachable from this run. Do not
push, do not open a PR, do not post to Linear, do not file spillover rows. The issue
text is below, in full.

1. The issue carries a Definition of Ready or acceptance criteria. Work ONLY what it scopes. A 'Not doing' line is binding.
2. Follow this repo's discipline: reproducer first and observed RED before green, then the real command output.
3. Commit here (detached HEAD) with the issue id {ident} in the message.
4. If you cannot finish, write why to {tree}/.sana-needs-scope (the spec is wrong) or {tree}/.sana-blocked-capability (this run lacks something), then stop.
5. End your turn with what you changed, the test command you ran, and its real output.

=== ISSUE {ident}: {title}
{desc}
"""


def judge_prompt(template, repo, tree, ctx):
    """The fleet reviewer's own prompt (a real round-1 transcript), pointed at this tree.
    Nothing in it names an arm, a model or a branch."""
    p = re.sub(r'review pull request #\d+ in \S+?,', f'review pull request #0 in {tree},', template)
    p = re.sub(r'\S+/review-scratch/ctx\.[^/\s]+', ctx, p)
    p = re.sub(r'\(gh -R assafkip/\S+ pr (view|diff) \d+\)', r'(the change under review)', p)
    return p.replace('assafkip/kipi-system', f'assafkip/{repo}')


def findings(text):
    fb = re.search(r'FINDINGS:\s*\n(.*?)END FINDINGS', text or '', re.S)
    rows = []
    for l in (fb[1].splitlines() if fb else []):
        q = [x.strip() for x in l.strip().split('|')]
        if len(q) >= 3 and q[0] in ('blocker', 'major', 'minor', 'nit'):
            rows.append({'sev': q[0], 'claim': q[1], 'loc': q[2], 'nonblocking': q[-1] == 'nonblocking'})
    v = re.findall(r'VERDICT:?\**\s*:?\s*\**\s*(APPROVE WITH NITS|APPROVE|REQUEST CHANGES|BLOCK)', text or '')
    return rows, (v[-1] if v else None), bool(fb)


def run_tests(tree, base):
    changed = sh('git', 'diff', '--name-only', base, 'HEAD', cwd=tree, check=False).splitlines()
    tests = [f for f in changed if re.search(r'(^|/)tests?/|(^|/)test[_-]', f)
             and os.path.exists(os.path.join(tree, f)) and f.endswith(('.py', '.sh'))]
    out = []
    for t in tests:
        runner = ['python3', t] if t.endswith('.py') else ['bash', t]
        try:
            r = subprocess.run(runner, cwd=tree, capture_output=True, text=True, timeout=900)
            out.append({'test': t, 'rc': r.returncode, 'tail': (r.stdout + r.stderr)[-600:]})
        except subprocess.TimeoutExpired:
            out.append({'test': t, 'rc': 'timeout', 'tail': ''})
    return changed, out


def main():
    os.makedirs(OUT, exist_ok=True)
    shard = sys.argv[sys.argv.index('--shard') + 1] if '--shard' in sys.argv else '0/1'
    si, sn = (int(x) for x in shard.split('/'))
    # one results file and one arms map per shard: each file has exactly one writer
    res_path = os.path.join(OUT, f'results-{si}of{sn}.jsonl')
    arms_path = os.path.join(OUT, f'arms-{si}of{sn}.json')
    arms = json.load(open(arms_path)) if os.path.exists(arms_path) else {}
    done = {(r['ticket'], r['arm']) for r in map(json.loads, open(res_path))} if os.path.exists(res_path) else set()
    template = open(os.path.join(EVAL, 'judge-template.txt')).read()
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    for n, (cls, repo, pr, ident) in enumerate(TICKETS):
        if n % sn != si:
            continue
        if only and only != ident:
            continue
        order = list(ARMS)
        random.Random(ident).shuffle(order)  # arm order fixed per ticket, not always one arm first
        for arm in order:
            if (ident, arm) in done:
                continue
            if not resources_ok():
                return 3
            local = os.path.expanduser(LOCAL[repo])
            sh('git', '-C', local, 'fetch', '-q', 'origin', f'pull/{pr}/head', timeout=300)
            commits = json.loads(sh('gh', 'api', f'repos/assafkip/{repo}/pulls/{pr}/commits', '--paginate'))
            base = commits[0]['parents'][0]['sha']
            token = arms.get(f'{ident}|{arm}') or f'eval-{random.randrange(16**8):08x}'
            arms[f'{ident}|{arm}'] = token
            json.dump(arms, open(arms_path, 'w'), indent=1)
            tree = os.path.join(TREES, token)
            if not os.path.isdir(tree):
                sh('git', '-C', local, 'worktree', 'add', '-q', '--detach', tree, base)
            title, desc = issue_text(ident)
            env = {k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY'}
            env['KIPI_AGENT'] = 'sana'
            t0 = time.time()
            wfile = os.path.join(OUT, 'logs', f'{token}-worker.json')
            os.makedirs(os.path.dirname(wfile), exist_ok=True)
            try:
                with open(wfile, 'w') as wf:
                    w = subprocess.run(['claude', '-p', worker_prompt(ident, tree, title, desc), '--model', ARMS[arm],
                                        '--output-format', 'json', *NO_MCP, '--disallowedTools', 'Bash(gh:*)',
                                        'Bash(git push:*)', 'Bash(curl:*)'], cwd=tree, env=env, stdout=wf,
                                       stderr=subprocess.DEVNULL, timeout=WORK_TIMEOUT, stdin=subprocess.DEVNULL)
                wout, wrc = open(wfile, errors='replace').read(), w.returncode
            except subprocess.TimeoutExpired:
                wout, wrc = '', 'timeout'
            wsecs = round(time.time() - t0)
            head = sh('git', 'rev-parse', 'HEAD', cwd=tree)
            refused = [f for f in ('.sana-needs-scope', '.sana-blocked-capability') if os.path.exists(os.path.join(tree, f))]
            changed, tests = run_tests(tree, base)
            ctx = os.path.join(OUT, 'ctx', token)
            os.makedirs(ctx, exist_ok=True)
            open(os.path.join(ctx, 'pr.txt'), 'w').write(f'title:\t{title}\nnumber:\t0 (an offline change, not a PR)\n--\n(no body)\n')
            open(os.path.join(ctx, 'pr.diff'), 'w').write(sh('git', 'diff', base, 'HEAD', cwd=tree, check=False) + '\n')
            jrows, jverdict, jok, jsecs, judge = [], None, False, 0, {}
            if head != base and resources_ok():
                t1 = time.time()
                jfile = os.path.join(OUT, 'logs', f'{token}-judge.json')
                try:
                    with open(jfile, 'w') as jf:
                        subprocess.run(['claude', '-p', judge_prompt(template, repo, tree, ctx), '--model', JUDGE_MODEL,
                                        '--output-format', 'json', '--disallowedTools', 'Bash(git clone:*)', 'Bash(gh:*)',
                                        'Bash(curl:*)'], cwd=tree,
                                       env={k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY'},
                                       stdout=jf, stderr=subprocess.DEVNULL, timeout=JUDGE_TIMEOUT, stdin=subprocess.DEVNULL)
                    judge = usage(open(jfile, errors='replace').read())
                except subprocess.TimeoutExpired:
                    judge = {'result': '', 'timeout': True}
                jsecs = round(time.time() - t1)
                jrows, jverdict, jok = findings(judge.get('result'))
                open(os.path.join(ctx, 'review.txt'), 'w').write(judge.get('result') or '')
            rec = dict(ticket=ident, cls=cls, repo=repo, pr=pr, arm=arm, model=ARMS[arm], token=token, base=base, head=head,
                       committed=head != base, refused=refused, worker_rc=wrc, worker_secs=wsecs, worker=usage(wout),
                       changed=changed, tests=tests, tests_pass=(all(t['rc'] == 0 for t in tests) if tests else None),
                       judge_model=JUDGE_MODEL, judge_secs=jsecs, verdict=jverdict, has_findings=jok, findings=jrows,
                       judge_usage={k: v for k, v in judge.items() if k != 'result'})
            with open(res_path, 'a') as fh:
                fh.write(json.dumps(rec) + '\n')
            sev = {s: sum(f['sev'] == s for f in jrows) for s in ('blocker', 'major', 'minor', 'nit')}
            print(f"{ident} {arm} committed={rec['committed']} tests={rec['tests_pass']} verdict={jverdict} {sev} "
                  f"worker {wsecs}s judge {jsecs}s", flush=True)
            # the result is recorded: the tree goes now (its commit stays in the object store)
            sh('git', '-C', local, 'worktree', 'remove', '--force', tree, check=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
