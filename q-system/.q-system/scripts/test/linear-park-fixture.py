#!/usr/bin/env python3
"""A fixture Linear GraphQL endpoint that answers park-label lookups (ASK-872).

ONE COPY, TWO SUITES. test-review-redrive-park.sh drives review-redrive.py
directly; test-ci-redrive.sh drives the REAL kipi-dispatch.sh, whose red-CI path
now asks the same reader for the same answer. Both need a board they can rewrite
between two reads. A second copy of this server is the same defect class as a
second copy of the park-label list (see park_labels.py): the two would drift, and
the one that drifted would be the one asserting the fix works.

RE-READ PER REQUEST, from the file named by $LABELS_FILE. The board is not a
constant in life -- the mark-dispatched cases exist precisely because a label can
land BETWEEN two reads, so a fixture answering from a dict frozen at import
cannot express the state the defect lives in.

THREE SENTINELS INSTEAD OF A LABEL LIST, because Linear can answer a lookup
without answering the question, and the three ways it does that have different
blast radii:

    __null__   the alias is present and null -- the id resolved to no issue.
               A BAD INPUT: only this issue's park state is unknown.
    __omit__   the alias is absent from `data` entirely. Also a bad input.
    __wrong__  the alias answers with a DIFFERENT identifier. Not a bad input --
               the response mapping itself is untrustworthy, so nothing in the
               batch can be filed with confidence.

All three arrive with NO `errors` key, so `graphql` returns normally and the
reader is holding a clean 200 that says nothing about the park.

Prints its port on stdout and serves forever. The caller kills it.
"""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

LABELS_FILE = os.environ["LABELS_FILE"]

NULL = "__null__"
OMIT = "__omit__"
WRONG = "__wrong__"


def _board():
    return json.load(open(LABELS_FILE))


def issue(ident):
    labels = _board().get(ident, [])
    if labels == NULL:
        return None
    if labels == WRONG:
        # Answers about a different issue under the alias asked for `ident`.
        return {"id": "ASK-000", "identifier": "ASK-000",
                "labels": {"nodes": []}}
    return {"id": ident, "identifier": ident,
            "labels": {"nodes": [{"name": n} for n in labels]}}


def _aliases(query):
    # `i0: issue(id: "ASK-901") { ... }` -> ("i0", "ASK-901")
    return re.findall(r'(\w+)\s*:\s*issue\(\s*id\s*:\s*"([^"]+)"', query)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        req = json.loads(body)
        # Answer whichever identifiers the reader named, under the alias it used,
        # so the fixture cannot accidentally teach the reader an ordering it does
        # not have live.
        data = {}
        for alias, ident in _aliases(req.get("query") or ""):
            if _board().get(ident) == OMIT:
                continue          # the alias never appears in the response
            data[alias] = issue(ident)
        out = json.dumps({"data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


if __name__ == "__main__":
    srv = HTTPServer(("127.0.0.1", 0), H)
    print(srv.server_port, flush=True)
    srv.serve_forever()
