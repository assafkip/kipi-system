"""Judge the Part 2 arms that committed work but were recorded without a review.

A load cut or the disk floor stopped some runs between the worker and the judge.
Their commit is still in the repo's object store (the recorded head), so this cuts
a detached worktree at that head, runs the SAME blind Opus judge with the same
prompt, writes an amendment row to part2/judge-amend.jsonl (results stay
append-only), and removes the tree. One at a time; disk and memory checked first.
"""
import json, glob, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import part2_run as P

amend_path = os.path.join(P.OUT, 'judge-amend.jsonl')
amended = {(json.loads(l)['ticket'], json.loads(l)['arm']) for l in open(amend_path)} if os.path.exists(amend_path) else set()
template = open(os.path.join(P.EVAL, 'judge-template.txt')).read()
rows = []
for f in sorted(glob.glob(os.path.join(P.OUT, 'results-*.jsonl'))):
    rows += [json.loads(l) for l in open(f)]
for r in rows:
    if not r['committed'] or r['verdict'] or (r['ticket'], r['arm']) in amended:
        continue
    if not P.resources_ok():
        sys.exit(3)
    local = os.path.expanduser(P.LOCAL[r['repo']])
    tree = os.path.join(P.TREES, r['token'] + '-j')
    if not os.path.isdir(tree):
        P.sh('git', '-C', local, 'worktree', 'add', '-q', '--detach', tree, r['head'])
    ctx = os.path.join(P.OUT, 'ctx', r['token'])
    os.makedirs(ctx, exist_ok=True)
    title, _desc = P.issue_text(r['ticket'])
    open(os.path.join(ctx, 'pr.txt'), 'w').write(f'title:\t{title}\nnumber:\t0 (an offline change, not a PR)\n--\n(no body)\n')
    open(os.path.join(ctx, 'pr.diff'), 'w').write(P.sh('git', 'diff', r['base'], r['head'], cwd=tree, check=False) + '\n')
    jfile = os.path.join(P.OUT, 'logs', f"{r['token']}-judge-amend.json")
    t1 = time.time()
    with open(jfile, 'w') as jf:
        subprocess.run(['claude', '-p', P.judge_prompt(template, r['repo'], tree, ctx), '--model', P.JUDGE_MODEL,
                        '--output-format', 'json', '--disallowedTools', 'Bash(git clone:*)', 'Bash(gh:*)', 'Bash(curl:*)'],
                       cwd=tree, env={k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY'},
                       stdout=jf, stderr=subprocess.DEVNULL, timeout=P.JUDGE_TIMEOUT, stdin=subprocess.DEVNULL)
    judge = P.usage(open(jfile, errors='replace').read())
    rows_f, verdict, ok = P.findings(judge.get('result'))
    rec = dict(ticket=r['ticket'], arm=r['arm'], amend='judge', verdict=verdict, has_findings=ok, findings=rows_f,
               judge_secs=round(time.time() - t1), judge_usage={k: v for k, v in judge.items() if k != 'result'})
    with open(amend_path, 'a') as fh:
        fh.write(json.dumps(rec) + '\n')
    print(f"amended {r['ticket']} {r['arm']}: verdict={verdict} findings={len(rows_f)}", flush=True)
    P.sh('git', '-C', local, 'worktree', 'remove', '--force', tree, check=False)
