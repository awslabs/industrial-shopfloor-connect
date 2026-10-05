#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""An OPC-UA server (python asyncua) for the OPC-UA adapter and opcua-writer-target cases, and an OPC-UA
probe client for the opcua-target cases.

Server::

    opcua_server.py --port <p> --spec opcua_server.json --writes writes.jsonl

The spec declares the address space and how it changes::

    {"path": "/e2e",                      # endpoint path, default ""
     "namespace": "urn:sfc:e2e",          # registered namespace; node ids are ns=<idx>;s=<id>
     "security": ["None"],                # any of None, Basic256Sha256_Sign, Basic256Sha256_SignAndEncrypt
     "certificate": "server.der", "privateKey": "server.pem",   # relative to the PKI dir, for security
     "anonymous": true,                   # offer the Anonymous user token (default true)
     "users": {"e2e": "secret"},          # offer the UserName token; only these credentials are accepted
     "nodes": [
       {"id": "Counter", "type": "Int32", "value": 0, "step": 1, "periodMs": 200},
       {"id": "Setpoint", "type": "Double", "value": 0.0, "writable": true},
       {"id": "Tags", "type": "String", "value": ["a", "b"]},  # a list value is an array node
       {"id": "Instance", "type": "String", "value": "$instance"}   # unique per server process
     ],
     "events": {"periodMs": 500, "message": "e2e event", "severity": 500,
                "messageFormat": "e2e-{n}"}}    # optional; the default message is "<message> <n>"

``step`` with ``periodMs`` makes a node count deterministically; a value the client writes is appended to
``--writes`` as ``{"node", "value", "type", "status", "request", "batch", "sourceTimestamp", "t"}``, which
is what the opcua-writes sink reads. ``request`` numbers the client's Write requests from 1 and ``batch``
is the number of nodes in that request, so a case can assert how a writer grouped its writes. The value
``$instance`` is replaced by a token unique to the server process, so a case can tell the data of a
restarted server from the data of the first one. The namespace index is printed as ``namespace-index <n>``
and the server prints ``opcua server ready`` once the endpoint is up.

Probe (a client, run to completion from a case step)::

    opcua_server.py --probe probe.json --url opc.tcp://127.0.0.1:<p>/sfc --out probe.jsonl

    {"timeoutSeconds": 20,                # connect and waitFor deadline
     "waitFor": ["nsu=urn:amazonaws.sfc;s=S/Sim/Iv"],     # nodes whose Value must be readable first
     "ops": [
       {"op": "read", "name": "iv", "node": "ns=2;s=S/Sim/Iv"},
       {"op": "write", "name": "w", "node": "ns=2;s=S/Sim/Iv", "value": 7, "type": "Int32"},
       {"op": "browse", "name": "p", "path": ["0:Objects", "2:SFC", "2:S"]},
       {"op": "children", "name": "c", "node": "ns=2;s=S/Sim"},
       {"op": "endpoints", "name": "e"},
       {"op": "subscribe", "name": "s", "node": "ns=2;s=S/Sim/Ctr", "count": 10, "publishingMs": 100}
     ]}

Every op appends one JSON line ``{"op", "name", ...}`` to ``--out`` (``subscribe`` one line per
notification); a failure is recorded as ``"status"``/``"error"`` rather than raised, so the case asserts on
it. Node ids may use ``nsu=<namespace uri>;`` instead of ``ns=<index>;``.
"""
import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from asyncua import Client, Server, ua
from asyncua.common.callback import CallbackType
from asyncua.crypto.permission_rules import User, UserRole

TYPES = {
    "Boolean": ua.VariantType.Boolean, "SByte": ua.VariantType.SByte, "Byte": ua.VariantType.Byte,
    "Int16": ua.VariantType.Int16, "UInt16": ua.VariantType.UInt16, "Int32": ua.VariantType.Int32,
    "UInt32": ua.VariantType.UInt32, "Int64": ua.VariantType.Int64, "UInt64": ua.VariantType.UInt64,
    "Float": ua.VariantType.Float, "Double": ua.VariantType.Double, "String": ua.VariantType.String,
    "DateTime": ua.VariantType.DateTime, "ByteString": ua.VariantType.ByteString,
}
SECURITY = {
    "None": ua.SecurityPolicyType.NoSecurity,
    "Basic256Sha256_Sign": ua.SecurityPolicyType.Basic256Sha256_Sign,
    "Basic256Sha256_SignAndEncrypt": ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
}


def jsonable(v):
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, bytes):
        return v.hex()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, ua.LocalizedText):
        return v.Text
    if isinstance(v, (ua.NodeId, ua.QualifiedName)):
        return v.to_string()
    if hasattr(v, "name") and hasattr(v, "value") and not isinstance(v, (int, float, str)):
        return v.name  # enums
    return v


class CredentialsUserManager:
    """Accepts exactly the configured username/password pairs; anonymous sessions pass through."""

    def __init__(self, users: dict):
        self.users = users

    def get_user(self, iserver, username=None, password=None, certificate=None):
        if username is None:
            return User(role=UserRole.User)
        if isinstance(password, bytes):
            password = password.decode("utf-8", "replace")
        return User(role=UserRole.User) if self.users.get(username) == password else None


# ------------------------------------------------------------------------------------------- server

async def serve(a):
    spec = json.loads(Path(a.spec).read_text())
    users = spec.get("users") or {}

    server = Server(user_manager=CredentialsUserManager(users) if users else None)
    await server.init()
    server.set_endpoint(f"opc.tcp://127.0.0.1:{a.port}{spec.get('path', '')}")
    server.set_server_name("sfc-e2e")
    policies = [SECURITY[s] for s in spec.get("security", ["None"])]
    server.set_security_policy(policies)
    tokens = [ua.AnonymousIdentityToken] if spec.get("anonymous", True) else []
    if users:
        tokens.append(ua.UserNameIdentityToken)
    server.set_identity_tokens(tokens)
    if any(p != ua.SecurityPolicyType.NoSecurity for p in policies):
        pki = Path(os.environ["SFC_E2E_PKI"])
        await server.load_certificate(str(pki / spec.get("certificate", "opcua-server.der")))
        await server.load_private_key(str(pki / spec.get("privateKey", "opcua-server.key")))

    idx = await server.register_namespace(spec.get("namespace", "urn:sfc:e2e"))
    folder = await server.nodes.objects.add_folder(ua.NodeId("E2E", idx), "E2E")
    instance = f"{os.getpid()}-{time.time_ns()}"
    counters, by_id = [], {}
    for n in spec.get("nodes", []):
        vtype = TYPES[n.get("type", "Double")]
        value = n.get("value", 0)
        if value == "$instance":
            value = instance
        node = await folder.add_variable(ua.NodeId(n["id"], idx), n.get("name", n["id"]), ua.Variant(value, vtype))
        if n.get("writable"):
            await node.set_writable()
        by_id[node.nodeid] = (n["id"], vtype)
        if n.get("step") is not None:
            counters.append((node, vtype, n["step"], n.get("periodMs", 500) / 1000.0, value))

    writes = open(a.writes, "a", buffering=1)
    requests = 0

    async def on_write(event, _dispatcher):
        nonlocal requests
        if not event.is_external:
            return  # the server's own updates (counters, server status), not a client write
        requests += 1
        nodes_to_write = event.request_params.NodesToWrite
        for wv, status in zip(nodes_to_write, event.response_params or []):
            name, _ = by_id.get(wv.NodeId, (wv.NodeId.to_string(), None))
            variant = wv.Value.Value
            source_ts = wv.Value.SourceTimestamp
            writes.write(json.dumps({"node": name, "value": jsonable(variant.Value),
                                     "type": variant.VariantType.name, "status": status.name,
                                     "request": requests, "batch": len(nodes_to_write),
                                     "sourceTimestamp": source_ts.isoformat() if source_ts else None,
                                     "t": time.time()}) + "\n")

    server.subscribe_server_callback(CallbackType.PostWrite, on_write)

    async def count(node, vtype, step, period, start):
        value = start
        while True:
            await asyncio.sleep(period)
            value += step
            await node.write_value(ua.Variant(value, vtype))

    async def emit_events(ev):
        gen = await server.get_event_generator()
        gen.event.Severity = ev.get("severity", 500)
        fmt = ev.get("messageFormat")
        n = 0
        while True:
            await asyncio.sleep(ev.get("periodMs", 500) / 1000.0)
            n += 1
            message = fmt.format(n=n) if fmt else f"{ev.get('message', 'e2e event')} {n}"
            await gen.trigger(message=message)

    async with server:
        print(f"namespace-index {idx}", flush=True)
        print(f"instance {instance}", flush=True)
        print("opcua server ready", flush=True)
        tasks = [asyncio.create_task(count(*c)) for c in counters]
        if spec.get("events"):
            tasks.append(asyncio.create_task(emit_events(spec["events"])))
        while True:
            await asyncio.sleep(3600)


# -------------------------------------------------------------------------------------------- probe

async def resolve(client, node_id: str) -> ua.NodeId:
    if node_id.startswith("nsu="):
        uri, rest = node_id[4:].split(";", 1)
        node_id = f"ns={await client.get_namespace_index(uri)};{rest}"
    return ua.NodeId.from_string(node_id)


async def read_op(client, op):
    node = client.get_node(await resolve(client, op["node"]))
    out = {"node": op["node"]}
    try:
        dv = await node.read_attribute(ua.AttributeIds.Value)
        out.update(status="Good", value=jsonable(dv.Value.Value), variantType=dv.Value.VariantType.name,
                   sourceTimestamp=dv.SourceTimestamp.isoformat() if dv.SourceTimestamp else None)
    except ua.UaStatusCodeError as e:
        out.update(status=type(e).__name__)
    for attr, key in ((ua.AttributeIds.NodeClass, "nodeClass"), (ua.AttributeIds.DataType, "dataType"),
                      (ua.AttributeIds.AccessLevel, "accessLevel"), (ua.AttributeIds.BrowseName, "browseName"),
                      (ua.AttributeIds.DisplayName, "displayName")):
        try:
            v = (await node.read_attribute(attr)).Value.Value
        except ua.UaStatusCodeError:
            continue
        if key == "dataType":
            try:
                v = (await client.get_node(v).read_browse_name()).Name
            except Exception:  # noqa: BLE001 - keep the raw id
                v = v.to_string()
        elif key == "accessLevel":
            v = sorted(b.name for b in ua.AccessLevel if v & (1 << b.value))
        out[key] = jsonable(v)
    return out


async def write_op(client, op):
    node = client.get_node(await resolve(client, op["node"]))
    try:
        await node.write_value(ua.DataValue(ua.Variant(op["value"], TYPES[op.get("type", "Int32")])))
        return {"node": op["node"], "status": "Good"}
    except ua.UaStatusCodeError as e:
        return {"node": op["node"], "status": type(e).__name__}


async def browse_op(client, op):
    try:
        node = await client.nodes.root.get_child(op["path"])
        return {"path": op["path"], "found": True, "nodeId": node.nodeid.to_string(),
                "nodeClass": (await node.read_node_class()).name}
    except ua.UaStatusCodeError as e:
        return {"path": op["path"], "found": False, "status": type(e).__name__}


async def children_op(client, op):
    node = client.get_node(await resolve(client, op["node"]))
    out = []
    for child in await node.get_children():
        out.append({"browseName": (await child.read_browse_name()).Name, "nodeId": child.nodeid.to_string(),
                    "nodeClass": (await child.read_node_class()).name})
    return {"node": op["node"], "children": sorted(out, key=lambda c: c["browseName"])}


async def endpoints_op(url):
    client = Client(url, timeout=5)
    eps = await client.connect_and_get_server_endpoints()
    return {"endpoints": [{"url": e.EndpointUrl, "securityPolicy": (e.SecurityPolicyUri or "").split("#")[-1],
                           "securityMode": e.SecurityMode.name,
                           "userTokens": sorted({t.TokenType.name for t in e.UserIdentityTokens}),
                           "hasCertificate": bool(e.ServerCertificate)} for e in eps]}


async def subscribe_op(client, op, emit):
    node = client.get_node(await resolve(client, op["node"]))
    done = asyncio.Event()
    seen = 0

    class Handler:
        def datachange_notification(self, _node, val, data):
            nonlocal seen
            dv = data.monitored_item.Value
            emit({"op": "notification", "name": op.get("name"), "value": jsonable(val),
                  "sourceTimestamp": dv.SourceTimestamp.isoformat() if dv.SourceTimestamp else None})
            seen += 1
            if seen >= op.get("count", 10):
                done.set()

    sub = await client.create_subscription(op.get("publishingMs", 100), Handler())
    await sub.subscribe_data_change(node, sampling_interval=op.get("samplingMs", op.get("publishingMs", 100)),
                                    queuesize=op.get("queueSize", 100))
    try:
        await asyncio.wait_for(done.wait(), op.get("timeoutSeconds", 20))
    except asyncio.TimeoutError:
        emit({"op": "subscribe", "name": op.get("name"), "status": "timeout", "notifications": seen})
    await sub.delete()


async def probe(a):
    spec = json.loads(Path(a.probe).read_text())
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = open(out_path, "a", buffering=1)

    def emit(rec):
        out.write(json.dumps(rec, default=str) + "\n")

    deadline = time.monotonic() + float(spec.get("timeoutSeconds", 20))
    client = None
    while time.monotonic() < deadline:
        client = Client(a.url, timeout=5)
        try:
            await client.connect()
            pending = list(spec.get("waitFor", []))
            while pending and time.monotonic() < deadline:
                try:
                    node = client.get_node(await resolve(client, pending[0]))
                    await node.read_attribute(ua.AttributeIds.Value)
                    pending.pop(0)
                except ua.UaStatusCodeError:
                    await asyncio.sleep(0.2)
            if pending:
                emit({"op": "waitFor", "status": "timeout", "pending": pending})
            break
        except (OSError, asyncio.TimeoutError, ua.UaError):
            client = None
            await asyncio.sleep(0.3)
    if client is None:
        emit({"op": "connect", "status": "timeout", "url": a.url})
        return

    try:
        for op in spec.get("ops", []):
            kind = op["op"]
            try:
                if kind == "subscribe":
                    await subscribe_op(client, op, emit)
                    continue
                result = {"read": read_op, "write": write_op, "browse": browse_op,
                          "children": children_op}.get(kind)
                rec = await result(client, op) if result else await endpoints_op(a.url) if kind == "endpoints" \
                    else {"status": f"unknown op {kind}"}
            except Exception as e:  # noqa: BLE001 - recorded, the case asserts on it
                rec = {"status": "error", "error": f"{type(e).__name__}: {e}"}
            emit({"op": kind, "name": op.get("name"), **rec})
    finally:
        await client.disconnect()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--spec")
    ap.add_argument("--writes")
    ap.add_argument("--probe", help="run as a probe client with this spec instead of serving")
    ap.add_argument("--url")
    ap.add_argument("--out")
    a = ap.parse_args()
    asyncio.run(probe(a) if a.probe else serve(a))


main()
