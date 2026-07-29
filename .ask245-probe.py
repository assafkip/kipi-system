import importlib.util, json, os, pathlib, subprocess
here = pathlib.Path(os.environ.get(
    "SCRIPT_DIR",
    "/Users/assafkipnis/.config/kipi/worktrees/ask-245/q-system/.q-system/scripts"))
os.environ.setdefault("SCRIPT_DIR", str(here))
spec = importlib.util.spec_from_file_location("ls", here / "linear-sync.py")
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
Q = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
 nodes{id identifier title description state{name type} project{name}
       labels{nodes{name}}} pageInfo{hasNextPage endCursor}}}"""
TEAM = 'query{teams(filter:{key:{eq:"ASK"}}){nodes{id}}}'
tid = ls.graphql(TEAM, {})["teams"]["nodes"][0]["id"]
issues, after = [], None
while True:
    p = ls.graphql(Q, {"t": tid, "a": after})["issues"]
    issues += p["nodes"]
    if not p["pageInfo"]["hasNextPage"]:
        break
    after = p["pageInfo"]["endCursor"]

def mine(i):
    labels = {l["name"] for l in i["labels"]["nodes"]}
    if "owner:assaf" in labels:
        return False
    if "owner:sana" not in labels:
        return False
    d = i.get("description") or ""
    return "## Definition of Ready" in d or "Definition of Ready" in d

rew = [i for i in issues if mine(i) and i["state"]["type"] == "started"]
open_prs = json.loads(subprocess.run(
    ["gh", "pr", "list", "--state", "open", "--json", "headRefName", "-L", "200"],
    capture_output=True, text=True).stdout or "[]")
open_branches = {p["headRefName"] for p in open_prs}
print("total ASK issues:", len(issues))
print("rework candidates (owner:sana + DoR + started):", len(rew))
for i in rew:
    br = "sana/" + i["identifier"].lower()
    print("  %-9s open_pr=%-5s %s | %s" % (
        i["identifier"], br in open_branches, i["state"]["name"], i["title"][:55]))
