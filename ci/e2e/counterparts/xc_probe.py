#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Probes for the cross-cutting runtime cases (IPC transport, health probes, metrics, IPC service CLI).

Run from a case's ``steps`` as ``{"do": "run", "argv": ["python", "${COUNTERPARTS}/xc_probe.py", <probe>, ...]}``.

Every probe writes ONE JSON object to ``--out`` and exits 0 whatever it observed, so the case's own
assertions decide - point ``--out`` into a file sink directory (``${SFC_E2E_SINK_PROBE}/<name>.json``) and
assert with ``everyRecord``/``deepEquals`` and ``"where": {"probe": "<name>"}``. A non-zero exit means the
probe was misused (bad arguments), never that SFC misbehaved.

    ipc      What an IPC server port speaks on the wire: cleartext HTTP/2 (h2c) and/or TLS, with or without
             a client certificate. The address and port are read from the rendered config.json, i.e. the
             values sfc-main itself was given.
    http     HTTP requests against a health probe, after finding its address in a process log line
             "Started health probe service, listening on <ip>:<port>/<path>".
    metrics  A digest of the E2eMetricsWriter JSONL: sources, names, units and dimensions per series.
    svc      Runs an IPC service launcher with given arguments and reports whether it listened or exited,
             with its exit code and output.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import random
import re
import signal
import socket
import ssl
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

H2_PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"
H2_EMPTY_SETTINGS = b"\x00\x00\x00\x04\x00\x00\x00\x00\x00"
H2_FRAME_SETTINGS = 0x04


def write_out(path: str, obj: dict) -> None:
    """Atomically, and via a temporary file OUTSIDE the sink directory, so a sink never counts a half
    written or temporary file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.parent.parent / f".{p.parent.name}-{p.name}.tmp"
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True))
    os.replace(tmp, p)


def local_ipv4_addresses() -> list[str]:
    out: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 1))
            out.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if info[4][0] not in out:
                out.append(info[4][0])
    except OSError:
        pass
    if "127.0.0.1" not in out:
        out.append("127.0.0.1")
    return out


def _resolve(value) -> str:
    """Resolve ${VAR} placeholders the way SFC does: the case configs name the IPC host and ports as
    ${SFC_E2E_IPC_HOST} / ${SFC_E2E_IPC_<SERVER>_PORT}, and a run step inherits the run's environment."""
    return re.sub(r"\$\{([A-Za-z0-9_]+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), str(value))


def server_from_config(config: str, section: str, key: str) -> tuple[str, int]:
    entry = json.loads(Path(config).read_text())[section][key]
    return _resolve(entry["Address"]), int(_resolve(entry["Port"]))


def read_frame_header(sock, timeout: float) -> bytes:
    sock.settimeout(timeout)
    data = b""
    deadline = time.monotonic() + timeout
    while len(data) < 9 and time.monotonic() < deadline:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


# ------------------------------------------------------------------------------------------------ ipc

def probe_h2c(addr: str, port: int, timeout: float) -> dict:
    """Send the HTTP/2 client preface in cleartext. A PlainText gRPC server answers with a SETTINGS frame;
    a TLS server cannot (it sees a malformed TLS record and closes)."""
    try:
        with socket.create_connection((addr, port), timeout=timeout) as s:
            s.sendall(H2_PREFACE + H2_EMPTY_SETTINGS)
            data = read_frame_header(s, timeout)
    except (socket.timeout, TimeoutError):
        return {"h2c": "timeout", "plaintextH2": False}
    except OSError as e:
        return {"h2c": f"error:{type(e).__name__}", "plaintextH2": False}
    if len(data) >= 9 and data[3] == H2_FRAME_SETTINGS:
        result = "settings"
    elif not data:
        result = "closed"
    elif data[0] in (0x15, 0x16):
        result = "tls-record"
    else:
        result = "other"
    return {"h2c": result, "plaintextH2": result == "settings", "h2cFirstBytes": data[:12].hex()}


def probe_tls(addr: str, port: int, ca: str | None, cert: str | None, key: str | None, timeout: float) -> dict:
    """A TLS handshake (ALPN h2), then the HTTP/2 preface over it. ``accepted`` means the server answered
    the preface with a SETTINGS frame, i.e. it serves this client. With TLS 1.3 a server that requires a
    client certificate rejects after the client's Finished, so the read - not the handshake - is what
    tells a client-authenticating server apart."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if ca:
        ctx.load_verify_locations(ca)
        ctx.check_hostname = True
    else:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if cert:
        ctx.load_cert_chain(cert, key)
    ctx.set_alpn_protocols(["h2"])
    out: dict = {"tlsClientCert": bool(cert), "tlsVerified": bool(ca)}
    try:
        raw = socket.create_connection((addr, port), timeout=timeout)
    except OSError as e:
        return {**out, "handshake": f"connect-error:{type(e).__name__}", "accepted": False}
    try:
        s = ctx.wrap_socket(raw, server_hostname=addr)
    except ssl.SSLCertVerificationError as e:
        raw.close()
        return {**out, "handshake": "untrusted", "reason": str(e.verify_message), "accepted": False}
    except ssl.SSLError as e:
        raw.close()
        return {**out, "handshake": "failed", "reason": str(e.reason or e), "accepted": False}
    except (OSError, socket.timeout) as e:
        raw.close()
        return {**out, "handshake": f"failed:{type(e).__name__}", "accepted": False}
    with s:
        out["handshake"] = "ok"
        out["tlsVersion"] = s.version()
        out["alpn"] = s.selected_alpn_protocol()
        peer = s.getpeercert() or {}
        cn = [v for rdn in peer.get("subject", ()) for (k, v) in rdn if k == "commonName"]
        if cn:
            out["peerCN"] = cn[0]
        try:
            s.sendall(H2_PREFACE + H2_EMPTY_SETTINGS)
            data = read_frame_header(s, timeout)
            out["h2"] = "settings" if len(data) >= 9 and data[3] == H2_FRAME_SETTINGS else ("closed" if not data else "other")
        except ssl.SSLError as e:
            out["h2"] = "ssl-error"
            out["h2Reason"] = str(e.reason or e)
        except (OSError, socket.timeout) as e:
            out["h2"] = f"error:{type(e).__name__}"
    out["accepted"] = out.get("h2") == "settings"
    return out


def cmd_ipc(a) -> dict:
    addr, port = server_from_config(a.config, a.section, a.server)
    out: dict = {"server": a.server, "address": addr, "port": port}
    if "h2c" in a.mode:
        out.update(probe_h2c(addr, port, a.timeout))
    if "tls" in a.mode:
        out.update(probe_tls(addr, port, a.ca, a.cert, a.key, a.timeout))
    return out


# ----------------------------------------------------------------------------------------------- http

HP_LINE = re.compile(r"Started health probe service, listening on ([0-9.]+):(\d+)(/\S*)")


def find_health_probe(logs: list[str], timeout: float) -> tuple[str, int, str] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for path in logs:
            try:
                text = Path(path).read_text(errors="replace")
            except OSError:
                continue
            m = HP_LINE.search(text)
            if m:
                return m.group(1), int(m.group(2)), m.group(3)
        time.sleep(0.2)
    return None


def one_request(addr, port, method, path, bind, timeout) -> dict:
    conn = http.client.HTTPConnection(addr, port, timeout=timeout, source_address=(bind, 0) if bind else None)
    try:
        conn.request(method, path)
        r = conn.getresponse()
        body = r.read().decode("utf-8", errors="replace")
        return {"method": method, "path": path, "status": r.status, "body": body,
                "contentType": r.getheader("Content-Type"), "cacheControl": r.getheader("Cache-Control")}
    except http.client.RemoteDisconnected:
        return {"method": method, "path": path, "status": "disconnected"}
    except OSError as e:
        return {"method": method, "path": path, "status": f"error:{type(e).__name__}"}
    finally:
        conn.close()


def cmd_http(a) -> dict:
    found = find_health_probe(a.log, a.timeout)
    if found is None:
        return {"found": False}
    addr, port, base = found
    out: dict = {"found": True, "address": addr, "port": port, "logPath": base, "bind": a.bind}
    results = []
    for spec in a.req:
        method, _, path = spec.partition(":")
        results.append(one_request(addr, port, method, path or base, a.bind, a.timeout))
    if a.repeat:
        statuses = []
        for i in range(a.repeat):
            if i and a.spacing_ms:
                time.sleep(a.spacing_ms / 1000.0)
            statuses.append(one_request(addr, port, "GET", base, a.bind, a.timeout)["status"])
        out["repeatStatuses"] = statuses
        out["repeat200"] = sum(1 for s in statuses if s == 200)
    out["requests"] = results
    out["statuses"] = [r["status"] for r in results]
    return out


# -------------------------------------------------------------------------------------------- metrics

def cmd_metrics(a) -> dict:
    path = Path(a.file)
    points = []
    if path.is_file():
        for line in path.read_text().splitlines():
            try:
                points.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    names: dict = defaultdict(set)
    units: dict = defaultdict(dict)
    dims: dict = defaultdict(lambda: defaultdict(set))
    totals: dict = defaultdict(lambda: defaultdict(float))
    for p in points:
        s, n = p.get("source", ""), p.get("name", "")
        names[s].add(n)
        units[s][n] = p.get("units")
        dims[s][n].add(json.dumps(p.get("dimensions") or {}, sort_keys=True))
        if p.get("valueType") == "single":
            totals[s][n] += float(p.get("value", 0.0))
    dim_out = {}
    for s, per_name in dims.items():
        dim_out[s] = {}
        for n, variants in per_name.items():
            decoded = [json.loads(v) for v in sorted(variants)]
            dim_out[s][n] = decoded[0] if len(decoded) == 1 else decoded
    dim_keys = {s: sorted({k for variants in per_name.values() for v in variants for k in json.loads(v)})
                for s, per_name in dims.items()}
    return {"points": len(points), "sources": sorted(names), "names": {s: sorted(v) for s, v in names.items()},
            "units": {s: dict(sorted(v.items())) for s, v in units.items()}, "dims": dim_out, "dimKeys": dim_keys,
            "totals": {s: dict(v) for s, v in totals.items()}}


# ------------------------------------------------------------------------------------------------ svc

def free_port() -> int:
    """A port for the probed service, picked like the harness's sfcproc.free_port.

    bind(127.0.0.1:0) handed out a port from the ephemeral range that an outgoing connection on the
    container address already held ("Failed to bind to address /172.17.0.2:44431"). 10000-19999 lies
    below the Linux (32768-60999) and macOS (49152-65535) ephemeral ranges and outside the harness's own
    20000-32767; binding 0.0.0.0 checks every local address the service may bind.
    """
    for _ in range(500):
        port = random.randint(10000, 19999)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
            except OSError:
                continue
        return port
    raise SystemExit("svc: no free port in 10000-19999 after 500 attempts")


def listening(port: int) -> str | None:
    for host in local_ipv4_addresses():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((host, port)) == 0:
                return host
    return None


def cmd_svc(a) -> dict:
    uberjar = os.environ.get("SFC_E2E_UBERJAR")
    if not uberjar:
        raise SystemExit("svc: SFC_E2E_UBERJAR is not set")
    # <out>/artifacts/sfc-uberjar/lib/sfc-uberjar-<v>.jar -> <out>/artifacts/<module>/bin/<module>
    launcher = Path(uberjar).parents[2] / a.module / "bin" / a.module
    if not launcher.is_file():
        raise SystemExit(f"svc: no launcher at {launcher} (the module is unpacked in inprocess/ipc mode only)")
    port = free_port()
    work = Path(a.workdir)
    work.mkdir(parents=True, exist_ok=True)
    if a.template:
        text = Path(a.template).read_text().replace("__PORT__", str(port)).replace("__WORK__", str(work))
        (work / Path(a.template).name).write_text(text)
    args = [x.replace("__PORT__", str(port)).replace("__WORK__", str(work)) for x in a.args]
    env = {**os.environ, "JAVA_OPTS": "-Xmx256m -XX:+ExitOnOutOfMemoryError", "TZ": "UTC", "LC_ALL": "C"}
    for kv in a.env:
        k, _, v = kv.partition("=")
        env[k] = v.replace("__PORT__", str(port))
    log = work / f"{a.name}.log"
    with open(log, "wb") as fh:
        proc = subprocess.Popen([str(launcher), *args], cwd=str(work), env=env, stdout=fh, stderr=subprocess.STDOUT,
                                start_new_session=True)
        outcome, host = "timeout", None
        deadline = time.monotonic() + a.timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                outcome = "exited"
                break
            host = listening(port)
            if host:
                outcome = "listening"
                break
            time.sleep(0.2)
        wire = probe_h2c(host, port, 3.0) if (outcome == "listening" and a.h2c) else {}
        if proc.poll() is None:
            # Let a listening service log its start line, then stop it.
            time.sleep(a.settle)
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=15)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait(timeout=10)
    text = re.sub(r"\x1b\[[0-9;]*m", "", log.read_text(errors="replace"))
    return {"outcome": outcome, "exitCode": proc.returncode if outcome == "exited" else None, "port": port,
            "listenHost": host, "args": args, **wire, "output": " | ".join(l.strip() for l in text.splitlines() if l.strip())}


# ----------------------------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("ipc", "http", "metrics", "svc"):
        p = sub.add_parser(name)
        p.add_argument("--name", required=True, help="the probe name, recorded as 'probe' in the output")
        p.add_argument("--out", required=True)
        p.add_argument("--timeout", type=float, default=5.0)
        if name == "ipc":
            p.add_argument("--config", required=True)
            p.add_argument("--section", default="AdapterServers")
            p.add_argument("--server", required=True)
            p.add_argument("--mode", default="h2c,tls")
            p.add_argument("--ca")
            p.add_argument("--cert")
            p.add_argument("--key")
        elif name == "http":
            p.add_argument("--log", action="append", required=True)
            p.add_argument("--req", action="append", default=[], help="METHOD:/path, or METHOD: for the probe path")
            p.add_argument("--bind")
            p.add_argument("--repeat", type=int, default=0)
            p.add_argument("--spacing-ms", type=int, default=0)
        elif name == "metrics":
            p.add_argument("--file", required=True)
        else:
            p.add_argument("--module", required=True)
            p.add_argument("--workdir", required=True)
            p.add_argument("--template")
            p.add_argument("--env", action="append", default=[])
            p.add_argument("--settle", type=float, default=1.0)
            p.add_argument("--h2c", action="store_true", help="when it listens, probe the port for cleartext HTTP/2")
            p.add_argument("args", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    if a.cmd == "svc" and a.args and a.args[0] == "--":
        a.args = a.args[1:]
    result = {"ipc": cmd_ipc, "http": cmd_http, "metrics": cmd_metrics, "svc": cmd_svc}[a.cmd](a)
    write_out(a.out, {"probe": a.name, **result})


if __name__ == "__main__":
    main()
