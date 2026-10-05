#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""A Modbus-TCP server (pymodbus 3.6) with a fixed, known register map.

    modbus_server.py --port <p> --spec modbus.json

::

    {"unit": 1,
     "coils":    {"0": [1, 0, 1, 1]},          # start address -> values (function code 1)
     "discrete": {"0": [0, 1]},                # function code 2
     "holding":  {"0": [1, 2, 3], "100": [16968, 16384]},   # function code 3
     "input":    {"0": [7, 8, 9]},             # function code 4
     "counters": [{"table": "holding", "address": 10, "step": 1, "periodMs": 200}]}

Addresses are zero-based exactly as the client sends them (``zero_mode``): reading holding register 100
returns the value configured at "100". Counters make a register change deterministically. The server
prints ``modbus server ready`` once it listens.
"""
import argparse
import asyncio
import json
from pathlib import Path

from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.datastore import ModbusSlaveContext as UnitContext  # the pymodbus 3.6 class name
from pymodbus.server import StartAsyncTcpServer

SIZE = 1000
FC = {"coils": 1, "discrete": 2, "holding": 3, "input": 4}


def block(entries: dict) -> ModbusSequentialDataBlock:
    values = [0] * SIZE
    for start, vals in (entries or {}).items():
        for i, v in enumerate(vals):
            values[int(start) + i] = int(v)
    return ModbusSequentialDataBlock(0, values)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--spec", required=True)
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text())

    unit = UnitContext(co=block(spec.get("coils")), di=block(spec.get("discrete")),
                       hr=block(spec.get("holding")), ir=block(spec.get("input")), zero_mode=True)
    context = ModbusServerContext(slaves={int(spec.get("unit", 1)): unit}, single=False)

    async def count(c):
        fc, addr, step = FC[c["table"]], int(c["address"]), int(c.get("step", 1))
        while True:
            await asyncio.sleep(c.get("periodMs", 500) / 1000.0)
            value = unit.getValues(fc, addr, 1)[0]
            unit.setValues(fc, addr, [(value + step) % 65536])

    for c in spec.get("counters", []):
        asyncio.get_running_loop().create_task(count(c))
    print("modbus server ready", flush=True)
    await StartAsyncTcpServer(context=context, address=("127.0.0.1", a.port))


asyncio.run(main())
