#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Publishes messages for SFC's MQTT and NATS adapters to read.

    publish.py mqtt --port <p> --topic t --payload '{"v": {n}}' [--count 10] [--interval-ms 200] [--retain] [--qos 1]
    publish.py nats --port <p> --subject s --payload '...' [--count 0]
    publish.py mqtt --port <p> --retain --message t1 '{"v": 1}' --message t2 'text' --linger

``{n}`` in the payload is replaced by the message number (0, 1, 2, ...), so a case can assert an exact
sequence. ``--count 0`` publishes forever - the form used as a ``command`` service; a finite count is
the form used in a ``run`` step. Prints ``published <n>`` after each message.

``--message TOPIC PAYLOAD`` (repeatable; the subject for NATS) publishes a fixed list of messages once,
in the order given, instead of ``--topic``/``--payload``/``--count``. ``--payload-hex`` / a ``hex:``
prefix on a ``--message`` payload sends raw bytes (non-UTF-8 or non-ASCII fixtures). After the last
message ``published all`` is printed.

``--linger`` keeps the process alive after publishing. A ``command`` service must still be running once
it is ready, so retained fixtures that have to exist *before* SFC subscribes are published by a
lingering service with ``"readyLog": "published all"``.

``--user``/``--password`` (MQTT) and ``--token`` (NATS) authenticate the publisher.
"""
import argparse
import asyncio
import time


def _bytes(payload: str) -> bytes:
    return bytes.fromhex(payload[4:]) if payload.startswith("hex:") else payload.encode("utf-8")


def messages(a):
    """(n, destination, payload bytes) in publishing order."""
    if a.message:
        for n, (dest, payload) in enumerate(a.message):
            yield n, dest, _bytes(payload)
        return
    dest = a.topic if a.protocol == "mqtt" else a.subject
    n = 0
    while a.count == 0 or n < a.count:
        if a.payload_hex is not None:
            yield n, dest, bytes.fromhex(a.payload_hex)
        else:
            yield n, dest, a.payload.replace("{n}", str(n)).encode("utf-8")
        n += 1


def mqtt(a):
    import paho.mqtt.client as m

    c = m.Client(m.CallbackAPIVersion.VERSION2, client_id=f"e2e-pub-{a.port}-{time.time_ns()}"[:60])
    if a.user is not None:
        c.username_pw_set(a.user, a.password)
    c.connect("127.0.0.1", a.port, keepalive=30)
    c.loop_start()
    for n, topic, p in messages(a):
        info = c.publish(topic, p, qos=a.qos, retain=a.retain)
        info.wait_for_publish(10)
        if not info.is_published():
            raise SystemExit(f"message {n} on {topic} was not acknowledged")
        print(f"published {n}", flush=True)
        time.sleep(a.interval_ms / 1000.0)
    print("published all", flush=True)
    linger()
    c.loop_stop()
    c.disconnect()


async def nats(a):
    import nats as n_

    nc = await n_.connect(f"nats://127.0.0.1:{a.port}", token=a.token)
    for n, subject, p in messages(a):
        await nc.publish(subject, p)
        await nc.flush()
        print(f"published {n}", flush=True)
        await asyncio.sleep(a.interval_ms / 1000.0)
    print("published all", flush=True)
    if a.linger:
        while True:
            await asyncio.sleep(3600)
    await nc.close()


def linger():
    while args.linger:
        time.sleep(3600)


ap = argparse.ArgumentParser()
ap.add_argument("protocol", choices=["mqtt", "nats"])
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--topic")
ap.add_argument("--subject")
ap.add_argument("--payload")
ap.add_argument("--payload-hex", help="raw payload bytes as hex, instead of --payload")
ap.add_argument("--message", nargs=2, action="append", metavar=("DEST", "PAYLOAD"),
                help="publish this fixed message once (repeatable); replaces --topic/--payload/--count")
ap.add_argument("--count", type=int, default=1)
ap.add_argument("--interval-ms", type=int, default=200)
ap.add_argument("--retain", action="store_true")
ap.add_argument("--qos", type=int, default=1)
ap.add_argument("--linger", action="store_true", help="stay alive after publishing (a command service)")
ap.add_argument("--user")
ap.add_argument("--password")
ap.add_argument("--token")
args = ap.parse_args()
if not args.message and args.payload is None and args.payload_hex is None:
    ap.error("--payload, --payload-hex or --message is required")
if args.protocol == "mqtt":
    mqtt(args)
else:
    asyncio.run(nats(args))
