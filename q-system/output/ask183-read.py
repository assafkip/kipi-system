import importlib.util
import pathlib

p = pathlib.Path("q-system/.q-system/scripts/linear-sync.py")
spec = importlib.util.spec_from_file_location("ls", p)
ls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ls)
q = "query($id:String!){issue(id:$id){identifier title state{name type} description}}"
d = ls.graphql(q, {"id": "ASK-183"})["issue"]
print(d["identifier"], "|", d["title"], "|", d["state"])
print("-----")
print(d["description"])
