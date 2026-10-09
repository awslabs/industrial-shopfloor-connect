# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Teardown for per-run AWS resources - the guarantee, not the convenience.

CodeBuild skips ``post_build`` when a build is ``TIMED_OUT`` or stopped, and those are exactly the runs that
leak. So cleanup is driven from the build's terminal state (an EventBridge rule) plus an hourly sweep.

Scoping rules - the only things ever deleted:

* **S3 Tables**: namespaces in the fixture table bucket whose name starts with ``sfc_it_b_<run>``
  (AutoCreate cases), with their tables; and table buckets named ``sfc-it-b-<run>...``. The fixture
  namespace ``sfc_it`` and its tables are never touched, whatever they contain.
* **SiteWise**: assets and asset models whose name starts with ``sfc-it-b_<run>`` (AssetCreation cases),
  assets first, models once no asset references them; disassociated time series under ``/sfc-it/b_<run>``.
  The fixture model ``sfc-it-fixture-model`` and its two assets never match.
* **IoT**: retained messages under ``sfc/it/b_<run>`` (read via ``iot-data`` - ``ListRetainedMessages`` does
  not exist on the ``iot`` control-plane client, which is what made the previous version crash on every
  call). A retained message is deleted by a zero-byte retained publish - ``iot-data`` has no delete
  operation. Device certificates carry no run id, so they are removed only when they hold the suite's device
  policy **and** are older than any build could be (``CERT_MIN_AGE_SECONDS``) - never a running build's.
* **SQS**: queues named ``sfc-it-b_<run>...``, one per SQS case run. The stack's queues never match.

Run-id derivation must match the runner and the buildspec: split on the LAST colon, because the event
carries the full build ARN while the container sees ``project:uuid``. ``ci/e2e/selftest`` pins this.
"""

from __future__ import annotations

import datetime as dt
import os
import time

RUN_PREFIX = "b_"
MAX_AGE = int(os.environ.get("MAX_AGE_SECONDS", "7200"))
CERT_MIN_AGE = int(os.environ.get("CERT_MIN_AGE_SECONDS", "4200"))
FIXTURE_NAMESPACE = os.environ.get("FIXTURE_NAMESPACE", "sfc_it")


def run_id_from_build_id(build_id: str) -> str:
    uuid = build_id.rsplit(":", 1)[-1]
    return RUN_PREFIX + uuid.replace("-", "")[:12].lower()


def _boto(service: str):
    import boto3  # imported lazily: run_id_from_build_id is unit-tested without the SDK

    return boto3.client(service)


def _age(ts) -> float:
    if ts is None:
        return 0.0
    if isinstance(ts, (int, float)):
        ts = dt.datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts, dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - ts).total_seconds()


def _selected(name: str, prefix: str, run_id: str | None, created, max_age: int) -> bool:
    """True when ``name`` belongs to this run (event mode) or to any run and is old enough (age mode)."""
    if run_id is not None:
        return name.startswith(f"{prefix}{run_id}")
    return name.startswith(f"{prefix}{RUN_PREFIX}") and _age(created) > max_age


# ------------------------------------------------------------------------------------------ S3 Tables

def clean_s3tables(run_id: str | None, deleted: list[str], max_age: int = MAX_AGE) -> None:
    client = _boto("s3tables")
    fixture_arn = os.environ.get("FIXTURE_TABLE_BUCKET_ARN", "")

    def drop_namespace(bucket_arn: str, ns: str) -> None:
        for page in client.get_paginator("list_tables").paginate(tableBucketARN=bucket_arn, namespace=ns):
            for t in page.get("tables", []):
                client.delete_table(tableBucketARN=bucket_arn, namespace=ns, name=t["name"])
                deleted.append(f"table {ns}.{t['name']}")
        client.delete_namespace(tableBucketARN=bucket_arn, namespace=ns)
        deleted.append(f"namespace {ns}")

    if fixture_arn:
        for page in client.get_paginator("list_namespaces").paginate(tableBucketARN=fixture_arn):
            for ns in page.get("namespaces", []):
                name = ns["namespace"][0]
                if name == FIXTURE_NAMESPACE:
                    continue  # never the fixture
                if _selected(name, "sfc_it_", run_id, ns.get("createdAt"), max_age):
                    drop_namespace(fixture_arn, name)

    for page in client.get_paginator("list_table_buckets").paginate():
        for b in page.get("tableBuckets", []):
            if b["arn"] == fixture_arn:
                continue
            # Bucket names allow hyphens only, so the run id appears as b-<12 hex>.
            rid = run_id.replace("_", "-") if run_id else None
            if _selected(b["name"], "sfc-it-", rid, b.get("createdAt"), max_age) or (
                    rid is None and b["name"].startswith("sfc-it-b-") and _age(b.get("createdAt")) > max_age):
                for npage in client.get_paginator("list_namespaces").paginate(tableBucketARN=b["arn"]):
                    for ns in npage.get("namespaces", []):
                        drop_namespace(b["arn"], ns["namespace"][0])
                client.delete_table_bucket(tableBucketARN=b["arn"])
                deleted.append(f"table bucket {b['name']}")


# ------------------------------------------------------------------------------------------ SiteWise

def clean_sitewise(run_id: str | None, deleted: list[str], max_age: int = MAX_AGE) -> None:
    client = _boto("iotsitewise")
    models = []
    for page in client.get_paginator("list_asset_models").paginate():
        for m in page.get("assetModelSummaries", []):
            if _selected(m["name"], "sfc-it-", run_id, m.get("creationDate"), max_age):
                models.append(m)
    pending_models = []
    for m in models:
        remaining = 0
        for page in client.get_paginator("list_assets").paginate(assetModelId=m["id"]):
            for a in page.get("assetSummaries", []):
                if a.get("status", {}).get("state") == "DELETING":
                    remaining += 1
                    continue
                client.delete_asset(assetId=a["id"])
                deleted.append(f"asset {a['name']}")
                remaining += 1
        pending_models.append((m, remaining))
    # Deletion is asynchronous: a model can only go once its assets are gone. Poll briefly; anything left
    # is picked up by the next invocation (the hourly sweep makes this multi-pass by design).
    deadline = time.time() + 240
    for m, remaining in pending_models:
        while remaining and time.time() < deadline:
            remaining = sum(len(p.get("assetSummaries", [])) for p in
                            client.get_paginator("list_assets").paginate(assetModelId=m["id"]))
            if remaining:
                time.sleep(5)
        if not remaining:
            try:
                client.delete_asset_model(assetModelId=m["id"])
                deleted.append(f"asset model {m['name']}")
            except Exception as e:  # noqa: BLE001
                print(f"asset model {m['name']} not deletable yet: {e}")
    alias_prefix = f"/sfc-it/{run_id}" if run_id else f"/sfc-it/{RUN_PREFIX}"
    for page in client.get_paginator("list_time_series").paginate(timeSeriesType="DISASSOCIATED", aliasPrefix=alias_prefix):
        for ts in page.get("TimeSeriesSummaries", page.get("timeSeriesSummaries", [])):
            if run_id is None and _age(ts.get("timeSeriesCreationDate")) <= max_age:
                continue
            client.delete_time_series(alias=ts["alias"])
            deleted.append(f"time series {ts['alias']}")


# ----------------------------------------------------------------------------------------------- IoT

def clean_iot(run_id: str | None, deleted: list[str], max_age: int = MAX_AGE) -> None:
    data = _boto("iot-data")
    prefix = f"sfc/it/{run_id}" if run_id else f"sfc/it/{RUN_PREFIX}"
    for page in data.get_paginator("list_retained_messages").paginate():
        for msg in page.get("retainedTopics", []):
            topic = msg.get("topic", "")
            if not topic.startswith(prefix):
                continue
            if run_id is None and _age(msg.get("lastModifiedTime")) <= max_age:
                continue
            data.publish(topic=topic, qos=1, retain=True, payload=b"")  # deletes it: there is no delete API
            deleted.append(f"retained {topic}")

    policy = os.environ.get("DEVICE_POLICY")
    if not policy:
        return
    iot = _boto("iot")
    for page in iot.get_paginator("list_certificates").paginate():
        for cert in page.get("certificates", []):
            if _age(cert.get("creationDate")) <= CERT_MIN_AGE:
                continue  # possibly a running build's certificate
            arn = cert["certificateArn"]
            attached = [p["policyName"] for p in iot.list_attached_policies(target=arn).get("policies", [])]
            if attached != [policy]:
                continue  # not ours, or shared with something else: leave it
            iot.detach_policy(policyName=policy, target=arn)
            iot.update_certificate(certificateId=cert["certificateId"], newStatus="INACTIVE")
            iot.delete_certificate(certificateId=cert["certificateId"], forceDelete=True)
            deleted.append(f"certificate {cert['certificateId']}")


# ----------------------------------------------------------------------------------------------- SQS

def clean_sqs(run_id: str | None, deleted: list[str], max_age: int = MAX_AGE) -> None:
    client = _boto("sqs")
    prefix = f"sfc-it-{run_id}" if run_id else f"sfc-it-{RUN_PREFIX}"
    for page in client.get_paginator("list_queues").paginate(QueueNamePrefix=prefix):
        for url in page.get("QueueUrls", []):
            if run_id is None:
                attrs = client.get_queue_attributes(QueueUrl=url, AttributeNames=["CreatedTimestamp"])["Attributes"]
                if _age(int(attrs["CreatedTimestamp"])) <= max_age:
                    continue
            client.delete_queue(QueueUrl=url)
            deleted.append(f"queue {url.rsplit('/', 1)[-1]}")


def _emit(value: float, mode: str) -> None:
    try:
        _boto("cloudwatch").put_metric_data(Namespace="SFC/IntegTest", MetricData=[{
            "MetricName": "OrphansDeleted", "Value": value, "Unit": "Count",
            "Dimensions": [{"Name": "Mode", "Value": mode}]}])
    except Exception as e:  # noqa: BLE001
        print(f"could not emit metric: {e}")


def handler(event, _context):  # noqa: ANN001
    """``{"mode": "age"}`` sweeps every run's leftovers older than MAX_AGE_SECONDS; ``"maxAgeSeconds": 0``
    sweeps all of them regardless of age (before ``cdk destroy``, with no build running). Anything else
    is a CodeBuild state-change event and cleans that build's run only."""
    mode = "age" if isinstance(event, dict) and event.get("mode") == "age" else "event"
    max_age = int(event.get("maxAgeSeconds", MAX_AGE)) if mode == "age" else MAX_AGE
    run_id = None
    if mode == "event":
        build_id = ((event or {}).get("detail") or {}).get("build-id", "")
        if not build_id:
            return {"mode": mode, "deleted": []}
        run_id = run_id_from_build_id(build_id)
        print(f"build {build_id} ended as {event['detail'].get('build-status')}; cleaning run {run_id}")
    deleted: list[str] = []
    errors: list[str] = []
    for step in (clean_s3tables, clean_sitewise, clean_iot, clean_sqs):
        try:
            step(run_id, deleted, max_age)
        except Exception as e:  # noqa: BLE001 - one area failing must not stop the others
            errors.append(f"{step.__name__}: {type(e).__name__}: {e}")
    print(f"deleted {len(deleted)}: {deleted}; errors: {errors}")
    # In age mode a non-zero count means the event-driven path is not keeping up - worth alarming on.
    _emit(float(len(deleted)), mode)
    return {"mode": mode, "runId": run_id, "deleted": deleted, "errors": errors}
