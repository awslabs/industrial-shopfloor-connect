# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""MSK read-back over the public IAM endpoint. A topic per case run, created before SFC starts and deleted afterwards.

``prepare()`` exports ``SFC_E2E_KAFKA_BOOTSTRAP`` and ``SFC_E2E_KAFKA_TOPIC`` for the case configuration
(``BootstrapBrokers: ["${SFC_E2E_KAFKA_BOOTSTRAP}"]``, ``TopicName: "${SFC_E2E_KAFKA_TOPIC}"``). Reading is by
partition 0 from the earliest offset, so no consumer group - and no group permissions - are involved.

``{"kind": "kafka", "format": "json"}`` (default) parses each message as a JSON record. ``"format": "raw"``
keeps the value as text in ``{"value": ..., "headers": {...}}`` records, with the headers SFC sets - ``serial``
plus any configured ``Headers``, which is where a non-JSON case carries the marker. ``"format": "headers"``
is the same without the value, for binary values (protobuf serialization), which would break the line framing.
"""

from __future__ import annotations

import json

from . import Sink, marker_of
from .. import kafka_admin
from .file import iter_json_documents


class KafkaSink(Sink):
    kind = "kafka"

    def prepare(self):
        self.bootstrap = kafka_admin.bootstrap(self.ctx.env.get("SFC_E2E_MSK_CLUSTER_NAME"), self.ctx.env.get("SFC_E2E_MSK_BOOTSTRAP"))
        self.topic = kafka_admin.topic_name(self.ctx.marker)
        kafka_admin.create_topic(self.bootstrap, self.topic)
        if self.ctx.cleanup is not None:
            self.ctx.cleanup.add("kafka-topic", delete_command=kafka_admin.delete_command(self.bootstrap, self.topic))
        self.format = self.spec.get("format", "json")
        self._cache: list = []
        return {"SFC_E2E_KAFKA_BOOTSTRAP": self.bootstrap, "SFC_E2E_KAFKA_TOPIC": self.topic}

    def offline_exports(self):
        return {"SFC_E2E_KAFKA_BOOTSTRAP": f"127.0.0.1:{self.ctx.env['SFC_E2E_DEAD_PORT']}",
                "SFC_E2E_KAFKA_TOPIC": kafka_admin.topic_name(self.ctx.marker)}

    def poll_interval(self):
        return 3.0  # each poll starts a console consumer JVM

    def records(self) -> list:
        n = kafka_admin.end_offset(self.bootstrap, self.topic)
        lines = kafka_admin.consume(self.bootstrap, self.topic, max_messages=n, timeout_ms=8000,
                                    headers=self.format in ("raw", "headers"),
                                    values=self.format != "headers") if n else []
        out = []
        if self.format in ("raw", "headers"):
            for line in lines:
                headers_part, _, value = line.partition("\t")
                headers = dict(h.split(":", 1) for h in headers_part.split("|") if ":" in h)
                out.append({"value": value, "headers": headers, "metadata": {"marker": headers.get("marker")}})
        else:
            # SFC pretty-prints its JSON (TargetData.kt:78), so a message spans several lines: the output is
            # read as a stream of documents, not line by line.
            try:
                out = [d for d in iter_json_documents("\n".join(lines)) if isinstance(d, dict)]
            except json.JSONDecodeError:
                out = []
        self._cache = [r for r in out if self.spec.get("anyMarker") or marker_of(r) == self.ctx.marker]
        return list(self._cache)

    def describe(self):
        return {"name": self.name, "kind": self.kind, "topic": self.topic}
