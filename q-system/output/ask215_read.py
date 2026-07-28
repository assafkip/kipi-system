import importlib.util
import os

REPO = "/Users/assafkipnis/.config/kipi/worktrees/ask-215"
spec = importlib.util.spec_from_file_location(
    "ls", os.path.join(REPO, "q-system/.q-system/scripts/linear-sync.py")
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

QUERY = """
query Q($id: String!) {
  issue(id: $id) {
    identifier
    title
    state { name }
    description
    comments(first: 40) { nodes { body createdAt user { name } } }
  }
}
"""

data = m.graphql(QUERY, {"id": "ASK-215"})
issue = data["issue"]
print("==", issue["identifier"], "|", issue["title"], "| state:", issue["state"]["name"])
print("=== DESCRIPTION ===")
print(issue["description"])
print("=== COMMENTS ===")
for c in issue["comments"]["nodes"]:
    who = (c["user"] or {}).get("name")
    print("---", c["createdAt"], who)
    print(c["body"])
