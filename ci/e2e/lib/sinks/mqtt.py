# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""An MQTT subscriber that reads back what the mqtt target published.

``{"kind": "mqtt", "service": "broker", "topic": "sfc/#", "qos": 1}``. The subscriber connects to the case's
broker before SFC starts, so nothing published is missed, and resubscribes on reconnect. Each message
becomes the decoded JSON record (an array payload - batching - is flattened) with ``_topic`` added.

For outage cases, cut SFC off with a ``tcpgate`` between SFC and the broker rather than stopping the broker:
the subscriber stays connected, so a record forwarded after recovery cannot race a reconnecting subscriber.
"""

from __future__ import annotations

import json
import threading
import time

from . import Sink, SinkError, marker_of


class MqttSink(Sink):
    kind = "mqtt"

    def prepare(self):
        import paho.mqtt.client as mqtt

        service = self.spec.get("service", "broker")
        port_var = "SFC_E2E_" + service.upper().replace("-", "_") + "_PORT"
        port = int(self.ctx.env[port_var])
        self.topic = self.spec.get("topic", "#").replace("<marker>", self.ctx.marker)
        self.qos = int(self.spec.get("qos", 1))
        self._records: list = []
        self._raw: list = []
        self._lock = threading.Lock()
        self._connected = threading.Event()

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"e2e-sub-{self.ctx.marker}"[:60])

        def on_connect(c, _u, _f, rc, _p=None):
            c.subscribe(self.topic, qos=self.qos)
            self._connected.set()

        def on_message(_c, _u, msg):
            text = msg.payload.decode("utf-8", errors="replace")
            with self._lock:
                self._raw.append({"topic": msg.topic, "payload": text, "retain": msg.retain})
                try:
                    doc = json.loads(text)
                except json.JSONDecodeError:
                    self._records.append({"_topic": msg.topic, "_text": text})
                    return
                for rec in doc if isinstance(doc, list) else [doc]:
                    if isinstance(rec, dict):
                        rec = {**rec, "_topic": msg.topic}
                    self._records.append(rec)

        client.on_connect = on_connect
        client.on_message = on_message
        client.reconnect_delay_set(min_delay=1, max_delay=2)
        client.connect("127.0.0.1", port, keepalive=30)
        client.loop_start()
        self.client = client
        if not self._connected.wait(10):
            raise SinkError(f"mqtt subscriber could not connect to 127.0.0.1:{port}")
        time.sleep(0.2)  # let SUBACK land before SFC publishes
        return {}

    def records(self) -> list:
        with self._lock:
            recs = list(self._records)
        if self.spec.get("anyMarker"):
            return recs
        return [r for r in recs if marker_of(r) in (None, self.ctx.marker) or not isinstance(r, dict)]

    def raw(self) -> list:
        with self._lock:
            return list(self._raw)

    def cleanup(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass
