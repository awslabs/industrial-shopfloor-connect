#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""A scripted HTTP server for the REST adapter.

    http_fake.py --port <p> --scenario scenario.json

scenario.json maps paths to responses::

    {"/counter": {"kind": "counter", "start": 0},            # {"value": n}, n += 1 per request
     "/static": {"kind": "json", "body": {"a": 1}},
     "/flaky":  {"kind": "status", "codes": [500, 500, 200], "body": {"ok": true}},
     "/echo":   {"kind": "echo"}}                            # method, path, headers, body

Every request is appended to requests.jsonl in the working directory, so a case can assert on what the
adapter sent (headers, query string, retries).
"""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--scenario", required=True)
a = ap.parse_args()
scenario = json.load(open(a.scenario))
state = {k: {"n": v.get("start", 0), "i": 0} for k, v in scenario.items()}
lock = threading.Lock()
log = open("requests.jsonl", "a", buffering=1)


class Handler(BaseHTTPRequestHandler):
    def _respond(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode() if length else ""
        with lock:
            log.write(json.dumps({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}) + "\n")
            spec = scenario.get(path)
            if spec is None:
                code, out = 404, {"error": "no route"}
            elif spec["kind"] == "counter":
                code, out = 200, {"value": state[path]["n"]}
                state[path]["n"] += 1
            elif spec["kind"] == "json":
                code, out = 200, spec["body"]
            elif spec["kind"] == "status":
                codes = spec["codes"]
                code = codes[min(state[path]["i"], len(codes) - 1)]
                state[path]["i"] += 1
                out = spec.get("body", {}) if code < 400 else {"error": code}
            elif spec["kind"] == "echo":
                code, out = 200, {"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}
            else:
                code, out = 500, {"error": "bad scenario"}
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = _respond

    def log_message(self, *args):
        pass


print(f"http fake on {a.port}", flush=True)
ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
