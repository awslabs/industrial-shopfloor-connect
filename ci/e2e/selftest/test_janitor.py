# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""The janitor deletes only what a run created - never a fixture, never another run's resources.

Runs the real ``ci/cdk/lambda/janitor.py`` against an in-memory fake of the AWS clients it uses, so the
scoping rules are proven without an account. The previous janitor called ``list_retained_messages`` on the
``iot`` client (it only exists on ``iot-data``) and would have deleted every IoT certificate in the account;
both are pinned here.
"""

from __future__ import annotations

import datetime as dt
import importlib
import sys
import types
import unittest
from pathlib import Path

LAMBDA_DIR = Path(__file__).resolve().parents[2] / "cdk" / "lambda"
RUN = "b_0e5e1b9c4a71"
OTHER = "b_ffffffffffff"
NOW = dt.datetime.now(dt.timezone.utc)
OLD = NOW - dt.timedelta(hours=5)
FRESH = NOW - dt.timedelta(minutes=5)
FIXTURE_ARN = "arn:aws:s3tables:us-east-1:1:bucket/sfc-it-fixture-1"


class _Paginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **kw):
        return self.pages(**kw)


class FakeAws:
    def __init__(self):
        self.calls: list[tuple] = []
        self.namespaces = {FIXTURE_ARN: [("sfc_it", OLD), (f"sfc_it_{RUN}_aws_s3t_03_uj", FRESH),
                                         (f"sfc_it_{OTHER}_aws_s3t_03_uj", FRESH), (f"sfc_it_{OTHER}_x_uj", OLD)]}
        self.buckets = [("sfc-it-fixture-1", FIXTURE_ARN, OLD),
                        (f"sfc-it-{RUN.replace('_', '-')}-s3t04-uj", "arn:run", FRESH),
                        (f"sfc-it-{OTHER.replace('_', '-')}-s3t04-uj", "arn:other", FRESH)]
        self.models = [("m-fixture", "sfc-it-fixture-model", OLD), ("m-run", f"sfc-it-{RUN}_aws_sw_02_uj-sim-model", FRESH),
                       ("m-other", f"sfc-it-{OTHER}_aws_sw_02_uj-sim-model", FRESH)]
        self.retained = [(f"sfc/it/{RUN}_aws_iot_02_uj/data", FRESH), (f"sfc/it/{OTHER}_aws_iot_02_uj/data", FRESH),
                         ("sfc/it/fixture", OLD)]
        self.certs = [("c-old-ours", OLD, ["sfc-it-device-us-east-1"]), ("c-fresh-ours", FRESH, ["sfc-it-device-us-east-1"]),
                      ("c-old-foreign", OLD, ["someone-elses-policy"]), ("c-old-shared", OLD, ["sfc-it-device-us-east-1", "x"])]
        self.queues = [(f"sfc-it-{RUN}_aws_sqs_01_ip", FRESH), (f"sfc-it-{OTHER}_aws_sqs_01_ip", FRESH),
                       (f"sfc-it-{OTHER}_aws_sqs_02_uj", OLD), ("SfcIntegrationTest-SnsSinkQueue1", OLD)]

    def client(self, service):
        fake = self
        rec = lambda name: (lambda **kw: fake.calls.append((service, name, kw)) or {})  # noqa: E731
        c = types.SimpleNamespace()
        c.exceptions = types.SimpleNamespace(ResourceNotFoundException=Exception)
        if service == "s3tables":
            def pages(op):
                def gen(**kw):
                    if op == "list_namespaces":
                        yield {"namespaces": [{"namespace": [n], "createdAt": t} for n, t in fake.namespaces.get(kw["tableBucketARN"], [])]}
                    elif op == "list_tables":
                        yield {"tables": [{"name": "t1"}]}
                    elif op == "list_table_buckets":
                        yield {"tableBuckets": [{"name": n, "arn": a, "createdAt": t} for n, a, t in fake.buckets]}
                return gen
            c.get_paginator = lambda op: _Paginator(pages(op))
            c.delete_table, c.delete_namespace, c.delete_table_bucket = rec("delete_table"), rec("delete_namespace"), rec("delete_table_bucket")
        elif service == "iotsitewise":
            def pages(op):
                def gen(**kw):
                    if op == "list_asset_models":
                        yield {"assetModelSummaries": [{"id": i, "name": n, "creationDate": t} for i, n, t in fake.models]}
                    elif op == "list_assets":
                        yield {"assetSummaries": []}
                    elif op == "list_time_series":
                        yield {"TimeSeriesSummaries": []}
                return gen
            c.get_paginator = lambda op: _Paginator(pages(op))
            c.delete_asset, c.delete_asset_model, c.delete_time_series = rec("delete_asset"), rec("delete_asset_model"), rec("delete_time_series")
        elif service == "iot-data":
            def pages(op):
                def gen(**kw):
                    yield {"retainedTopics": [{"topic": t, "lastModifiedTime": int(ts.timestamp() * 1000)} for t, ts in fake.retained]}
                return gen
            c.get_paginator = lambda op: _Paginator(pages(op)) if op == "list_retained_messages" else (_ for _ in ()).throw(AssertionError(op))
            c.publish = rec("publish")
        elif service == "iot":
            def no_retained(op):
                if op == "list_retained_messages":
                    raise AssertionError("ListRetainedMessages does not exist on the iot client")
                return _Paginator(lambda **kw: iter([{"certificates": [
                    {"certificateId": i, "certificateArn": f"arn:{i}", "creationDate": t} for i, t, _ in fake.certs]}]))
            c.get_paginator = no_retained
            c.list_attached_policies = lambda target: {"policies": [{"policyName": p} for i, _, ps in fake.certs if f"arn:{i}" == target for p in ps]}
            c.detach_policy, c.update_certificate, c.delete_certificate = rec("detach_policy"), rec("update_certificate"), rec("delete_certificate")
        elif service == "sqs":
            url = lambda n: f"https://sqs.us-east-1.amazonaws.com/1/{n}"  # noqa: E731
            c.get_paginator = lambda op: _Paginator(lambda QueueNamePrefix="": iter([{"QueueUrls": [
                url(n) for n, _ in fake.queues if n.startswith(QueueNamePrefix)]}]))
            c.get_queue_attributes = lambda QueueUrl, AttributeNames: {"Attributes": {"CreatedTimestamp": str(int(
                next(t for n, t in fake.queues if url(n) == QueueUrl).timestamp()))}}
            c.delete_queue = rec("delete_queue")
        else:
            c.put_metric_data = rec("put_metric_data")
        return c

    def deleted(self, name):
        return [kw for (_s, n, kw) in self.calls if n == name]

    def retained_deleted(self):
        """Topics whose retained message was deleted: a zero-byte retained publish (iot-data has no delete)."""
        return [kw["topic"] for kw in self.deleted("publish") if kw.get("retain") and kw.get("payload") == b""]

    def deleted_queues(self):
        return sorted(kw["QueueUrl"].rsplit("/", 1)[-1] for kw in self.deleted("delete_queue"))


class JanitorScopingTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeAws()
        sys.modules["boto3"] = types.SimpleNamespace(client=self.fake.client)
        import os

        os.environ.update({"FIXTURE_TABLE_BUCKET_ARN": FIXTURE_ARN, "FIXTURE_NAMESPACE": "sfc_it",
                           "DEVICE_POLICY": "sfc-it-device-us-east-1", "MAX_AGE_SECONDS": "7200",
                           "CERT_MIN_AGE_SECONDS": "4200"})
        sys.path.insert(0, str(LAMBDA_DIR))
        import janitor

        self.janitor = importlib.reload(janitor)

    def tearDown(self):
        sys.modules.pop("boto3", None)

    def event(self):
        arn = f"arn:aws:codebuild:us-east-1:1:build/sfc-integration-test:{RUN[2:6]}{RUN[6:10]}-{RUN[10:]}00-0000-0000-000000000000"
        return {"detail": {"build-id": arn, "build-status": "TIMED_OUT"}}

    def test_event_mode_deletes_only_this_run(self):
        out = self.janitor.handler(self.event(), None)
        self.assertEqual(out["runId"], RUN, out)
        self.assertFalse(out["errors"], out["errors"])
        namespaces = [kw["namespace"] for kw in self.fake.deleted("delete_namespace")]
        self.assertEqual(namespaces, [f"sfc_it_{RUN}_aws_s3t_03_uj"])
        self.assertEqual([kw["tableBucketARN"] for kw in self.fake.deleted("delete_table_bucket")], ["arn:run"])
        self.assertEqual([kw["assetModelId"] for kw in self.fake.deleted("delete_asset_model")], ["m-run"])
        self.assertEqual(self.fake.retained_deleted(), [f"sfc/it/{RUN}_aws_iot_02_uj/data"])
        self.assertEqual(self.fake.deleted_queues(), [f"sfc-it-{RUN}_aws_sqs_01_ip"])

    def test_fixtures_are_never_touched(self):
        self.janitor.handler(self.event(), None)
        self.janitor.handler({"mode": "age"}, None)
        self.assertNotIn("sfc_it", [kw["namespace"] for kw in self.fake.deleted("delete_namespace")])
        self.assertNotIn(FIXTURE_ARN, [kw["tableBucketARN"] for kw in self.fake.deleted("delete_table_bucket")])
        self.assertNotIn("m-fixture", [kw["assetModelId"] for kw in self.fake.deleted("delete_asset_model")])
        self.assertNotIn("sfc/it/fixture", self.fake.retained_deleted())
        self.assertNotIn("SfcIntegrationTest-SnsSinkQueue1", self.fake.deleted_queues())

    def test_age_mode_deletes_only_old_run_resources(self):
        out = self.janitor.handler({"mode": "age"}, None)
        self.assertFalse(out["errors"], out["errors"])
        self.assertEqual([kw["namespace"] for kw in self.fake.deleted("delete_namespace")], [f"sfc_it_{OTHER}_x_uj"])
        self.assertEqual(self.fake.deleted_queues(), [f"sfc-it-{OTHER}_aws_sqs_02_uj"])

    def test_destroy_sweep_takes_every_run_but_still_no_fixture(self):
        # {"mode": "age", "maxAgeSeconds": 0} is the pre-`cdk destroy` sweep (ci/README.md section 6).
        out = self.janitor.handler({"mode": "age", "maxAgeSeconds": 0}, None)
        self.assertFalse(out["errors"], out["errors"])
        namespaces = sorted(kw["namespace"] for kw in self.fake.deleted("delete_namespace"))
        self.assertEqual(namespaces, sorted([f"sfc_it_{RUN}_aws_s3t_03_uj", f"sfc_it_{OTHER}_aws_s3t_03_uj",
                                             f"sfc_it_{OTHER}_x_uj"]))
        self.assertNotIn(FIXTURE_ARN, [kw["tableBucketARN"] for kw in self.fake.deleted("delete_table_bucket")])
        self.assertNotIn("m-fixture", [kw["assetModelId"] for kw in self.fake.deleted("delete_asset_model")])
        self.assertEqual(self.fake.deleted_queues(), sorted([f"sfc-it-{RUN}_aws_sqs_01_ip", f"sfc-it-{OTHER}_aws_sqs_01_ip",
                                                             f"sfc-it-{OTHER}_aws_sqs_02_uj"]))

    def test_certificates_only_old_and_exclusively_ours(self):
        self.janitor.handler(self.event(), None)
        self.assertEqual([kw["certificateId"] for kw in self.fake.deleted("delete_certificate")], ["c-old-ours"])


if __name__ == "__main__":
    unittest.main()
