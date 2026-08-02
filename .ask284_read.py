import importlib.util, pathlib
here = pathlib.Path("/Users/assafkipnis/projects/kipi-system/q-system/.q-system/scripts")
spec = importlib.util.spec_from_file_location("ls", here / "linear-sync.py")
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
r = ls.graphql('query{issue(id:"ASK-284"){identifier title description state{name}}}', {})
i = r["issue"]
print(i["identifier"], "|", i["title"], "|", i["state"]["name"])
print("=====")
print(i["description"])
