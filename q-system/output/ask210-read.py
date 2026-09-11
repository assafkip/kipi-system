import json
import importlib.util
import urllib.request

spec = importlib.util.spec_from_file_location(
    "ls", "q-system/.q-system/scripts/linear-sync.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

query = (
    "query Q "
    "{ issue(id: \"ASK-210\") "
    "{ identifier title description state { name } } }"
)
req = urllib.request.Request(
    "https://api.linear.app/graphql",
    data=json.dumps({"query": query}).encode(),
    headers={"Content-Type": "application/json",
             "Authorization": mod.linear_api_key()},
)
payload = json.loads(urllib.request.urlopen(req, timeout=30).read())
issue = payload["data"]["issue"]
print("STATE:", issue["state"]["name"])
print("TITLE:", issue["title"])
print("---")
print(issue["description"])
