"""Part 1 candidates: PRs whose LAST review was Opus 5, at the PR's final head, with at least one major.

Same head sha is the point: the recall test re-reviews exactly the tree Opus read,
so a major Opus raised is still in the code when Sonnet looks.
"""
import glob, json, os, re, subprocess, sys
PRD = os.path.expanduser('~/.config/kipi/pr-reviews')
out = []
for vf in glob.glob(PRD + '/assafkip_*__pr-*.verdict.json'):
    m = re.match(r'assafkip_(.+?)__pr-(\d+)\.verdict\.json$', os.path.basename(vf))
    if not m:
        continue
    repo, pr = m[1], int(m[2])
    try:
        v = json.load(open(vf))
    except Exception:
        continue
    if v.get('engine') != 'claude' or v.get('reviewed_by') != 'claude-opus-5' or not v.get('head_sha'):
        continue
    if v.get('review_base'):
        continue  # a delta round read only part of the PR
    review = v.get('review')
    if not review or not os.path.exists(review):
        continue
    t = open(review, errors='replace').read()
    fb = re.search(r'FINDINGS:\s*\n(.*?)END FINDINGS', t, re.S)
    majors = []
    for l in (fb[1].splitlines() if fb else []):
        p = [x.strip() for x in l.strip().split('|')]
        if len(p) >= 3 and p[0] in ('major', 'blocker'):
            majors.append({'sev': p[0], 'claim': p[1], 'loc': p[2], 'nonblocking': p[-1] == 'nonblocking'})
    if not majors:
        continue
    out.append(dict(repo=repo, pr=pr, head=v['head_sha'], ts=v.get('ts'), verdict=v.get('verdict'),
                    review=review, majors=majors, issue=v.get('issue')))
out.sort(key=lambda r: r['ts'] or '', reverse=True)
json.dump(out, open(sys.argv[1], 'w'), indent=1)
for r in out[:40]:
    print(r['repo'][:16], r['pr'], r['head'][:8], r['ts'][:10], r['verdict'], len(r['majors']))
print(len(out), 'candidates')
