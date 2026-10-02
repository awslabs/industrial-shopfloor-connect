# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Teardown for per-run AWS resources.

This is the authoritative cleanup, not the buildspec's ``post_build``. CodeBuild skips ``post_build``
entirely when a build is ``TIMED_OUT`` or stopped, and those are exactly the runs that leak - so cleanup
is driven from the build's terminal state instead.

Two entry paths:

* **event** - an EventBridge "CodeBuild Build State Change" for a terminal status. The run id is derived
  from the build id.
* **age** - an hourly sweep that removes anything older than ``MAX_AGE_SECONDS``, as a backstop for a
  terminal event that was never delivered.

The run-id derivation is the subtle part and the reason this file has a test. The two sources spell the
same build differently:

* ``$CODEBUILD_BUILD_ID`` inside the container is ``project-name:uuid``
* ``event["detail"]["build-id"]`` is the **full ARN**, ``arn:aws:codebuild:region:acct:build/project:uuid``

Splitting on the *first* colon therefore yields ``aws`` for the event, which would make the janitor
delete nothing at all while appearing to work. Both sides must split on the **last** colon - bash uses
``${BUILD_ID##*:}`` and this module uses ``rsplit(":", 1)[-1]``.
"""

from __future__ import annotations

import os
import time

# boto3 is imported lazily inside each function that needs it, not at module scope. The Lambda runtime
# always provides it, but run_id_from_build_id is pure and is unit-tested outside Lambda
# (ci/scripts/test_run_id.py) - a module-level import would make the most safety-critical function in
# this file untestable without installing the SDK.

RUN_PREFIX = "b_"
TOPIC_PREFIX = "sfc/it/"
MAX_AGE_SECONDS = int(os.environ.get("MAX_AGE_SECONDS", "7200"))


def run_id_from_build_id(build_id: str) -> str:
    """``arn:...:build/proj:uuid`` or ``proj:uuid`` -> ``b_<uuid-without-dashes, 12 chars>``.

    Must stay byte-for-byte consistent with the buildspec's ``${CODEBUILD_BUILD_ID##*:}``.
    """
    uuid = build_id.rsplit(":", 1)[-1]
    return RUN_PREFIX + uuid.replace("-", "")[:12]


def _delete_retained_messages(prefix: str) -> list[str]:
    """Retained messages are the one artefact with no lifecycle policy behind it.

    ``ListRetainedMessages`` has no resource type in IAM and must be granted on ``*``, so every deletion
    is gated on the topic prefix in code as well - the IAM policy alone cannot scope the list call.
    """
    import boto3

    deleted: list[str] = []
    data = boto3.client("iot-data")
    control = boto3.client("iot")
    paginator = control.get_paginator("list_retained_messages")
    for page in paginator.paginate():
        for msg in page.get("retainedTopics", []):
            topic = msg.get("topic", "")
            if not topic.startswith(prefix):
                continue
            try:
                data.delete_retained_message(topic=topic)
                deleted.append(topic)
            except Exception as e:  # noqa: BLE001 - best effort, keep going
                print(f"could not delete retained message {topic}: {e}")
    return deleted


def _delete_run_certificates(run_id: str | None, max_age: int | None) -> list[str]:
    """Remove per-run IoT certificates, which have no expiry of their own."""
    import boto3

    iot = boto3.client("iot")
    removed: list[str] = []
    now = time.time()
    for page in iot.get_paginator("list_certificates").paginate():
        for cert in page.get("certificates", []):
            created = cert.get("creationDate")
            age = now - created.timestamp() if created else 0
            if max_age is not None and age < max_age:
                continue
            cert_id = cert["certificateId"]
            arn = cert["certificateArn"]
            try:
                for pol in iot.list_attached_policies(target=arn).get("policies", []):
                    iot.detach_policy(policyName=pol["policyName"], target=arn)
                iot.update_certificate(certificateId=cert_id, newStatus="INACTIVE")
                iot.delete_certificate(certificateId=cert_id, forceDelete=True)
                removed.append(cert_id)
            except Exception as e:  # noqa: BLE001
                print(f"could not delete certificate {cert_id}: {e}")
    return removed


def _emit(metric: str, value: float, mode: str) -> None:
    import boto3

    try:
        boto3.client("cloudwatch").put_metric_data(
            Namespace="SFC/IntegTest",
            MetricData=[{
                "MetricName": metric,
                "Value": value,
                "Unit": "Count",
                "Dimensions": [{"Name": "Mode", "Value": mode}],
            }],
        )
    except Exception as e:  # noqa: BLE001
        print(f"could not emit metric {metric}: {e}")


def handler(event, _context):  # noqa: ANN001
    mode = "age" if (isinstance(event, dict) and event.get("mode") == "age") else "event"

    if mode == "event":
        build_id = (event.get("detail") or {}).get("build-id", "")
        if not build_id:
            print("no detail.build-id in the event; nothing to do")
            return {"mode": mode, "deleted": 0}
        run_id = run_id_from_build_id(build_id)
        status = (event.get("detail") or {}).get("build-status")
        print(f"build {build_id} finished as {status}; cleaning run {run_id}")
        # Per-run prefix, so a concurrent build's data is untouched.
        topics = _delete_retained_messages(f"{TOPIC_PREFIX}{run_id}/")
        certs = _delete_run_certificates(run_id, max_age=None)
    else:
        print(f"age sweep: removing anything older than {MAX_AGE_SECONDS}s")
        topics = _delete_retained_messages(TOPIC_PREFIX)
        certs = _delete_run_certificates(None, max_age=MAX_AGE_SECONDS)

    total = len(topics) + len(certs)
    print(f"deleted {len(topics)} retained message(s) and {len(certs)} certificate(s)")
    # A non-zero count from the age sweep means the event-driven path is not keeping up, which is worth
    # alarming on rather than discovering from a quota error.
    _emit("OrphansDeleted", float(total), mode)
    return {"mode": mode, "retainedMessages": topics, "certificates": certs}
