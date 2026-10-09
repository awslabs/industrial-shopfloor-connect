# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""The debug target's output, parsed out of the log of the process that hosts it.

DebugTargetWriter logs each record at INFO as pretty-printed JSON: ``<date> <time> INFO  - {`` followed by the
rest of the document on raw lines (no prefix). Records are found by scanning for that marker and decoding
one JSON document from the brace onward.

The hosting process depends on the mode: sfc-main in-process and uberjar, the target's own service in IPC
mode (``target-<TargetId>``). ``{"kind": "debug", "target": "Dbg"}``.
"""

from __future__ import annotations

import json
import re

from . import Sink, marker_of

_START = re.compile(r"INFO\s+- \{")


class DebugSink(Sink):
    kind = "debug"

    def prepare(self):
        self.target = self.spec.get("target", "DebugTarget")
        return {}

    def _text(self) -> str:
        wanted = f"target-{self.target}"
        procs = self.ctx.processes()
        names = [p.name for p in procs]
        host = wanted if wanted in names else "sfc-main"
        return "\n".join(p.read_stdout() for p in procs if p.name == host)

    def records(self) -> list:
        text = self._text()
        decoder = json.JSONDecoder()
        out = []
        for m in _START.finditer(text):
            start = m.end() - 1
            try:
                doc, _ = decoder.raw_decode(text, start)
            except json.JSONDecodeError:
                continue  # being written
            if isinstance(doc, dict) and ("sources" in doc or "schedule" in doc):
                if self.spec.get("anyMarker") or marker_of(doc) in (None, self.ctx.marker):
                    out.append(doc)
        return out
