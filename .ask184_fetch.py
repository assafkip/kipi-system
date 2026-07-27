import json, os, urllib.request

key = open(os.path.expanduser("~/.config/kipi/linear-api-key")).read().strip()
q = """
query($id: String!) {
  issue(id: $id) {
    identifier
    title
    url
    state { name }
    description
    comments(first: 20) { nodes { body createdAt user { name } } }
  }
}
"""
body = json.dumps({"query": q, "variables": {"id": "ASK-184"}}).encode()
req = urllib.request.Request(
    "https://api.linear.app/graphql",
    data=body,
    headers={"Content-Type": "application/json", "Authorization": key},
)
data = json.load(urllib.request.urlopen(req, timeout=30))
issue = data["data"]["issue"]
print("=== %s  [%s] ===" % (issue["identifier"], issue["state"]["name"]))
print(issue["title"])
print(issue["url"])
print("\n--- DESCRIPTION ---")
print(issue["description"] or "(none)")
print("\n--- COMMENTS ---")
for c in issue["comments"]["nodes"]:
    who = (c.get("user") or {}).get("name", "?")
    print("[%s %s] %s" % (c["createdAt"], who, c["body"][:1500]))
