# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Read-back for the message and object AWS destinations: S3, SQS, SNS (via its sink queue), IoT Core (via the
topic rule's sink queue, or a retained message), Kinesis, Firehose and Lambda (via its evidence objects).

Every reader decodes what the target actually writes - verified per writer:

* S3: one object per flush; the body is a JSON **array** (``AsArrayWhenBuffered`` defaults to true); GZip or
  Zip compression is raw bytes.
* SQS / SNS: one message per record; with compression the body is ``{"compression": "GZIP", "payload": b64}``.
* IoT Core (rule): ``{"payload": base64(record JSON), "topic": ..., "ts": ...}``.
* Kinesis: one record per SFC record; the partition key is the record's index in its batch
  (AwsKinesisTargetWriter.kt:342), so it cannot identify a run - the run marker in the payload does.
* Firehose: objects hold records as JSON + ``"\\n"``; pretty-printed records span lines, so the body is
  parsed as concatenated JSON documents, not NDJSON.
* Lambda: the target invokes asynchronously; the evidence function writes ``{"payload": <event>}`` objects.

Shared destinations are filtered by ``$.metadata.marker``. SQS messages that belong to another run are made
visible again immediately, so concurrent cases do not steal each other's data. The SQS target itself writes to
a queue of each case run's own (``SqsSink``).
"""

from __future__ import annotations

import base64
import gzip
import io
import json
import time
import zipfile

from . import Sink, SinkError, marker_of
from .file import iter_json_documents


def client(service: str):
    import boto3

    return boto3.client(service)


def decode_body(raw: bytes) -> list:
    """Bytes as written by a target -> records. Handles gzip, zip, and the compression envelope."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    elif raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            raw = b"".join(zf.read(n) for n in zf.namelist())
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    out: list = []
    for doc in iter_json_documents(text):
        if isinstance(doc, dict) and "payload" in doc and str(doc.get("compression", "")).upper() in ("GZIP", "ZIP"):
            out.extend(decode_body(base64.b64decode(doc["payload"])))
        elif isinstance(doc, list):
            out.extend(doc)
        else:
            out.append(doc)
    return out


class _Filtered(Sink):
    """Accumulates decoded records, keeping only this run's (unless ``"anyMarker": true``)."""

    #: A destination that keeps no order (a queue, asynchronous delivery): when the gate passes it holds an
    #: arbitrary subset of what was sent, so it is read to the end once SFC has stopped.
    unordered = False

    def __init__(self, name, spec, ctx):
        super().__init__(name, spec, ctx)
        self._records: list = []
        self._seen: set = set()

    def _keep(self, record) -> bool:
        return self.spec.get("anyMarker") or marker_of(record) == self.ctx.marker

    def _add(self, key, records) -> None:
        if key in self._seen:
            return
        self._seen.add(key)
        self._records.extend(r for r in records if self._keep(r))

    def records(self) -> list:
        self.poll()
        return list(self._records)

    def count(self) -> int:
        self.poll()
        return len(self._records)

    def drain(self, quiet: float = 8.0, limit: float = 60.0) -> bool:
        """Poll until no new record of this run has arrived for ``quiet`` seconds."""
        if not self.unordered:
            return False
        deadline = time.monotonic() + limit
        count, changed = len(self._records), time.monotonic()
        while time.monotonic() < deadline and time.monotonic() - changed < quiet:
            self.poll()
            if len(self._records) != count:
                count, changed = len(self._records), time.monotonic()
            time.sleep(self.poll_interval())
        return True

    def poll(self) -> None:
        raise NotImplementedError


class S3Sink(_Filtered):
    """``{"kind": "s3", "prefix": "s3-target/<marker>/"}`` - the prefix defaults to the run's own."""

    kind = "s3"

    def prepare(self):
        self.bucket = self.spec.get("bucket") or self.ctx.env["SFC_E2E_BUCKET"]
        self.prefix = self.spec.get("prefix") or f"s3-target/{self.ctx.marker}/"
        self.s3 = client("s3")
        self.keys: list[str] = []
        return {"SFC_E2E_S3_PREFIX": self.prefix.rstrip("/")}

    def offline_exports(self):
        return {"SFC_E2E_S3_PREFIX": (self.spec.get("prefix") or f"s3-target/{self.ctx.marker}/").rstrip("/")}

    def poll_interval(self):
        return 1.0

    def poll(self):
        objs = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self.prefix):
            objs.extend(page.get("Contents", []))
        for obj in sorted(objs, key=lambda o: (o["LastModified"], o["Key"])):
            if obj["Key"] in self._seen:
                continue
            body = self.s3.get_object(Bucket=self.bucket, Key=obj["Key"])["Body"].read()
            self.keys.append(obj["Key"])
            # S3 objects under the run's own prefix are this run's by construction.
            self._seen.add(obj["Key"])
            self._records.extend(decode_body(body))

    def describe(self):
        return {"name": self.name, "kind": self.kind, "prefix": self.prefix, "objects": len(self.keys)}


#: A case run's own queue: 1 MiB messages, as SFC's SQS_MAX_BATCH_MSG_SIZE (AwsSqsTargetWriter.kt:416) and the
#: limit AWS raised SQS to in 2025.
QUEUE_ATTRIBUTES = {"MaximumMessageSize": "1048576", "MessageRetentionPeriod": "3600", "VisibilityTimeout": "10",
                    "SqsManagedSseEnabled": "true"}


class SqsSink(_Filtered):
    """``{"kind": "sqs"}``: the queue ``sfc-it-<marker>``, created for this case run before SFC starts (as
    ``${SFC_E2E_SQS_QUEUE_URL}``) and deleted afterwards. ``{"kind": "sns"}`` reads the stack's SNS sink queue.

    Not one shared queue: a standard queue does not keep order, and with every concurrent case run reading
    it each sink received mostly other runs' messages, put them back and fell behind - when its gate passed
    it held an arbitrary subset of its own records. A queue of its own is read to the end once SFC has
    stopped (:meth:`drain`), so the records are everything SFC delivered.
    """

    kind = "sqs"
    own = False
    unordered = True

    def prepare(self):
        self.sqs = client("sqs")
        if self.spec.get("kind", "sqs") == "sqs" and not self.spec.get("queueUrl"):
            self.url = self.sqs.create_queue(QueueName=f"sfc-it-{self.ctx.marker}", Attributes=QUEUE_ATTRIBUTES)["QueueUrl"]
            self.own = True
            if self.ctx.cleanup is not None:
                self.ctx.cleanup.add("sqs-queue", url=self.url)
            time.sleep(1)  # a new queue takes about a second before it can be used
            return {"SFC_E2E_SQS_QUEUE_URL": self.url}
        default = "SFC_E2E_SNS_SINK_QUEUE_URL" if self.spec.get("kind") == "sns" else "SFC_E2E_SQS_QUEUE_URL"
        self.url = self.spec.get("queueUrl") or self.ctx.env[self.spec.get("queueEnv", default)]
        return {}

    def poll_interval(self):
        return 0.2

    def drain(self, quiet: float = 8.0, limit: float = 60.0) -> bool:
        """The run's own queue is read until two long polls in a row come back empty; a shared one (SNS, the
        IoT rule's) until no record of this run has arrived for ``quiet`` seconds."""
        if not self.own:
            return super().drain(quiet, limit)
        deadline, empty = time.monotonic() + limit, 0
        while empty < 2 and time.monotonic() < deadline:
            empty = 0 if self._receive(wait=2) else empty + 1
        return True

    def poll(self):
        self._receive(wait=1)

    def _receive(self, wait: int) -> int:
        resp = self.sqs.receive_message(QueueUrl=self.url, MaxNumberOfMessages=10, WaitTimeSeconds=wait,
                                        VisibilityTimeout=30, MessageAttributeNames=["All"])
        mine, foreign = [], []
        for msg in resp.get("Messages", []):
            try:
                recs = decode_body(msg["Body"].encode())
            except json.JSONDecodeError:
                foreign.append(msg)
                continue
            if self.spec.get("anyMarker") or any(marker_of(r) == self.ctx.marker for r in recs):
                self._add(msg["MessageId"], recs)
                mine.append(msg)
            else:
                foreign.append(msg)
        if mine:
            self.sqs.delete_message_batch(QueueUrl=self.url, Entries=[
                {"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]} for i, m in enumerate(mine)])
        if foreign:
            # Someone else's - make it visible again at once.
            self.sqs.change_message_visibility_batch(QueueUrl=self.url, Entries=[
                {"Id": str(i), "ReceiptHandle": m["ReceiptHandle"], "VisibilityTimeout": 0} for i, m in enumerate(foreign)])
        return len(mine) + len(foreign)


class IotSink(SqsSink):
    """IoT Core, observed through the topic rule ``sfc/it/#`` -> sink queue (base64 payload).

    ``{"kind": "iot", "retainedTopic": "sfc/it/<marker>/data"}`` instead reads the retained message.
    """

    kind = "iot"

    @property
    def unordered(self):
        return not self.retained  # the rule's queue; a retained message is one value

    def prepare(self):
        self.retained = self.spec.get("retainedTopic")
        if self.retained:
            self.retained = self.retained.replace("<marker>", self.ctx.marker)
            self.data = client("iot-data")
            if self.ctx.cleanup is not None:
                self.ctx.cleanup.add("iot-retained", topic=self.retained)
            return {"SFC_E2E_IOT_TOPIC": self.retained}
        self.url = self.ctx.env["SFC_E2E_IOT_SINK_QUEUE_URL"]
        self.sqs = client("sqs")
        return {"SFC_E2E_IOT_TOPIC_ROOT": f"sfc/it/{self.ctx.marker}"}

    def offline_exports(self):
        retained = self.spec.get("retainedTopic")
        if retained:
            return {"SFC_E2E_IOT_TOPIC": retained.replace("<marker>", self.ctx.marker)}
        return {"SFC_E2E_IOT_TOPIC_ROOT": f"sfc/it/{self.ctx.marker}"}

    def poll(self):
        if self.retained:
            try:
                resp = self.data.get_retained_message(topic=self.retained)
            except Exception:  # noqa: BLE001 - not there yet
                return
            self._add(resp.get("lastModifiedTime"), decode_body(resp["payload"]))
            return
        resp = self.sqs.receive_message(QueueUrl=self.url, MaxNumberOfMessages=10, WaitTimeSeconds=1, VisibilityTimeout=30)
        mine, foreign = [], []
        for msg in resp.get("Messages", []):
            body = json.loads(msg["Body"])
            recs = decode_body(base64.b64decode(body.get("payload", "")))
            for r in recs:
                if isinstance(r, dict):
                    r.setdefault("_topic", body.get("topic"))
            if any(marker_of(r) == self.ctx.marker for r in recs):
                self._add(msg["MessageId"], recs)
                mine.append(msg)
            else:
                foreign.append(msg)
        if mine:
            self.sqs.delete_message_batch(QueueUrl=self.url, Entries=[
                {"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]} for i, m in enumerate(mine)])
        if foreign:
            self.sqs.change_message_visibility_batch(QueueUrl=self.url, Entries=[
                {"Id": str(i), "ReceiptHandle": m["ReceiptHandle"], "VisibilityTimeout": 0} for i, m in enumerate(foreign)])


class KinesisSink(_Filtered):
    """Reads the shared stream from just before the case started (AT_TIMESTAMP), filtered by marker."""

    kind = "kinesis"

    def prepare(self):
        self.stream = self.spec.get("stream") or self.ctx.env["SFC_E2E_KINESIS_STREAM"]
        self.kinesis = client("kinesis")
        self.iterators: dict[str, str] = {}
        return {}

    def poll_interval(self):
        return 1.0  # GetRecords is limited to 5 calls per second per shard, shared by every concurrent reader

    def poll(self):
        if not self.iterators:
            for shard in self.kinesis.list_shards(StreamName=self.stream)["Shards"]:
                it = self.kinesis.get_shard_iterator(StreamName=self.stream, ShardId=shard["ShardId"],
                                                     ShardIteratorType="AT_TIMESTAMP",
                                                     Timestamp=self.ctx.started_at - 10)["ShardIterator"]
                self.iterators[shard["ShardId"]] = it
        for shard_id, it in list(self.iterators.items()):
            for _ in range(5):
                try:
                    resp = self.kinesis.get_records(ShardIterator=it, Limit=1000)
                except Exception as e:  # noqa: BLE001 - throughput exceeded: back off and retry next poll
                    if "ProvisionedThroughputExceeded" in str(e):
                        time.sleep(1)
                        break
                    raise
                for rec in resp.get("Records", []):
                    try:
                        records = decode_body(rec["Data"])
                    except (json.JSONDecodeError, OSError, zipfile.BadZipFile):
                        records = []  # the stream is shared: someone else's non-JSON record is not ours
                    self._add(rec["SequenceNumber"], records)
                it = resp.get("NextShardIterator") or it
                self.iterators[shard_id] = it
                if resp.get("MillisBehindLatest", 0) == 0:
                    break


class FirehoseSink(_Filtered):
    """Objects Firehose delivered after the case started; 0 s buffering makes this seconds, not minutes."""

    kind = "firehose"
    unordered = True

    def prepare(self):
        self.bucket = self.ctx.env["SFC_E2E_BUCKET"]
        self.prefix = self.spec.get("prefix", "firehose/data/")
        self.s3 = client("s3")
        return {}

    def poll_interval(self):
        return 2.0

    def poll(self):
        import datetime as dt

        since = dt.datetime.fromtimestamp(self.ctx.started_at - 120, dt.timezone.utc)
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self.prefix):
            for obj in page.get("Contents", []):
                if obj["LastModified"] < since or obj["Key"] in self._seen:
                    continue
                body = self.s3.get_object(Bucket=self.bucket, Key=obj["Key"])["Body"].read()
                try:
                    records = decode_body(body)
                except json.JSONDecodeError:
                    # The stream is shared: one case's non-JSON output (a formatter, a template) must not
                    # break every other case's read. Line by line, and what is not JSON stays as text.
                    records = []
                    for line in body.decode("utf-8", errors="replace").splitlines():
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            records.append({"text": line})
                self._add(obj["Key"], records)


class LambdaEvidenceSink(_Filtered):
    """What the evidence function received, under ``lambda-evidence/<marker>/``."""

    kind = "lambda"
    unordered = True  # asynchronous invocation

    def prepare(self):
        self.bucket = self.ctx.env["SFC_E2E_BUCKET"]
        self.prefix = f"lambda-evidence/{self.ctx.marker}/"
        self.s3 = client("s3")
        return {}

    def poll_interval(self):
        return 1.0

    def poll(self):
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self.prefix):
            for obj in sorted(page.get("Contents", []), key=lambda o: o["Key"]):
                if obj["Key"] in self._seen:
                    continue
                doc = json.loads(self.s3.get_object(Bucket=self.bucket, Key=obj["Key"])["Body"].read())
                # One record, a batch (array) or SFC's compression envelope - decode_body opens all three.
                payload = doc.get("payload")
                self._seen.add(obj["Key"])
                self._records.extend(decode_body(json.dumps(payload).encode()) if payload is not None else [])


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise SinkError(message)
