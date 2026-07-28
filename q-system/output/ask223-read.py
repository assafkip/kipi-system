import importlib.util

spec = importlib.util.spec_from_file_location(
    "ls", "q-system/.q-system/scripts/linear-sync.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

QUERY = (
    "query($id: String!) { issue(id: $id) { identifier title state { name } "
    "description url labels { nodes { name } } comments { nodes { body } } } }"
)

data = m.graphql(QUERY, {"id": "ASK-223"})
issue = data["issue"]
print("==", issue["identifier"], "|", issue["title"])
print("state:", issue["state"]["name"], "| url:", issue["url"])
print("labels:", [n["name"] for n in issue["labels"]["nodes"]])
print("--- DESCRIPTION ---")
print(issue["description"])
print("--- COMMENTS ---")
for node in issue["comments"]["nodes"]:
    print("*", node["body"][:800])
