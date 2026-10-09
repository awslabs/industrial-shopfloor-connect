#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""A local stand-in for the AWS service endpoints SFC's AWS targets call, with scripted faults.

    aws_wire_stub.py --port <p> --spec stub.json --capture capture.jsonl

Every AWS target accepts an ``Endpoint``; pointing it at ``http://127.0.0.1:<port>`` sends the SDK's real
wire requests here. Nothing is ever forwarded to AWS and no signature is validated. The protocols are the
ones the bundled SDK (2.55.2) uses - verified from the protocol factory each generated client is built
with, and from the request marshallers' resource paths:

    service     protocol (SDK factory)                    request
    SQS         AWS JSON 1.0 (AwsJsonProtocolFactory)     POST /, X-Amz-Target AmazonSQS.SendMessageBatch
    Firehose    AWS JSON 1.1                              POST /, X-Amz-Target Firehose_20150804.PutRecordBatch
    Kinesis     CBOR 1.1, or AWS JSON 1.1 when the        POST /, X-Amz-Target Kinesis_20131202.PutRecords
                setting CBOR_ENABLED / aws.cborEnabled
                is false (AwsCborProtocolFactory)
    SNS         AWS Query (AwsQueryProtocolFactory)       POST /, form Action=PublishBatch, XML answer
    S3          REST-XML (AwsXmlProtocolFactory)          PUT /<bucket>/<key> (path style for an IP endpoint),
                                                          body possibly aws-chunked
    Lambda      REST-JSON                                 POST /2015-03-31/functions/{FunctionName}/invocations
    IoT         REST-JSON                                 GET /endpoint (control plane, DescribeEndpoint)
    IoT data    REST-JSON                                 POST /topics/{topic}?qos=&retain=
    S3 Tables   REST-JSON                                 GET /buckets, /namespaces/{arn}, /tables/{arn}; PUT ...
    SiteWise    REST-JSON, host prefix "data."            POST /properties (BatchPutAssetPropertyValue)

``"mode": "iot-credentials"`` turns the stub into the AWS IoT credentials provider instead: HTTPS with the
run PKI (``$SFC_E2E_PKI/server.crt``; client certificates must chain to ``ca.crt``), answering
``GET /role-aliases/<alias>/credentials`` with session credentials whose key id changes per request.

The spec scripts the answer to each request; the last entry of a script repeats::

    {"responses": [...],                     # one script for every request, in arrival order
     "faults": {"q-flaky": [...], "*": [...]},  # or one script per resource (queue name, topic ARN or topic,
                                             # function, stream, bucket, role alias); "*" for the rest
     "iotEndpoint": "stub-ats.iot.local",    # what DescribeEndpoint answers
     "s3tables": {"buckets": [{"name": "b"}], "namespaces": {"b": ["ns"]}, "tables": {"b": [["ns", "t"]]}}}

    a script entry:
       {"status": 400, "error": "ThrottlingException"}   a whole-request error, in the service's own format
       {"status": 500, "error": "InternalError"}
       {"failEntries": [0]}                              partial batch failure: entry 0 rejected
       {"delayMs": 3000}                                 answer late (timeouts)
       {"drop": true}                                    close the connection without answering
       {}                                                success

Every request is appended to ``--capture`` as one JSON line::

    {"op", "service", "resource", "attempt" (n-th request overall), "resourceAttempt" (n-th for this
     resource), "status", "t", "time"/"prevTime" (ISO, this and the previous request for the resource),
     "method", "path", "query", "headers", "accessKeyId", "sessionToken",
     "entries": [{"id", "body", "accepted", ...service fields}]}

``entries[].body`` is the payload as text, already decompressed when the target compressed it (gzip or zip
bytes for S3, Kinesis and IoT; the JSON compression envelope is left as sent, the sinks decode it), so the
``aws-stub`` sink can decode it as SFC records; ``encoding`` records what was undone.

Accepted payloads are also decoded into SFC records - the compression envelope unwrapped, a JSON array
split, concatenated JSON documents separated, anything else kept as ``{"_text": ...}`` - and appended to
``records.jsonl`` and to ``records-<resource>.jsonl`` (the resource with every character outside
``[A-Za-z0-9_.-]`` replaced by ``_``). Each record carries what the wire said about it in ``_``-prefixed
keys: ``_resource``, ``_op``, ``_entryId``, ``_encoding`` (bytes decompressed), ``_wrapper`` and
``_wrapperKeys`` (the compression envelope), ``_zipEntries``, ``_shape`` (object, array, concatenated or text)
and ``_batch`` (records in the payload), plus the service fields (``_key``, ``_contentType``, ``_topic``,
``_retain``, ``_partitionKey``, ``_subject``, ``_messageGroupId``, ``_messageDeduplicationId``, ``_function``,
``_qualifier``, ``_invocationType``). A ``jsonl`` sink on one of those files gives per-destination record
assertions and gates: ``{"kind": "jsonl", "service": "stub", "file": "records-q-gzip.jsonl"}``.
"""
import argparse
import base64
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import socket
import ssl
import struct
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from xml.sax.saxutils import escape

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--spec", required=True)
ap.add_argument("--capture", required=True)
a = ap.parse_args()
SPEC = json.loads(Path(a.spec).read_text())
MODE = SPEC.get("mode", "aws")
lock = threading.Lock()
state = {"n": 0, "per": {}, "last": {}, "cred": 0}
capture = open(a.capture, "a", buffering=1)

ACCOUNT = "000000000000"
REGION = "us-east-1"


# ---------------------------------------------------------------------------------------------- CBOR
# Kinesis speaks CBOR unless the SDK is told otherwise; a minimal codec (RFC 8949: the major types the
# SDK's Jackson CBOR generator emits, definite and indefinite lengths) keeps the stub independent of that.

def cbor_decode(data: bytes):
    pos = 0

    def length(info):
        nonlocal pos
        if info < 24:
            return info
        size = {24: 1, 25: 2, 26: 4, 27: 8}.get(info)
        if size is None:
            return None  # indefinite
        v = int.from_bytes(data[pos:pos + size], "big")
        pos += size
        return v

    def item():
        nonlocal pos
        b = data[pos]
        pos += 1
        major, info = b >> 5, b & 0x1F
        if major == 0:
            return length(info)
        if major == 1:
            return -1 - length(info)
        if major in (2, 3):
            n = length(info)
            if n is None:
                chunks = []
                while data[pos] != 0xFF:
                    chunks.append(item())
                pos += 1
                out = b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)
            else:
                out = data[pos:pos + n]
                pos += n
            return out if major == 2 else out.decode("utf-8", "replace")
        if major == 4:
            n = length(info)
            out = []
            if n is None:
                while data[pos] != 0xFF:
                    out.append(item())
                pos += 1
            else:
                out = [item() for _ in range(n)]
            return out
        if major == 5:
            n = length(info)
            out = {}
            if n is None:
                while data[pos] != 0xFF:
                    k = item()
                    out[k] = item()
                pos += 1
            else:
                for _ in range(n):
                    k = item()
                    out[k] = item()
            return out
        if major == 6:
            length(info)
            return item()
        # major 7
        if info == 20:
            return False
        if info == 21:
            return True
        if info in (22, 23):
            return None
        if info == 25:
            v = struct.unpack(">e", data[pos:pos + 2])[0]
            pos += 2
            return v
        if info == 26:
            v = struct.unpack(">f", data[pos:pos + 4])[0]
            pos += 4
            return v
        if info == 27:
            v = struct.unpack(">d", data[pos:pos + 8])[0]
            pos += 8
            return v
        return None

    return item()


def cbor_encode(v) -> bytes:
    def head(major, n):
        if n < 24:
            return bytes([(major << 5) | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < (1 << (8 * size)):
                return bytes([(major << 5) | info]) + n.to_bytes(size, "big")
        raise ValueError(n)

    if v is None:
        return b"\xf6"
    if v is True:
        return b"\xf5"
    if v is False:
        return b"\xf4"
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, float):
        return b"\xfb" + struct.pack(">d", v)
    if isinstance(v, bytes):
        return head(2, len(v)) + v
    if isinstance(v, str):
        b = v.encode()
        return head(3, len(b)) + b
    if isinstance(v, list):
        return head(4, len(v)) + b"".join(cbor_encode(x) for x in v)
    if isinstance(v, dict):
        return head(5, len(v)) + b"".join(cbor_encode(k) + cbor_encode(x) for k, x in v.items())
    raise TypeError(type(v))


# ------------------------------------------------------------------------------------------- helpers

def md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()  # the SQS SDK validates MD5OfMessageBody


def iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def unchunk(raw: bytes) -> bytes:
    """Undo ``Content-Encoding: aws-chunked``: ``<hex>;chunk-signature=..\\r\\n<data>\\r\\n`` ... ``0;..``."""
    out, pos = bytearray(), 0
    while pos < len(raw):
        eol = raw.find(b"\r\n", pos)
        if eol < 0:
            break
        size = int(raw[pos:eol].split(b";", 1)[0] or b"0", 16)
        pos = eol + 2
        if size == 0:
            break
        out += raw[pos:pos + size]
        pos += size + 2
    return bytes(out)


def unpack(raw: bytes) -> tuple[str, str, list]:
    """Payload bytes as SFC sent them -> (text, encoding undone, zip entry names)."""
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw).decode("utf-8", "replace"), "gzip", []
    if raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
            return b"".join(zf.read(n) for n in names).decode("utf-8", "replace"), "zip", names
    return raw.decode("utf-8", "replace"), "none", []


def b64text(s: str) -> bytes:
    try:
        return base64.b64decode(s)
    except Exception:  # noqa: BLE001
        return s.encode()


_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
_FIELDS = {"key": "_key", "contentType": "_contentType", "topic": "_topic", "retain": "_retain", "qos": "_qos",
           "partitionKey": "_partitionKey", "subject": "_subject", "messageGroupId": "_messageGroupId",
           "messageDeduplicationId": "_messageDeduplicationId", "function": "_function", "qualifier": "_qualifier",
           "invocationType": "_invocationType", "zipEntries": "_zipEntries", "encoding": "_encoding"}


def documents(text: str) -> tuple[list, str]:
    """Text -> (JSON documents, shape). Concatenated documents are what AsArrayWhenBuffered=false sends."""
    dec, pos, docs = json.JSONDecoder(), 0, []
    text = text.strip()
    while pos < len(text):
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        if pos >= len(text):
            break
        try:
            doc, pos = dec.raw_decode(text, pos)
        except ValueError:
            return [], "text"
        docs.append(doc)
    if len(docs) == 1:
        return docs, "array" if isinstance(docs[0], list) else "object"
    return docs, "concatenated" if docs else "empty"


def decoded_records(entry: dict) -> list[dict]:
    """One accepted wire entry -> the SFC records it carries, annotated with what the wire said."""
    text, extra = entry.get("body") or "", {}
    docs, shape = documents(text)
    if shape == "object" and isinstance(docs[0], dict) and "payload" in docs[0] and "compression" in docs[0]:
        env = docs[0]
        inner, enc, names = unpack(b64text(str(env["payload"])))
        extra = {"_wrapper": env.get("compression"), "_wrapperKeys": sorted(env), "_wrapperEncoding": enc}
        if names:
            extra["_zipEntries"] = names
        docs, shape = documents(inner)
        if shape == "text":
            docs = [{"_text": inner}]
    elif shape == "text":
        docs = [{"_text": text}]
    items = docs[0] if shape == "array" else docs
    out = []
    for i, doc in enumerate(items):
        rec = dict(doc) if isinstance(doc, dict) else {"_value": doc}
        rec.update({"_entryId": entry.get("id"), "_shape": shape, "_batch": len(items), "_index": i})
        for k, name in _FIELDS.items():
            if k in entry and entry[k] not in (None, [], ""):
                rec[name] = entry[k]
        rec.update(extra)
        out.append(rec)
    return out


def write_records(resource: str, op: str, entries: list) -> None:
    recs = []
    for e in entries:
        if e.get("accepted"):
            for r in decoded_records(e):
                r.update({"_resource": resource, "_op": op})
                recs.append(r)
    if not recs:
        return
    lines = "".join(json.dumps(r) + "\n" for r in recs)
    base = Path(a.capture).parent
    with lock:
        with open(base / "records.jsonl", "a") as f:
            f.write(lines)
        with open(base / f"records-{_SAFE.sub('_', resource)}.jsonl", "a") as f:
            f.write(lines)


def plan_for(resource: str) -> tuple[dict, int, int, float | None, float]:
    """The scripted answer for this request, and its sequence numbers."""
    faults = SPEC.get("faults") or {}
    now = time.time()
    with lock:
        n = state["n"]
        state["n"] += 1
        k = state["per"].get(resource, 0)
        state["per"][resource] = k + 1
        prev = state["last"].get(resource)
        state["last"][resource] = now
    if resource in faults or "*" in faults:
        script = faults.get(resource) or faults.get("*") or [{}]
        return script[min(k, len(script) - 1)], n, k, prev, now
    script = SPEC.get("responses") or [{}]
    return script[min(n, len(script) - 1)], n, k, prev, now


# --------------------------------------------------------------------------------------- the server

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # -- plumbing -----------------------------------------------------------------------------------
    def log_message(self, *args):
        pass

    def _read_body(self) -> bytes:
        if (self.headers.get("Transfer-Encoding") or "").lower() == "chunked":
            out = bytearray()
            while True:
                size = int(self.rfile.readline().split(b";", 1)[0].strip() or b"0", 16)
                if size == 0:
                    self.rfile.readline()
                    break
                out += self.rfile.read(size)
                self.rfile.readline()
            return bytes(out)
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def _send(self, status: int, body: bytes = b"", ctype: str = "application/json", headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("x-amzn-RequestId", str(uuid.uuid4()))
        self.send_header("x-amz-request-id", uuid.uuid4().hex[:16])
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _auth(self) -> tuple[str | None, str | None]:
        auth = self.headers.get("Authorization") or ""
        key = None
        if "Credential=" in auth:
            key = auth.split("Credential=", 1)[1].split("/", 1)[0]
        return key, self.headers.get("X-Amz-Security-Token")

    def _record(self, *, service, op, resource, plan_info, status, entries, extra=None):
        plan, n, k, prev, now = plan_info
        key, token = self._auth()
        split = urlsplit(self.path)
        rec = {"op": op, "service": service, "resource": resource, "attempt": n + 1, "resourceAttempt": k + 1,
               "status": status, "t": now, "time": iso(now), "prevTime": iso(prev) if prev else None,
               "method": self.command, "path": unquote(split.path),
               "query": {q: v[0] if len(v) == 1 else v for q, v in parse_qs(split.query).items()},
               "headers": {h.lower(): v for h, v in self.headers.items() if h.lower() != "authorization"},
               "accessKeyId": key, "sessionToken": token, "entries": entries}
        if extra:
            rec.update(extra)
        capture.write(json.dumps(rec) + "\n")
        write_records(resource, op, entries)

    # -- dispatch -----------------------------------------------------------------------------------
    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def _dispatch(self):
        raw = self._read_body()
        if (self.headers.get("Content-Encoding") or "").lower().startswith("aws-chunked") or \
                (self.headers.get("x-amz-content-sha256") or "").startswith("STREAMING-"):
            raw = unchunk(raw)
        path = urlsplit(self.path).path
        try:
            if MODE == "iot-credentials":
                return self.iot_credentials(path)
            target = self.headers.get("X-Amz-Target")
            if target:
                return self.aws_json(target, raw)
            if path.startswith("/2015-03-31/functions/"):
                return self.lambda_invoke(path, raw)
            if path == "/endpoint":
                return self.iot_describe_endpoint()
            if path.startswith("/topics/"):
                return self.iot_publish(path, raw)
            if path == "/properties":
                return self.sitewise_put(raw)
            if path.startswith(("/buckets", "/namespaces/", "/tables/", "/get-table")):
                return self.s3tables(path, raw)
            ctype = (self.headers.get("Content-Type") or "").lower()
            if path == "/" and ctype.startswith("application/x-www-form-urlencoded") and b"Action=" in raw:
                return self.aws_query(raw)
            return self.s3(path, raw)
        except (BrokenPipeError, ConnectionResetError):
            return None

    # -- faults -------------------------------------------------------------------------------------
    def _apply_delay_or_drop(self, plan) -> bool:
        if plan.get("delayMs"):
            time.sleep(plan["delayMs"] / 1000.0)
        if plan.get("drop"):
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.close_connection = True
            return True
        return False

    @staticmethod
    def _failed(plan, count: int, status: int) -> set:
        return set(plan.get("failEntries", [])) if status == 200 else set(range(count))

    # -- AWS JSON: SQS, Firehose, Kinesis -----------------------------------------------------------
    def aws_json(self, target: str, raw: bytes):
        prefix, op = target.rsplit(".", 1) if "." in target else ("", target)
        service = {"AmazonSQS": "sqs", "Firehose_20150804": "firehose", "Kinesis_20131202": "kinesis"}.get(prefix, prefix)
        ctype = (self.headers.get("Content-Type") or "").lower()
        cbor = "cbor" in ctype
        try:
            req = cbor_decode(raw) if cbor else json.loads(raw or b"{}")
        except Exception:  # noqa: BLE001
            req = {}
        if service == "sqs":
            resource = str(req.get("QueueUrl", "")).rstrip("/").rsplit("/", 1)[-1]
        else:
            resource = str(req.get("StreamName") or req.get("DeliveryStreamName") or "")
        entries = []
        if op == "SendMessageBatch":
            entries = [{"id": e.get("Id"), "body": e.get("MessageBody", "")} for e in req.get("Entries", [])]
        elif op == "SendMessage":
            entries = [{"id": "0", "body": req.get("MessageBody", "")}]
        elif op in ("PutRecordBatch", "PutRecord"):
            recs = req.get("Records", []) if op == "PutRecordBatch" else [req.get("Record", {})]
            for i, r in enumerate(recs):
                text, enc, _ = unpack(b64text(r.get("Data", "")))
                entries.append({"id": str(i), "body": text, "encoding": enc})
        elif op in ("PutRecords", "PutRecord") and service == "kinesis":
            recs = req.get("Records", []) if op == "PutRecords" else [req]
            for i, r in enumerate(recs):
                data = r.get("Data", b"")
                data = data if isinstance(data, bytes) else b64text(data)
                text, enc, _ = unpack(data)
                entries.append({"id": str(i), "body": text, "encoding": enc, "partitionKey": r.get("PartitionKey")})
        info = plan_for(resource)
        plan = info[0]
        if self._apply_delay_or_drop(plan):
            return None
        status = int(plan.get("status", 200))
        failed = self._failed(plan, len(entries), status)
        for i, e in enumerate(entries):
            e["accepted"] = i not in failed
        self._record(service=service, op=op, resource=resource, plan_info=info, status=status, entries=entries,
                     extra={"contentType": ctype})
        headers = {}
        if status == 200:
            out = self._json_success(service, op, entries, failed)
        else:
            code = plan.get("error", "InternalFailure")
            out = {"__type": f"com.amazonaws.e2e#{code}", "message": f"scripted {code}"}
            if service == "sqs":
                headers["x-amzn-query-error"] = f"{code};{'Sender' if status < 500 else 'Receiver'}"
        if cbor:
            return self._send(status, cbor_encode(out), "application/x-amz-cbor-1.1", headers)
        version = "1.0" if service == "sqs" else "1.1"
        return self._send(status, json.dumps(out).encode(), f"application/x-amz-json-{version}", headers)

    @staticmethod
    def _json_success(service, op, entries, failed) -> dict:
        if op == "SendMessageBatch":
            return {"Successful": [{"Id": e["id"], "MessageId": str(uuid.uuid4()), "MD5OfMessageBody": md5(e["body"])}
                                   for i, e in enumerate(entries) if i not in failed],
                    "Failed": [{"Id": e["id"], "SenderFault": True, "Code": "InvalidParameterValue",
                                "Message": "rejected by the e2e stub"} for i, e in enumerate(entries) if i in failed]}
        if op == "SendMessage":
            return {"MessageId": str(uuid.uuid4()), "MD5OfMessageBody": md5(entries[0]["body"])}
        if op == "PutRecordBatch":
            return {"FailedPutCount": len(failed), "Encrypted": False,
                    "RequestResponses": [{"ErrorCode": "ServiceUnavailableException", "ErrorMessage": "e2e stub"}
                                         if i in failed else {"RecordId": uuid.uuid4().hex} for i in range(len(entries))]}
        if op == "PutRecord" and service == "firehose":
            return {"RecordId": uuid.uuid4().hex, "Encrypted": False}
        if op == "PutRecords":
            return {"FailedRecordCount": len(failed), "EncryptionType": "NONE",
                    "Records": [{"ErrorCode": "ProvisionedThroughputExceededException", "ErrorMessage": "Rate exceeded for shard"}
                                if i in failed else {"SequenceNumber": f"4960{int(time.time() * 1000)}{i:04d}",
                                                     "ShardId": "shardId-000000000000"} for i in range(len(entries))]}
        if op == "PutRecord":
            return {"SequenceNumber": f"4960{int(time.time() * 1000)}", "ShardId": "shardId-000000000000"}
        return {}

    # -- AWS Query: SNS ------------------------------------------------------------------------------
    def aws_query(self, raw: bytes):
        form = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True).items()}
        op = form.get("Action", "")
        resource = form.get("TopicArn", "")
        entries = []
        if op == "PublishBatch":
            i = 1
            while f"PublishBatchRequestEntries.member.{i}.Id" in form:
                p = f"PublishBatchRequestEntries.member.{i}."
                e = {"id": form[p + "Id"], "body": form.get(p + "Message", "")}
                for f in ("Subject", "MessageGroupId", "MessageDeduplicationId", "MessageStructure"):
                    if p + f in form:
                        e[f[0].lower() + f[1:]] = form[p + f]
                entries.append(e)
                i += 1
        elif op == "Publish":
            e = {"id": "0", "body": form.get("Message", "")}
            for f in ("Subject", "MessageGroupId", "MessageDeduplicationId"):
                if f in form:
                    e[f[0].lower() + f[1:]] = form[f]
            entries.append(e)
        info = plan_for(resource)
        plan = info[0]
        if self._apply_delay_or_drop(plan):
            return None
        status = int(plan.get("status", 200))
        failed = self._failed(plan, len(entries), status)
        for i, e in enumerate(entries):
            e["accepted"] = i not in failed
        self._record(service="sns", op=op, resource=resource, plan_info=info, status=status, entries=entries,
                     extra={"topicArn": resource})
        ns = "http://sns.amazonaws.com/doc/2010-03-31/"
        rid = f"<ResponseMetadata><RequestId>{uuid.uuid4()}</RequestId></ResponseMetadata>"
        if status != 200:
            code = plan.get("error", "InternalError")
            kind = "Sender" if status < 500 else "Receiver"
            xml = (f'<ErrorResponse xmlns="{ns}"><Error><Type>{kind}</Type><Code>{escape(code)}</Code>'
                   f"<Message>scripted {escape(code)}</Message></Error><RequestId>{uuid.uuid4()}</RequestId></ErrorResponse>")
        elif op == "PublishBatch":
            ok = "".join(f"<member><Id>{escape(e['id'])}</Id><MessageId>{uuid.uuid4()}</MessageId></member>"
                         for i, e in enumerate(entries) if i not in failed)
            bad = "".join(f"<member><Id>{escape(e['id'])}</Id><Code>InternalError</Code><Message>e2e stub</Message>"
                          f"<SenderFault>false</SenderFault></member>" for i, e in enumerate(entries) if i in failed)
            xml = (f'<PublishBatchResponse xmlns="{ns}"><PublishBatchResult><Successful>{ok}</Successful>'
                   f"<Failed>{bad}</Failed></PublishBatchResult>{rid}</PublishBatchResponse>")
        else:
            xml = (f'<{op}Response xmlns="{ns}"><{op}Result><MessageId>{uuid.uuid4()}</MessageId></{op}Result>'
                   f"{rid}</{op}Response>")
        return self._send(status, xml.encode(), "text/xml")

    # -- REST-JSON errors ---------------------------------------------------------------------------
    def _rest_error(self, plan, status):
        code = plan.get("error", "InternalFailure")
        body = json.dumps({"__type": code, "message": f"scripted {code}", "Message": f"scripted {code}"}).encode()
        return self._send(status, body, "application/json", {"x-amzn-ErrorType": code})

    # -- Lambda ---------------------------------------------------------------------------------------
    def lambda_invoke(self, path: str, raw: bytes):
        function = unquote(path[len("/2015-03-31/functions/"):].split("/invocations", 1)[0])
        query = parse_qs(urlsplit(self.path).query)
        qualifier = query.get("Qualifier", [None])[0]
        resource = function if qualifier is None else f"{function}:{qualifier}"
        text, enc, _ = unpack(raw)
        entries = [{"id": resource, "body": text, "encoding": enc, "function": function, "qualifier": qualifier,
                    "invocationType": self.headers.get("X-Amz-Invocation-Type")}]
        info = plan_for(resource)
        plan = info[0]
        if self._apply_delay_or_drop(plan):
            return None
        status = int(plan.get("status", 202))
        entries[0]["accepted"] = status < 300
        self._record(service="lambda", op="Invoke", resource=resource, plan_info=info, status=status, entries=entries)
        if status >= 300:
            return self._rest_error(plan, status)
        return self._send(status, b"", "application/json", {"X-Amz-Executed-Version": "$LATEST"})

    # -- IoT Core -----------------------------------------------------------------------------------
    def iot_describe_endpoint(self):
        info = plan_for("endpoint")
        plan = info[0]
        if self._apply_delay_or_drop(plan):
            return None
        status = int(plan.get("status", 200))
        self._record(service="iot", op="DescribeEndpoint", resource="endpoint", plan_info=info, status=status, entries=[])
        if status != 200:
            return self._rest_error(plan, status)
        address = SPEC.get("iotEndpoint", "stub-ats.iot.us-east-1.amazonaws.com")
        return self._send(200, json.dumps({"endpointAddress": address}).encode())

    def iot_publish(self, path: str, raw: bytes):
        topic = unquote(path[len("/topics/"):])
        query = parse_qs(urlsplit(self.path).query)
        text, enc, _ = unpack(raw)
        entries = [{"id": topic, "body": text, "encoding": enc, "topic": topic,
                    "retain": query.get("retain", ["false"])[0] == "true", "qos": query.get("qos", [None])[0],
                    "bytes": len(raw)}]
        info = plan_for(topic)
        plan = info[0]
        if self._apply_delay_or_drop(plan):
            return None
        status = int(plan.get("status", 200))
        entries[0]["accepted"] = status == 200
        self._record(service="iot-data", op="Publish", resource=topic, plan_info=info, status=status, entries=entries)
        if status != 200:
            return self._rest_error(plan, status)
        return self._send(200, b"{}")

    # -- SiteWise -----------------------------------------------------------------------------------
    def sitewise_put(self, raw: bytes):
        req = json.loads(raw or b"{}")
        entries = []
        for e in req.get("entries", []):
            entries.append({"id": e.get("entryId"), "body": "", "propertyAlias": e.get("propertyAlias"),
                            "assetId": e.get("assetId"), "propertyId": e.get("propertyId"),
                            "values": [v.get("value") for v in e.get("propertyValues", [])]})
        info = plan_for("properties")
        plan = info[0]
        if self._apply_delay_or_drop(plan):
            return None
        status = int(plan.get("status", 200))
        failed = self._failed(plan, len(entries), status)
        for i, e in enumerate(entries):
            e["accepted"] = i not in failed
        self._record(service="sitewise", op="BatchPutAssetPropertyValue", resource="properties", plan_info=info,
                     status=status, entries=entries, extra={"host": self.headers.get("Host")})
        if status != 200:
            return self._rest_error(plan, status)
        errors = [{"entryId": e["id"], "errors": [{"errorCode": "InvalidRequestException", "errorMessage": "e2e stub",
                                                   "timestamps": []}]} for i, e in enumerate(entries) if i in failed]
        return self._send(200, json.dumps({"errorEntries": errors}).encode())

    # -- S3 Tables (management API only; the Iceberg REST catalog URI is not configurable) ------------
    def s3tables(self, path: str, raw: bytes):
        cfg = SPEC.get("s3tables") or {}
        buckets = [{"name": b["name"], "arn": b.get("arn") or f"arn:aws:s3tables:{REGION}:{ACCOUNT}:bucket/{b['name']}",
                    "ownerAccountId": ACCOUNT, "createdAt": "2026-01-01T00:00:00Z"} for b in cfg.get("buckets", [])]
        by_arn = {b["arn"]: b["name"] for b in buckets}
        parts = path.split("/", 2)
        op, resource, out = "", "", {}
        arn = unquote(parts[2]) if len(parts) > 2 else ""
        if self.command == "GET" and path == "/buckets":
            op, resource, out = "ListTableBuckets", "buckets", {"tableBuckets": buckets}
        elif self.command == "PUT" and path == "/buckets":
            name = json.loads(raw or b"{}").get("name", "")
            op, resource, out = "CreateTableBucket", name, {"arn": f"arn:aws:s3tables:{REGION}:{ACCOUNT}:bucket/{name}"}
        elif path.startswith("/namespaces/"):
            bucket = by_arn.get(arn, arn)
            resource = bucket
            if self.command == "PUT":
                ns = json.loads(raw or b"{}").get("namespace", [])
                op, out = "CreateNamespace", {"tableBucketARN": arn, "namespace": ns}
            else:
                op = "ListNamespaces"
                out = {"namespaces": [{"namespace": [n], "createdAt": "2026-01-01T00:00:00Z", "createdBy": ACCOUNT,
                                       "ownerAccountId": ACCOUNT} for n in (cfg.get("namespaces") or {}).get(bucket, [])]}
        elif path.startswith("/tables/"):
            bucket = by_arn.get(arn.split("/namespace")[0], arn)
            resource, op = bucket, "ListTables"
            out = {"tables": [{"namespace": [ns], "name": t, "type": "customer",
                               "tableARN": f"arn:aws:s3tables:{REGION}:{ACCOUNT}:bucket/{bucket}/table/{uuid.uuid4()}",
                               "createdAt": "2026-01-01T00:00:00Z", "modifiedAt": "2026-01-01T00:00:00Z"}
                              for ns, t in (cfg.get("tables") or {}).get(bucket, [])]}
        else:
            op, resource = "Unsupported", path
        info = plan_for(resource or op)
        plan = info[0]
        if self._apply_delay_or_drop(plan):
            return None
        status = int(plan.get("status", 200))
        self._record(service="s3tables", op=op, resource=resource, plan_info=info, status=status, entries=[],
                     extra={"body": raw.decode("utf-8", "replace")[:2000]})
        if status != 200:
            return self._rest_error(plan, status)
        return self._send(200, json.dumps(out).encode())

    # -- S3 (REST-XML, path style) --------------------------------------------------------------------
    def s3(self, path: str, raw: bytes):
        bucket, _, key = path.lstrip("/").partition("/")
        key = unquote(key)
        text, enc, names = unpack(raw)
        entries = []
        if self.command == "PUT" and key:
            entries = [{"id": key, "body": text, "encoding": enc, "key": key, "zipEntries": names,
                        "contentType": self.headers.get("Content-Type"), "bytes": len(raw)}]
        info = plan_for(bucket)
        plan = info[0]
        if self._apply_delay_or_drop(plan):
            return None
        status = int(plan.get("status", 200))
        for e in entries:
            e["accepted"] = status == 200
        self._record(service="s3", op="PutObject" if self.command == "PUT" else f"{self.command}Object",
                     resource=bucket, plan_info=info, status=status, entries=entries)
        if status != 200:
            code = plan.get("error", "InternalError")
            xml = (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Error><Code>{escape(code)}</Code>"
                   f"<Message>scripted {escape(code)}</Message><RequestId>{uuid.uuid4().hex[:16]}</RequestId></Error>")
            return self._send(status, xml.encode(), "application/xml")
        return self._send(200, b"", "application/xml", {"ETag": f'"{hashlib.md5(raw).hexdigest()}"'})

    # -- the AWS IoT credentials provider (mutual TLS) -------------------------------------------------
    def iot_credentials(self, path: str):
        alias = path.split("/role-aliases/", 1)[-1].split("/credentials", 1)[0] if "/role-aliases/" in path else ""
        cert = self.connection.getpeercert() if isinstance(self.connection, ssl.SSLSocket) else None
        subject = dict(x[0] for x in (cert or {}).get("subject", ())) if cert else {}
        info = plan_for(alias)
        plan = info[0]
        if self._apply_delay_or_drop(plan):
            return None
        status = int(plan.get("status", 200))
        with lock:
            state["cred"] += 1
            n = state["cred"]
        creds = {"accessKeyId": f"ASIAE2EIOTCRED{n:06d}", "secretAccessKey": f"e2e-iot-secret-{n:06d}",
                 "sessionToken": f"e2e-iot-session-token-{n:06d}-{'x' * 16}",
                 "expiration": SPEC.get("expiration", "2099-01-01T00:00:00Z")}
        entries = [{"id": alias, "body": "", "accepted": status == 200, "thingName": self.headers.get("x-amzn-iot-thingname"),
                    "clientCertCN": subject.get("commonName"), **({"issuedAccessKeyId": creds["accessKeyId"],
                                                                   "issuedSessionToken": creds["sessionToken"]}
                                                                  if status == 200 else {})}]
        self._record(service="iot-credentials", op="GetCredentials", resource=alias, plan_info=info, status=status,
                     entries=entries)
        if status != 200:
            return self._send(status, json.dumps({"message": f"scripted {plan.get('error', 'Forbidden')}"}).encode())
        return self._send(200, json.dumps({"credentials": creds}).encode())


class TlsServer(ThreadingHTTPServer):
    """HTTPS that demands a client certificate, handshaking in the request thread (a readiness probe that
    connects and closes must not stall the accept loop)."""

    context: ssl.SSLContext

    def finish_request(self, request, client_address):
        try:
            request = self.context.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return
        super().finish_request(request, client_address)

    def handle_error(self, request, client_address):
        pass


def tls_context() -> ssl.SSLContext:
    tls = SPEC.get("tls") or {}
    pki = Path(os.environ.get("SFC_E2E_PKI", "."))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tls.get("cert", str(pki / "server.crt")), tls.get("key", str(pki / "server.key")))
    ctx.load_verify_locations(tls.get("ca", str(pki / "ca.crt")))
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


if MODE == "iot-credentials":
    server = TlsServer(("127.0.0.1", a.port), Handler)
    server.context = tls_context()
else:
    server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
server.daemon_threads = True
print(f"aws wire stub ({MODE}) on {a.port}", flush=True)
server.serve_forever()
