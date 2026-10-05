# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""What a counterpart recorded, read from the JSON-lines file it appends to.

* ``jsonl`` - any counterpart log: ``{"kind": "jsonl", "service": "rest", "file": "requests.jsonl"}``
  (the HTTP fake's requests, for asserting on what the REST adapter sent).
* ``aws-stub`` - the SFC records the AWS wire stub **accepted**, decoded from the message bodies, so
  the usual record assertions apply: ``{"kind": "aws-stub", "service": "stub"}``.
* ``aws-stub-requests`` - one record per wire request ``{"op", "attempt", "status", "entries"}``: what
  the SDK and SFC's own retry loop actually sent, for retry and backoff assertions.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import Sink, marker_of
from .aws import decode_body


class JsonlSink(Sink):
    kind = "jsonl"
    default_file = "out.jsonl"

    def prepare(self):
        service = self.spec.get("service", "stub")
        self.path = Path(self.ctx.workdir) / "services" / service / self.spec.get("file", self.default_file)
        return {}

    def lines(self) -> list[dict]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # the last line is being written
        return out

    def records(self) -> list:
        return self.lines()


class StubRequestSink(JsonlSink):
    kind = "aws-stub-requests"
    default_file = "capture.jsonl"


class StubAcceptedSink(JsonlSink):
    kind = "aws-stub"
    default_file = "capture.jsonl"

    def records(self) -> list:
        out = []
        for req in self.lines():
            for e in req.get("entries", []):
                if not e.get("accepted"):
                    continue
                for rec in decode_body(e["body"].encode()):
                    if self.spec.get("anyMarker") or marker_of(rec) in (None, self.ctx.marker):
                        out.append(rec)
        return out
