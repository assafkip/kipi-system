import importlib.util

SCRIPT = "/Users/assafkipnis/.config/kipi/worktrees/ask-191/q-system/.q-system/scripts/linear-sync.py"
spec = importlib.util.spec_from_file_location("ls", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

QUERY = """
query Q($id: String!) {
  issue(id: $id) {
    identifier
    title
    description
    url
    branchName
    state { name }
    labels { nodes { name } }
    comments { nodes { body createdAt user { name } } }
  }
}
"""

data = m.graphql(QUERY, {"id": "ASK-191"})
i = data["issue"]
print("TITLE:", i["title"])
print("STATE:", i["state"]["name"])
print("URL:", i["url"])
print("BRANCH:", i["branchName"])
print("LABELS:", [l["name"] for l in i["labels"]["nodes"]])
print("---- DESCRIPTION ----")
print(i["description"])
print("---- COMMENTS ----")
for c in i["comments"]["nodes"]:
    who = (c.get("user") or {}).get("name", "?")
    print("[%s %s]" % (c["createdAt"], who))
    print(c["body"])
    print("--")
