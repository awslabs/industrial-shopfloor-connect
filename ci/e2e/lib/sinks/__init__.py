# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Sinks: where a case reads back what SFC delivered.

Every destination - a directory, an SQS queue, a Kinesis stream, an MQTT broker, an OPC-UA server - is a
``Sink``. The runner only knows this interface:

* ``prepare()``   create what the destination needs before SFC starts (directories, a Kafka topic, a
                  subscriber) and return the environment variables the case configuration refers to;
* ``count()``     how many matching records have arrived so far;
* ``records()``   the matching records, decoded to SFC target-data dicts where the destination carries
                  them, in arrival order where the destination preserves it;
* ``cleanup()``   remove what ``prepare()`` created.

The runner calls ``wait()`` **while SFC is still running** and stops SFC only afterwards. sfc-main
installs no JVM shutdown hook, so anything still buffered in a target when the process is stopped is
lost; a case that waited for "the process to flush on exit" would be asserting on data that never comes.
The one exception is ``drain()``: a destination that keeps no order (a case run's own SQS queue) holds an
arbitrary subset of what was sent when the gate passes, so it is read to the end after the stop.

Shared destinations (one SQS queue, one Kinesis stream, the fixture SiteWise assets) are used by several
concurrent builds and by every mode of a case. Sinks for those filter on the run marker the runner
injects into every record as top-level metadata (``$.metadata.marker``), so a record is only counted by
the case run that produced it.
"""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable


class SinkError(RuntimeError):
    pass


@dataclass
class SinkContext:
    """What a sink may use. Built once per case run by the runner."""

    case_id: str
    mode: str
    run_id: str
    marker: str
    workdir: Any               # pathlib.Path
    env: dict                  # stack values and per-run values, already resolved
    started_at: float          # epoch seconds when the case run started
    cleanup: Any = None        # cleanup.Registry
    processes: Callable[[], list] = lambda: []   # the SFC processes of this run, for exit detection
    fatal: Callable[[], Any] = lambda: None       # a fatal log line, if one appeared (Unit.fatal)


def marker_of(record: Any) -> str | None:
    """The run marker of a decoded SFC record, if it carries one."""
    if isinstance(record, dict):
        md = record.get("metadata")
        if isinstance(md, dict):
            return md.get("marker")
    return None


class Sink:
    kind = "abstract"

    def __init__(self, name: str, spec: dict, ctx: SinkContext):
        self.name = name
        self.spec = spec
        self.ctx = ctx

    # -- lifecycle -----------------------------------------------------------------------------------
    def prepare(self) -> dict[str, str]:
        return {}

    def offline_exports(self) -> dict[str, str]:
        """What ``prepare()`` would export, without touching the destination (``run.py --offline-aws``)."""
        return {}

    def cleanup(self) -> None:
        return None

    # -- observation ---------------------------------------------------------------------------------
    def records(self) -> list[Any]:
        raise NotImplementedError

    def count(self) -> int:
        return len(self.records())

    def poll_interval(self) -> float:
        return 0.25

    def drain(self) -> bool:
        """After SFC has stopped: read what is still in flight. True when :meth:`records` may have grown."""
        return False

    def wait(self, n: int, timeout: float) -> list[Any]:
        """Block until at least ``n`` matching records arrived, then return them.

        A process exiting first is reported with its own diagnostics rather than as a timeout: a broken
        configuration should report itself, not masquerade as a slow destination.
        """
        deadline = time.monotonic() + timeout
        seen = 0
        while time.monotonic() < deadline:
            seen = self.count()
            if seen >= n:
                return self.records()
            line = self.ctx.fatal()
            if line:
                raise SinkError(f"{seen}/{n} record(s) in sink {self.name!r} and none can follow - {line}")
            for proc in self.ctx.processes():
                if proc.poll() is not None:
                    raise SinkError(
                        f"{proc.name} exited with {proc.popen.returncode} after {seen}/{n} record(s) "
                        f"reached sink {self.name!r}\n--- stderr ---\n{proc.tail_stderr()}\n"
                        f"--- stdout (tail) ---\n{proc.tail_stdout()}"
                    )
            time.sleep(self.poll_interval())
        raise SinkError(f"only {seen}/{n} record(s) reached sink {self.name!r} ({self.kind}) within {timeout}s")

    def describe(self) -> dict:
        return {"name": self.name, "kind": self.kind}


#: kind -> "module:Class"
REGISTRY = {
    "file": "file:FileDirSink",
    "debug": "debug:DebugSink",
    "s3": "aws:S3Sink",
    "sqs": "aws:SqsSink",
    "sns": "aws:SqsSink",           # SNS is observed through its subscribed sink queue
    "iot": "aws:IotSink",
    "kinesis": "aws:KinesisSink",
    "firehose": "aws:FirehoseSink",
    "lambda": "aws:LambdaEvidenceSink",
    "s3tables": "s3tables:S3TablesSink",
    "sitewise": "sitewise:SiteWiseSink",
    "kafka": "kafka:KafkaSink",
    "mqtt": "mqtt:MqttSink",
    "nats": "nats:NatsSink",
    "opcua": "opcua:OpcuaProbeSink",
    "opcua-writes": "opcua:OpcuaWriteSink",
    "jsonl": "jsonl:JsonlSink",
    "aws-stub": "jsonl:StubAcceptedSink",
    "aws-stub-requests": "jsonl:StubRequestSink",
}


def _expand(value: Any, env: dict) -> Any:
    """``${NAME}`` in a sink spec, from the run's environment - as in the case's configuration."""
    if isinstance(value, str):
        for k, v in env.items():
            value = value.replace("${" + k + "}", str(v))
        return value
    if isinstance(value, dict):
        return {k: _expand(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, env) for v in value]
    return value


def make_sink(name: str, spec: dict, ctx: SinkContext) -> Sink:
    kind = spec.get("kind", "file")
    try:
        module_name, class_name = REGISTRY[kind].split(":")
    except KeyError:
        raise SinkError(f"unknown sink kind {kind!r}; known: {sorted(REGISTRY)}") from None
    module = importlib.import_module(f"{__name__}.{module_name}")
    return getattr(module, class_name)(name, _expand(spec, ctx.env), ctx)
