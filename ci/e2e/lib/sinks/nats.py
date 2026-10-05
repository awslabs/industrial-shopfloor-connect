# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""A NATS subscriber that reads back what the nats target published.

``{"kind": "nats", "service": "nats", "subject": ">"}``. Runs nats-py on its own event loop in a background
thread; connected before SFC starts. Each message becomes the decoded JSON record with ``_subject`` added.
"""

from __future__ import annotations

import asyncio
import json
import threading

from . import Sink, SinkError, marker_of


class NatsSink(Sink):
    kind = "nats"

    def prepare(self):
        service = self.spec.get("service", "nats")
        port = int(self.ctx.env["SFC_E2E_" + service.upper().replace("-", "_") + "_PORT"])
        self.subject = self.spec.get("subject", ">").replace("<marker>", self.ctx.marker)
        self._records: list = []
        self._lock = threading.Lock()
        ready = threading.Event()
        self.loop = asyncio.new_event_loop()
        self._error: list = []

        async def run():
            import nats

            try:
                async def quiet(_e):
                    pass  # nats-py prints a traceback per failed reconnect; outages here are deliberate

                self.nc = await nats.connect(f"nats://127.0.0.1:{port}", error_cb=quiet,
                                             reconnect_time_wait=0.5, max_reconnect_attempts=-1)

                async def handler(msg):
                    text = msg.data.decode("utf-8", errors="replace")
                    with self._lock:
                        try:
                            doc = json.loads(text)
                        except json.JSONDecodeError:
                            self._records.append({"_subject": msg.subject, "_text": text})
                            return
                        for rec in doc if isinstance(doc, list) else [doc]:
                            self._records.append({**rec, "_subject": msg.subject} if isinstance(rec, dict) else rec)

                await self.nc.subscribe(self.subject, cb=handler)
                await self.nc.flush()
            except Exception as e:  # noqa: BLE001
                self._error.append(e)
            finally:
                ready.set()

        self.thread = threading.Thread(target=lambda: (self.loop.run_until_complete(run()), self.loop.run_forever()),
                                       daemon=True)
        self.thread.start()
        if not ready.wait(10) or self._error:
            raise SinkError(f"nats subscriber could not connect to 127.0.0.1:{port}: {self._error}")
        return {}

    def records(self) -> list:
        with self._lock:
            recs = list(self._records)
        return recs if self.spec.get("anyMarker") else [r for r in recs if marker_of(r) in (None, self.ctx.marker)]

    def cleanup(self):
        try:
            asyncio.run_coroutine_threadsafe(self.nc.close(), self.loop).result(5)
            self.loop.call_soon_threadsafe(self.loop.stop)
        except Exception:  # noqa: BLE001
            pass
