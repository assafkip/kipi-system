"""Record Part 1 reviews that finished while their runner was stuck on the watchdog pipe.

The review itself completed (its round file and verdict record are in the eval out
dir); only the runner's result line is missing. Time is the round file's birth to
its last write, which is the reviewer's own start and end.

    recover_part1.py <model> repo:pr [repo:pr ...]
"""
import glob, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import part1_run as P

model = sys.argv[1]
elig = {(e['repo'], e['pr']): e for e in json.load(open(os.path.join(P.EVAL, 'eligible.json')))}
outdir = os.path.join(P.OUT, 'reviews', model)
res_path = os.path.join(P.OUT, 'results-recovered.jsonl')
for key in sys.argv[2:]:
    repo, pr = key.rsplit(':', 1); pr = int(pr)
    mds = sorted(glob.glob(os.path.join(outdir, f'assafkip_{repo}__pr-{pr}-*.md')))
    if not mds or os.path.getsize(mds[-1]) == 0:
        print(f'{key}: no finished round file, not recorded'); continue
    md = mds[-1]
    born = float(subprocess.run(['stat', '-f', '%B', md], capture_output=True, text=True).stdout)
    end = os.path.getmtime(md)
    v = json.load(open(os.path.join(outdir, f'assafkip_{repo}__pr-{pr}.verdict.json')))
    rows, verdict, ok = P.findings(md)
    tok, seen = P.usage_since(repo, pr, born - 5)
    e = elig[(repo, pr)]
    rec = dict(repo=repo, pr=pr, model=model, seen_model=seen, rc=None, secs=round(end - born),
               head=v.get('head_sha'), opus_head=e['head'], verdict=verdict, has_findings=ok, findings=rows,
               opus_majors=e['majors'], opus_verdict=e['verdict'], tokens=tok, review_md=md,
               recovered=True, reviewed_by=v.get('reviewed_by'))
    with open(res_path, 'a') as fh:
        fh.write(json.dumps(rec) + '\n')
    print(f"{key} recovered: {rec['secs']}s verdict={verdict} findings={len(rows)} reviewed_by={rec['reviewed_by']} head_match={rec['head'] == e['head']}")
