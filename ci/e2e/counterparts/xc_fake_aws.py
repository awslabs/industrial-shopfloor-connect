#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""A local stand-in for the two AWS JSON-protocol calls SFC's runtime makes outside targets:
Secrets Manager GetSecretValue (JSON 1.1) and CloudWatch PutMetricData (JSON 1.0 in SDK 2.55).

    xc_fake_aws.py --port P --spec spec.json --aws-config <path>

Run as a "command" service. SFC has no Endpoint setting for either client (AwsServiceConfig.endpoint is
null), and a case's "env" values are not placeholder-expanded, so the endpoint cannot be passed as
AWS_ENDPOINT_URL_*. Instead this server writes a shared AWS config file whose default profile carries
``endpoint_url = http://127.0.0.1:P`` (honoured by the SDK's AwsClientEndpointProvider), and the case sets
``AWS_CONFIG_FILE`` to that file's path relative to the SFC process working directory (the case run
directory). Cases also pin a region that does not exist ("e2e-local-1"), so that even if the override did
not apply, nothing could reach a real AWS endpoint.

spec.json: {"secrets": {"<name>": "<SecretString>"}, "accountId": "000000000000"}

Every request is appended to requests.jsonl in the working directory, one line per call -
``{"op", "secretId", "versionStage"}`` - and, for PutMetricData, one line per datum - ``{"op",
"namespace", "name", "dims", "unit", "value"}`` - so a jsonl sink can assert on what SFC sent. Secret
values are never logged.
(Shared by several case directories; it belongs in ci/e2e/counterparts/ once the lead adopts it.)
"""

from __future__ import annotations

import argparse
import gzip
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--spec", required=True)
ap.add_argument("--aws-config", required=True)
ap.add_argument("--region", default="e2e-local-1")
a = ap.parse_args()

spec = json.loads(Path(a.spec).read_text())
account = spec.get("accountId", "000000000000")
secrets: dict = spec.get("secrets", {})
lock = threading.Lock()
log = open("requests.jsonl", "a", buffering=1)


def arn_of(name: str) -> str:
    return f"arn:aws:secretsmanager:{a.region}:{account}:secret:{name}-AbCdEf"


def lookup(secret_id: str) -> str | None:
    if secret_id in secrets:
        return secret_id
    for name in secrets:
        if secret_id == arn_of(name):
            return name
    return None


def emit(entry: dict) -> None:
    with lock:
        log.write(json.dumps(entry, sort_keys=True) + "\n")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, body: dict, content_type: str) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("x-amzn-RequestId", "e2e-0000")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if self.headers.get("Content-Encoding", "").lower() == "gzip":
            raw = gzip.decompress(raw)
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            body = {}
        target = self.headers.get("X-Amz-Target", "")
        op = target.rsplit(".", 1)[-1]
        if target.startswith("secretsmanager."):
            ctype = "application/x-amz-json-1.1"
            emit({"op": op, "secretId": body.get("SecretId"), "versionStage": body.get("VersionStage")})
            if op != "GetSecretValue":
                return self._send(400, {"__type": "UnknownOperationException", "message": op}, ctype)
            name = lookup(str(body.get("SecretId", "")))
            if name is None:
                return self._send(400, {"__type": "ResourceNotFoundException",
                                        "message": "Secrets Manager can't find the specified secret."}, ctype)
            return self._send(200, {"ARN": arn_of(name), "Name": name, "VersionId": "e2e-version-1",
                                    "SecretString": secrets[name], "VersionStages": ["AWSCURRENT"],
                                    "CreatedDate": 1759000000.0}, ctype)
        if target.startswith("GraniteServiceVersion20100801."):
            ctype = "application/x-amz-json-1.0"
            if op == "PutMetricData":
                for datum in body.get("MetricData", []):
                    emit({"op": op, "namespace": body.get("Namespace"), "name": datum.get("MetricName"),
                          "dims": {d.get("Name"): d.get("Value") for d in datum.get("Dimensions", [])},
                          "unit": datum.get("Unit"), "value": datum.get("Value"),
                          "values": datum.get("Values"), "statistics": datum.get("StatisticValues")})
                return self._send(200, {}, ctype)
            emit({"op": op})
            return self._send(400, {"__type": "UnknownOperationException", "message": op}, ctype)
        emit({"op": "unknown", "target": target, "path": self.path})
        return self._send(400, {"__type": "UnknownOperationException", "message": target}, "application/json")

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
cfg = Path(a.aws_config)
cfg.parent.mkdir(parents=True, exist_ok=True)
cfg.write_text(f"[default]\nregion = {a.region}\nendpoint_url = http://127.0.0.1:{a.port}\n")
print(f"fake aws listening on 127.0.0.1:{a.port}, config {cfg}", flush=True)
server.serve_forever()
