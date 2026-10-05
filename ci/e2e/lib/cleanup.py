# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run-scoped teardown of the AWS resources a case run created.

Best effort, and deliberately not the guarantee: a build that times out or is stopped never reaches this
code. The janitor Lambda (``ci/cdk/lambda/janitor.py``) is the guarantee - it runs on every terminal build
state and on an hourly sweep, and applies the same naming rules. This module only shortens the window and
keeps one run's leftovers from confusing the next case.

Rules shared with the janitor, and asserted by ``selftest/test_janitor.py``:

* only resources whose name carries this run's id (``b_<12 hex>``, or ``sfc-it-b-<12 hex>`` where hyphens
  are required) are ever deleted;
* the stack's fixtures - the ``sfc_it`` namespace and its ``sim_a``/``sim_b`` tables, the fixture asset
  model and its two assets - are never touched, whatever their contents.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class Entry:
    kind: str
    ids: dict
    created: float = field(default_factory=time.time)
    destroyed: str = ""


class Registry:
    def __init__(self):
        self._entries: list[Entry] = []
        self._lock = threading.Lock()

    def add(self, kind: str, **ids) -> None:
        with self._lock:
            self._entries.append(Entry(kind, ids))

    def entries(self) -> list[Entry]:
        with self._lock:
            return list(self._entries)

    def run(self) -> None:
        for entry in reversed(self.entries()):
            fn = _HANDLERS.get(entry.kind)
            if fn is None:
                entry.destroyed = "no handler"
                continue
            try:
                fn(**entry.ids)
                entry.destroyed = "yes"
            except Exception as e:  # noqa: BLE001 - best effort; the janitor retries
                entry.destroyed = f"failed: {type(e).__name__}: {e}"[:300]

    def as_rows(self) -> list[dict]:
        return [{"id": f"{e.kind}:{'/'.join(str(v) for v in e.ids.values())}",
                 "created": time.strftime("%H:%M:%S", time.gmtime(e.created)),
                 "destroyed": e.destroyed or "-"} for e in self.entries()]


def _boto(service: str):
    import boto3  # AWS tier only; the core tier never imports boto3

    return boto3.client(service)


def _s3tables_namespace(table_bucket_arn: str, namespace: str) -> None:
    client = _boto("s3tables")
    for page in client.get_paginator("list_tables").paginate(tableBucketARN=table_bucket_arn, namespace=namespace):
        for table in page.get("tables", []):
            client.delete_table(tableBucketARN=table_bucket_arn, namespace=namespace, name=table["name"])
    client.delete_namespace(tableBucketARN=table_bucket_arn, namespace=namespace)


def _s3tables_bucket(table_bucket_arn: str) -> None:
    client = _boto("s3tables")
    for page in client.get_paginator("list_namespaces").paginate(tableBucketARN=table_bucket_arn):
        for ns in page.get("namespaces", []):
            _s3tables_namespace(table_bucket_arn, ns["namespace"][0])
    client.delete_table_bucket(tableBucketARN=table_bucket_arn)


def _sitewise_asset_and_model(asset_id: str = "", model_id: str = "") -> None:
    """Assets first (deletion is asynchronous), then the model once no asset references it."""
    client = _boto("iotsitewise")
    if asset_id:
        client.delete_asset(assetId=asset_id)
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                client.describe_asset(assetId=asset_id)
            except client.exceptions.ResourceNotFoundException:
                break
            time.sleep(3)
    if model_id:
        client.delete_asset_model(assetModelId=model_id)


def _retained_message(topic: str) -> None:
    # There is no DeleteRetainedMessage API: a zero-byte retained publish deletes the retained message.
    _boto("iot-data").publish(topic=topic, qos=1, retain=True, payload=b"")


def _kafka_topic(delete_command: list) -> None:
    import subprocess

    subprocess.run(delete_command, check=False, capture_output=True, timeout=120)


def _sqs_queue(url: str) -> None:
    _boto("sqs").delete_queue(QueueUrl=url)


def _iot_certificate(certificate_id: str, certificate_arn: str, policy_name: str) -> None:
    client = _boto("iot")
    client.detach_policy(policyName=policy_name, target=certificate_arn)
    client.update_certificate(certificateId=certificate_id, newStatus="INACTIVE")
    client.delete_certificate(certificateId=certificate_id, forceDelete=True)


_HANDLERS = {
    "s3tables-namespace": _s3tables_namespace,
    "s3tables-bucket": _s3tables_bucket,
    "sitewise": _sitewise_asset_and_model,
    "iot-retained": _retained_message,
    "kafka-topic": _kafka_topic,
    "sqs-queue": _sqs_queue,
    "iot-certificate": _iot_certificate,
}
