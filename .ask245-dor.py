import importlib.util, os, pathlib
here = pathlib.Path(
    "/Users/assafkipnis/.config/kipi/worktrees/ask-245/q-system/.q-system/scripts")
os.environ.setdefault("SCRIPT_DIR", str(here))
spec = importlib.util.spec_from_file_location("ls", here / "linear-sync.py")
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
Q = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
 nodes{identifier title description} pageInfo{hasNextPage endCursor}}}"""
TEAM = 'query{teams(filter:{key:{eq:"ASK"}}){nodes{id}}}'
tid = ls.graphql(TEAM, {})["teams"]["nodes"][0]["id"]
after = None
while True:
    p = ls.graphql(Q, {"t": tid, "a": after})["issues"]
    for n in p["nodes"]:
        if n["identifier"] == "ASK-245":
            print(n["title"]); print("=" * 70); print(n["description"])
            raise SystemExit(0)
    if not p["pageInfo"]["hasNextPage"]:
        break
    after = p["pageInfo"]["endCursor"]
print("ASK-245 not found")
