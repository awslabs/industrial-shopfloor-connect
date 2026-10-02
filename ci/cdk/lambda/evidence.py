# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Records what the SFC Lambda target invoked it with.

The Lambda target invokes asynchronously (InvocationType Event), so the caller never sees a response and
there is nothing for the harness to read back. The only observable is a side effect, which is what this
function provides: it writes the payload it received to S3 under a per-run prefix, and the verifier reads
that object.

Keyed by run id and by a monotonic-enough timestamp, so concurrent runs cannot overwrite one another.
"""

from __future__ import annotations

import json
import os
import time
import uuid

import boto3

BUCKET = os.environ["EVIDENCE_BUCKET"]
PREFIX = os.environ.get("EVIDENCE_PREFIX", "evidence-lambda/")

s3 = boto3.client("s3")


def handler(event, context):  # noqa: ANN001
    # The run id is carried in the payload's metadata by the test configuration. Falling back to
    # "unknown" rather than raising keeps a malformed payload visible in S3 instead of only in a log.
    run_id = "unknown"
    if isinstance(event, dict):
        run_id = str(event.get("runId") or (event.get("metadata") or {}).get("runId") or "unknown")
    elif isinstance(event, list) and event and isinstance(event[0], dict):
        run_id = str((event[0].get("metadata") or {}).get("runId") or "unknown")

    key = f"{PREFIX}{run_id}/{time.time_ns()}-{uuid.uuid4().hex[:8]}.json"
    body = json.dumps(
        {
            "receivedAt": time.time(),
            "requestId": getattr(context, "aws_request_id", None),
            "payload": event,
        },
        default=str,
    ).encode("utf-8")

    s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType="application/json")
    print(f"wrote s3://{BUCKET}/{key} ({len(body)} bytes)")
    return {"key": key}
