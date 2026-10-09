#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""A TCP forwarder that can be closed and reopened while it runs - deterministic outages.

    tcpgate.py --listen 127.0.0.1:<port> --to 127.0.0.1:<port>

SIGUSR1 closes the gate: live connections are dropped and new ones are accepted and immediately closed, so
the client sees a reset rather than a hang. SIGUSR2 opens it again. ``--closed`` starts it closed: the
downstream is unreachable from SFC's first connection attempt. Every accepted connection is appended to
``connections.jsonl`` in the working directory, so a case can count how often a client connects. Stopping a broker would also drop the
test's own subscriber; cutting only SFC's path keeps the observer connected.
"""
import argparse
import asyncio
import json
import signal
import time


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", required=True)
    ap.add_argument("--to", required=True)
    ap.add_argument("--closed", action="store_true")
    a = ap.parse_args()
    lhost, lport = a.listen.rsplit(":", 1)
    thost, tport = a.to.rsplit(":", 1)
    state = {"open": not a.closed, "conns": set()}

    async def pipe(reader, writer):
        try:
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    log = open("connections.jsonl", "a", buffering=1)  # one line per accepted connection (cwd = service dir)

    async def handle(creader, cwriter):
        log.write(json.dumps({"t": time.time(), "open": state["open"]}) + "\n")
        if not state["open"]:
            cwriter.close()
            return
        try:
            treader, twriter = await asyncio.open_connection(thost, int(tport))
        except OSError:
            cwriter.close()
            return
        pair = (cwriter, twriter)
        state["conns"].add(pair)
        await asyncio.gather(pipe(creader, twriter), pipe(treader, cwriter))
        state["conns"].discard(pair)

    def close():
        state["open"] = False
        for c, t in list(state["conns"]):
            c.close()
            t.close()
        print("gate closed", flush=True)

    def reopen():
        state["open"] = True
        print("gate open", flush=True)

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGUSR1, close)
    loop.add_signal_handler(signal.SIGUSR2, reopen)
    server = await asyncio.start_server(handle, lhost, int(lport))
    print(f"tcpgate {a.listen} -> {a.to} {'closed' if a.closed else 'open'}", flush=True)
    async with server:
        await server.serve_forever()


asyncio.run(main())
