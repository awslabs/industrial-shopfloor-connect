# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Records what the SFC Lambda target invoked it with.

The target invokes asynchronously (InvocationType ``Event``), so the caller never sees a response. The only
observable is a side effect: this function writes the payload it received to S3 under the run marker that
every test record carries in ``$.metadata.marker``, and the suite's lambda sink reads it back from there.

A compressed invocation is SFC's envelope ``{"compression": "GZIP"|"ZIP", "payload": <base64>}``; the marker is
inside, so the envelope is unwrapped to find it. The event is stored as received. The object is named after
the request id: an asynchronous event Lambda delivers twice is stored once.
"""

from __future__ import annotations

import base64
import gzip
import io
import json
import os
import time
import uuid
import zipfile

import boto3

BUCKET = os.environ["EVIDENCE_BUCKET"]
PREFIX = os.environ.get("EVIDENCE_PREFIX", "lambda-evidence/")
s3 = boto3.client("s3")


def _unwrapped(event):
    """The records an event carries, with SFC's compression envelope opened."""
    if isinstance(event, dict) and str(event.get("compression", "")).upper() in ("GZIP", "ZIP") and "payload" in event:
        raw = base64.b64decode(event["payload"])
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        elif raw[:4] == b"PK\x03\x04":
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                raw = b"".join(zf.read(n) for n in zf.namelist())
        return json.loads(raw)
    return event


def _marker(event) -> str:
    try:
        records = _unwrapped(event)
    except Exception:  # noqa: BLE001 - an undecodable envelope is filed under "unknown", not lost
        records = event
    first = records[0] if isinstance(records, list) and records else records
    if isinstance(first, dict):
        md = first.get("metadata")
        if isinstance(md, dict) and md.get("marker"):
            return str(md["marker"])
    return "unknown"


def handler(event, context):  # noqa: ANN001
    request_id = getattr(context, "aws_request_id", None)
    key = f"{PREFIX}{_marker(event)}/{request_id or f'{time.time_ns()}-{uuid.uuid4().hex[:8]}'}.json"
    body = json.dumps({"receivedAt": time.time(), "requestId": request_id, "payload": event}, default=str).encode()
    s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType="application/json")
    return {"key": key}
