#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Best-effort teardown at the end of a build.

**This is not the teardown guarantee.** It runs in the buildspec's ``post_build`` phase, which CodeBuild
skips entirely when a build is ``TIMED_OUT`` or stopped - precisely the runs that leak. The authoritative
cleanup is the EventBridge-driven janitor in ``ci/cdk/lambda/janitor.py``, which fires on every terminal
build state including those two.

This exists only to shorten the window: deleting immediately is tidier than waiting for the next event,
and draining the queues stops one run's messages from confusing the next. Every operation tolerates
failure, because a cleanup error must never turn a green suite red.
"""

from __future__ import annotations

import os
import sys

try:
    import boto3
except ImportError:  # pragma: no cover
    print("boto3 is required", file=sys.stderr)
    raise


def run_id() -> str:
    build_id = os.environ.get("CODEBUILD_BUILD_ID", "local:000000000000")
    return "b_" + build_id.rsplit(":", 1)[-1].replace("-", "")[:12]


def drain(queue_url: str, label: str) -> int:
    """Remove leftover messages so they cannot be observed by a later run.

    Bounded, and never PurgeQueue: purge is throttled to once per 60 seconds, so using it would break
    back-to-back reruns - the common case when someone is iterating on a failing assertion.
    """
    if not queue_url:
        return 0
    sqs = boto3.client("sqs")
    removed = 0
    for _ in range(20):
        try:
            resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=0)
        except Exception as e:  # noqa: BLE001
            print(f"  {label}: could not receive: {e}")
            break
        msgs = resp.get("Messages", [])
        if not msgs:
            break
        try:
            sqs.delete_message_batch(
                QueueUrl=queue_url,
                Entries=[{"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]} for i, m in enumerate(msgs)],
            )
            removed += len(msgs)
        except Exception as e:  # noqa: BLE001
            print(f"  {label}: could not delete: {e}")
            break
    print(f"  {label}: drained {removed} message(s)")
    return removed


def main() -> int:
    rid = run_id()
    print(f"cleaning up run {rid}")

    for var, label in (
        ("SFC_E2E_QUEUE_URL", "sqs-target"),
        ("SFC_E2E_SNS_SINK_QUEUE_URL", "sns-sink"),
        ("SFC_E2E_IOT_SINK_QUEUE_URL", "iot-sink"),
    ):
        drain(os.environ.get(var, ""), label)

    stream = os.environ.get("SFC_E2E_KINESIS_STREAM")
    if stream:
        try:
            boto3.client("kinesis").delete_stream(StreamName=stream, EnforceConsumerDeletion=True)
            print(f"  deleted kinesis stream {stream}")
        except Exception as e:  # noqa: BLE001
            print(f"  could not delete kinesis stream {stream}: {e} (the janitor will retry)")

    # Retained messages have no lifecycle policy behind them, so they are the one thing that genuinely
    # accumulates. Scoped to this run's topic prefix so a concurrent build is untouched.
    try:
        control = boto3.client("iot")
        data = boto3.client("iot-data")
        prefix = f"sfc/it/{rid}/"
        for page in control.get_paginator("list_retained_messages").paginate():
            for msg in page.get("retainedTopics", []):
                topic = msg.get("topic", "")
                if topic.startswith(prefix):
                    data.delete_retained_message(topic=topic)
                    print(f"  deleted retained message {topic}")
    except Exception as e:  # noqa: BLE001
        print(f"  retained-message cleanup skipped: {e} (the janitor will retry)")

    print("cleanup finished (failures above are non-fatal by design)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
