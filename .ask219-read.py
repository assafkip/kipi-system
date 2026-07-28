import json, os, sys, urllib.request

key = open(os.path.expanduser("~/.config/kipi/linear-api-key")).read().strip()
q = "query($id:String!){ issue(id:$id){ identifier title description state{name} comments(first:50){nodes{body createdAt user{name}}} } }"
req = urllib.request.Request(
    "https://api.linear.app/graphql",
    data=json.dumps({"query": q, "variables": {"id": "ASK-219"}}).encode(),
    headers={"Authorization": key, "Content-Type": "application/json"},
)
d = json.load(urllib.request.urlopen(req))
i = d["data"]["issue"]
print("===", i["identifier"], i["title"], "| state:", i["state"]["name"])
print(i["description"])
print("\n=== COMMENTS ===")
for c in i["comments"]["nodes"]:
    print("---", c["createdAt"], (c.get("user") or {}).get("name"))
    print(c["body"][:2500])
