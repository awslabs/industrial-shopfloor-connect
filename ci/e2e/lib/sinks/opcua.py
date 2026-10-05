# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""OPC-UA read-back.

* ``opcua`` - an independent asyncua client polling nodes that SFC's opcua-target serves::

      {"kind": "opcua", "port": "SFC_E2E_OPCUA_PORT", "path": "", "nodes": {"ctr": "ns=2;s=..."}}

  ``port`` names the environment variable holding the server port (the case config binds opcua-target to
  ``${SFC_E2E_OPCUA_PORT}``, a runner-reserved port exported via ``env``). Each poll that sees a change
  appends one record ``{"values": {name: value}, "types": {name: variant type}}``.

* ``opcua-writes`` - what opcua-writer-target wrote into the asyncua counterpart server, as recorded by
  that server in ``writes.jsonl`` (one ``{"node", "value", "type"}`` line per write).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import Sink


class OpcuaProbeSink(Sink):
    kind = "opcua"

    def prepare(self):
        self.nodes: dict = self.spec["nodes"]
        self._records: list = []
        self._last = None
        self._client = None
        return {}

    def _connect(self):
        from asyncua.sync import Client

        port = self.ctx.env[self.spec.get("port", "SFC_E2E_OPCUA_PORT")]
        url = f"opc.tcp://127.0.0.1:{port}{self.spec.get('path', '')}"
        client = Client(url, timeout=5)
        client.connect()
        self._client = client

    def poll_interval(self):
        return 0.3

    def records(self) -> list:
        try:
            if self._client is None:
                self._connect()
            values, types = {}, {}
            for name, node_id in self.nodes.items():
                node = self._client.get_node(node_id)
                dv = node.read_data_value()
                values[name] = dv.Value.Value
                types[name] = dv.Value.VariantType.name
        except Exception:  # noqa: BLE001 - the server (or the node, created on first write) is not up yet
            self._client = None
            return list(self._records)
        if values != self._last:
            self._records.append({"values": values, "types": types, "_t": time.time()})
            self._last = values
        return list(self._records)

    def cleanup(self):
        try:
            if self._client is not None:
                self._client.disconnect()
        except Exception:  # noqa: BLE001
            pass


class OpcuaWriteSink(Sink):
    kind = "opcua-writes"

    def prepare(self):
        self.path = Path(self.ctx.workdir) / "services" / self.spec.get("service", "opcua") / "writes.jsonl"
        return {}

    def records(self) -> list:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
