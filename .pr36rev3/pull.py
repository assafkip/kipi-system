import importlib.util, json, pathlib

spec = importlib.util.spec_from_file_location(
    "ls", "/Users/assafkipnis/projects/kipi-system/q-system/.q-system/scripts/linear-sync.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

q = ('query{issues(first:250,filter:{team:{key:{eq:"ASK"}}})'
     '{nodes{identifier description state{name type} assignee{name}}}}')
nodes = m.graphql(q, {})["issues"]["nodes"]

# The same shape ready() uses in linear-worker.sh: backlog/unstarted, has a DoR,
# not owned by the founder.
ready = [n for n in nodes
         if n["state"]["type"] in ("backlog", "unstarted")
         and "Definition of Ready" in (n.get("description") or "")
         and (n.get("assignee") or {}).get("name", "") != "Assaf Kipnis"]

out = pathlib.Path(__file__).parent
out.joinpath("dor.json").write_text(
    json.dumps({n["identifier"]: n["description"] for n in ready}))
out.joinpath("ready.txt").write_text(" ".join(n["identifier"] for n in ready))
print("real ready issues pulled from Linear: %d" % len(ready))
