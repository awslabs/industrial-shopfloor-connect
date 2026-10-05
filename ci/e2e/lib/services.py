# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Counterparts: the processes a case needs besides SFC itself.

A case lists them in ``case.json``::

    "services": [
      {"name": "broker", "kind": "mosquitto"},
      {"name": "gate",   "kind": "tcpgate", "args": {"to": "broker"}},
      {"name": "late",   "kind": "nats", "start": "deferred"}
    ]

Every service gets runner-allocated ports, exported to SFC and to the case as ``SFC_E2E_<NAME>_PORT``
(``SFC_E2E_BROKER_PORT`` above), so two cases - or two builds - never contend for a fixed port. Services
start before SFC unless ``"start": "deferred"``, in which case a timeline step starts them; their ports
are reserved from the beginning so the SFC configuration can already point at them.

Nothing here needs Docker. In CodeBuild the binaries come from apt (mosquitto, snmpd, postgresql), a
pinned static download (nats-server) or pip (asyncua, pymodbus); the rest are the stdlib scripts in
``ci/e2e/counterparts``. On a laptop a missing binary makes the case SKIP with the reason - in CI it is an
error, because a silently skipped case reads as coverage that does not exist.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import sfcproc
from .counterpart_paths import COUNTERPARTS


class ServiceError(RuntimeError):
    pass


def _var(name: str) -> str:
    return "SFC_E2E_" + name.upper().replace("-", "_")


class Service:
    kind = "abstract"
    #: Executables that must be on PATH.
    binaries: tuple[str, ...] = ()
    #: Python modules that must be importable.
    python_modules: tuple[str, ...] = ()
    #: Names of the ports this service needs; "port" is the main one.
    port_names: tuple[str, ...] = ("port",)

    def __init__(self, spec: dict, workdir: Path, env: dict):
        self.name = spec["name"]
        self.spec = spec
        self.args = spec.get("args") or {}
        self.deferred = spec.get("start", "before") == "deferred"
        self.workdir = workdir / "services" / self.name
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.env_in = env
        self.ports = {p: sfcproc.free_port("127.0.0.1") for p in self.port_names}
        self.proc: subprocess.Popen | None = None
        self._log_out = self.workdir / "out.log"
        self._log_err = self.workdir / "err.log"

    # -- contract ------------------------------------------------------------------------------------
    @property
    def port(self) -> int:
        return self.ports["port"]

    def exports(self) -> dict[str, str]:
        out = {}
        for pname, value in self.ports.items():
            suffix = "PORT" if pname == "port" else f"{pname.upper()}_PORT"
            out[f"{_var(self.name)}_{suffix}"] = str(value)
        return out

    def command(self, env: dict) -> list[str]:
        raise NotImplementedError

    def ready(self, timeout: float) -> None:
        sfcproc.wait_for_port(self.port, timeout, hosts=("127.0.0.1",), proc=None)

    # -- lifecycle -----------------------------------------------------------------------------------
    def start(self, env: dict, timeout: float = 30.0) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        argv = self.command(env)
        out = self._log_out.open("ab")
        err = self._log_err.open("ab")
        self.proc = subprocess.Popen(argv, cwd=str(self.workdir), env={**os.environ, **env},
                                     stdout=out, stderr=err, start_new_session=True)
        try:
            self.ready(timeout)
        except Exception as e:
            raise ServiceError(f"service {self.name!r} ({self.kind}) did not become ready: {e}\n"
                               f"--- stderr ---\n{self.tail(self._log_err)}") from None
        if self.proc.poll() is not None:
            raise ServiceError(f"service {self.name!r} exited with {self.proc.returncode}\n{self.tail(self._log_err)}")

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            self.proc.wait(timeout=10)

    def signal(self, sig: int) -> None:
        if self.proc is not None and self.proc.poll() is None:
            os.killpg(os.getpgid(self.proc.pid), sig)

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @staticmethod
    def tail(path: Path, lines: int = 30) -> str:
        if not path.is_file():
            return ""
        return "".join(path.read_text(errors="replace").splitlines(keepends=True)[-lines:])

    def describe(self) -> dict:
        return {"name": self.name, "kind": self.kind, "ports": self.ports}


def _py(script: str) -> list[str]:
    return [sys.executable, str(COUNTERPARTS / script)]


class CommandService(Service):
    """Any command; ``args.argv`` may reference ``${SFC_E2E_...}`` and ``${COUNTERPARTS}``, and
    ``python`` is the harness interpreter. Readiness: ``args.readyLog`` (text on stdout), else the
    service's port when ``args.listens`` is true, else just "still running after a moment"."""

    kind = "command"

    def command(self, env):
        argv = self.args.get("argv")
        if not argv:
            raise ServiceError(f"service {self.name!r}: command needs args.argv")
        return [_expand(a, env) for a in argv]

    def ready(self, timeout):
        if self.args.get("readyLog"):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.args["readyLog"] in self.tail(self._log_out, 500):
                    return
                if self.proc.poll() is not None:
                    raise ServiceError(f"exited with {self.proc.returncode}")
                time.sleep(0.1)
            raise ServiceError(f"{self.args['readyLog']!r} not seen")
        if self.args.get("listens"):
            return super().ready(timeout)
        time.sleep(0.5)
        if self.proc.poll() is not None and self.proc.returncode != 0:
            raise ServiceError(f"exited with {self.proc.returncode}")


def _expand(value: str, env: dict) -> str:
    out = value.replace("${COUNTERPARTS}", str(COUNTERPARTS))
    out = sys.executable if out == "python" else out
    for k, v in env.items():
        out = out.replace("${" + k + "}", str(v))
    return out


class TcpGateService(Service):
    """A TCP forwarder that can be closed and reopened mid-case - deterministic outages.

    SIGUSR1 closes the gate (drops live connections and refuses new ones), SIGUSR2 reopens it.
    ``args.to`` names another service whose main port is the destination, or ``args.toPort``;
    ``args.closed`` starts it closed.
    """

    kind = "tcpgate"

    def command(self, env):
        to = self.args.get("toPort")
        if to is None:
            to = env.get(f"{_var(self.args['to'])}_PORT")
        if to is None:
            raise ServiceError(f"tcpgate {self.name!r}: unknown destination")
        argv = _py("tcpgate.py") + ["--listen", f"127.0.0.1:{self.port}", "--to", f"127.0.0.1:{_expand(str(to), env)}"]
        return argv + (["--closed"] if self.args.get("closed") else [])

    def close(self):
        self.signal(signal.SIGUSR1)

    def open(self):
        self.signal(signal.SIGUSR2)


class SilentService(Service):
    """Accepts TCP connections and never answers - a peer that hangs rather than refuses."""

    kind = "silent"

    def command(self, env):
        return _py("silent.py") + ["--port", str(self.port)]


class MosquittoService(Service):
    """mosquitto on a generated config. ``args.tls``: ``"server"`` adds a TLS listener (port
    ``SFC_E2E_<NAME>_TLS_PORT``) with the run PKI's server certificate, ``"mutual"`` also requires a
    client certificate signed by the run CA."""

    kind = "mosquitto"
    binaries = ("mosquitto",)

    def __init__(self, spec, workdir, env):
        if (spec.get("args") or {}).get("tls"):
            self.port_names = ("port", "tls")
        super().__init__(spec, workdir, env)

    def command(self, env):
        conf = self.workdir / "mosquitto.conf"
        lines = ["per_listener_settings true", f"listener {self.port} 127.0.0.1", "allow_anonymous true"]
        tls = self.args.get("tls")
        if tls:
            pki = env.get("SFC_E2E_PKI")
            if not pki:
                raise ServiceError("mosquitto TLS needs the run PKI (openssl was not available)")
            lines += [f"listener {self.ports['tls']} 127.0.0.1", "allow_anonymous true",
                      f"cafile {pki}/ca.crt", f"certfile {pki}/server.crt", f"keyfile {pki}/server.key"]
            if tls == "mutual":
                lines += ["require_certificate true", "use_identity_as_username true"]
        conf.write_text("\n".join(lines) + "\n")
        return ["mosquitto", "-c", str(conf)]


class NatsService(Service):
    kind = "nats"
    binaries = ("nats-server",)

    def command(self, env):
        argv = ["nats-server", "-a", "127.0.0.1", "-p", str(self.port)]
        argv += [_expand(a, env) for a in self.args.get("extra", [])]
        return argv


class HttpFakeService(Service):
    """A scripted HTTP server for the REST adapter (stdlib only)."""

    kind = "http"

    def command(self, env):
        scenario = self.args.get("scenario", "scenario.json")
        return _py("http_fake.py") + ["--port", str(self.port), "--scenario",
                                      str(Path(env["SFC_E2E_CASE_DIR"]) / scenario)]


class OpcuaServerService(Service):
    """A python asyncua server with writable nodes - the counterpart for opcua-writer-target and for the
    adapter cases that need something SFC's own (read-only) OPC-UA server cannot provide."""

    kind = "opcua-server"
    python_modules = ("asyncua",)

    def command(self, env):
        spec = self.args.get("spec", "opcua_server.json")
        return _py("opcua_server.py") + ["--port", str(self.port), "--spec",
                                         str(Path(env["SFC_E2E_CASE_DIR"]) / spec),
                                         "--writes", str(self.workdir / "writes.jsonl")]


class ModbusService(Service):
    kind = "modbus"
    python_modules = ("pymodbus",)

    def command(self, env):
        spec = self.args.get("spec", "modbus.json")
        return _py("modbus_server.py") + ["--port", str(self.port), "--spec",
                                          str(Path(env["SFC_E2E_CASE_DIR"]) / spec)]


class SnmpdService(Service):
    kind = "snmpd"
    binaries = ("snmpd",)

    def command(self, env):
        conf = self.workdir / "snmpd.conf"
        src = self.args.get("conf")
        text = (Path(env["SFC_E2E_CASE_DIR"]) / src).read_text() if src else "rocommunity public 127.0.0.1\n"
        conf.write_text(text)
        return ["snmpd", "-f", "-Lo", "-C", "-c", str(conf), f"udp:127.0.0.1:{self.port}"]

    def ready(self, timeout):
        # UDP has no connect-level readiness; snmpd prints its banner once it is serving.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if "NET-SNMP version" in self.tail(self._log_out, 200) + self.tail(self._log_err, 200):
                return
            time.sleep(0.2)
        raise ServiceError("snmpd banner not seen")


class SfcProcessService(Service):
    """A second SFC process, e.g. an OPC-UA server built from opcua-target for an adapter round trip.

    Always launched from the uberjar: it is a counterpart, not the code under test, so its mode is fixed.
    ``args.config`` is a config file in the case directory; ``args.readyPort`` names the port to probe.
    """

    kind = "sfc"

    def command(self, env):
        jar = env.get("SFC_E2E_UBERJAR")
        if not jar:
            raise ServiceError("sfc counterpart needs the uberjar (SFC_E2E_UBERJAR)")
        config = Path(env["SFC_E2E_CASE_DIR"]) / self.args["config"]
        rendered = self.workdir / "config.json"
        rendered.write_text(_expand(config.read_text(), {**env, **self.exports()}))
        from .modes import JVM_BOUNDS, java  # local import: modes imports sfcproc, not services

        return [java(), *JVM_BOUNDS, "-cp", jar, "com.amazonaws.sfc.MainController",
                "-config", str(rendered), "-info"]


class _Shared:
    """Run-scoped singletons: services too expensive to start per case (PostgreSQL)."""

    lock = threading.Lock()
    instances: dict[str, "Service"] = {}


class PostgresService(Service):
    """One PostgreSQL cluster per run, shared by every SQL case; each case run gets its own database.

    The cluster is the distro one (``pg_ctlcluster <version> main``), started on first use and left
    running. A role ``sfc_e2e``/``sfc_e2e`` is created once; the case database is named after the marker
    and loaded from ``args.sql`` (a file in the case directory). Exports ``SFC_E2E_<NAME>_PORT`` (5432)
    and ``SFC_E2E_<NAME>_DB``.
    """

    kind = "postgres"
    binaries = ("pg_ctlcluster", "psql")

    def __init__(self, spec, workdir, env):
        super().__init__(spec, workdir, env)
        self.ports["port"] = 5432
        self.database = "e2e_" + env["SFC_E2E_MARKER"]

    def exports(self):
        return {**super().exports(), f"{_var(self.name)}_DB": self.database}

    @staticmethod
    def _psql(sql: str, db: str = "postgres") -> None:
        proc = subprocess.run(["runuser", "-u", "postgres", "--", "psql", "-v", "ON_ERROR_STOP=1", "-q",
                               "-d", db, "-c", sql], capture_output=True, text=True)
        if proc.returncode != 0:
            raise ServiceError(f"psql failed: {proc.stderr.strip()}")

    def start(self, env, timeout=60.0):
        with _Shared.lock:
            if "postgres" not in _Shared.instances:
                versions = sorted(p.name for p in Path("/etc/postgresql").iterdir()) if Path("/etc/postgresql").is_dir() else []
                if not versions:
                    raise ServiceError("no PostgreSQL cluster under /etc/postgresql")
                proc = subprocess.run(["pg_ctlcluster", versions[-1], "main", "start"], capture_output=True, text=True)
                if proc.returncode not in (0, 2):  # 2 = already running
                    raise ServiceError(f"pg_ctlcluster failed: {proc.stderr}")
                sfcproc.wait_for_port(5432, timeout, hosts=("127.0.0.1",), proc=None)
                self._psql("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sfc_e2e') THEN "
                           "CREATE ROLE sfc_e2e LOGIN PASSWORD 'sfc_e2e'; END IF; END $$;")
                _Shared.instances["postgres"] = self
        self._psql(f'DROP DATABASE IF EXISTS "{self.database}"')
        self._psql(f'CREATE DATABASE "{self.database}" OWNER sfc_e2e')
        script = self.args.get("sql")
        if script:
            sql = (Path(env["SFC_E2E_CASE_DIR"]) / script).read_text()
            proc = subprocess.run(["psql", "-v", "ON_ERROR_STOP=1", "-q", "-h", "127.0.0.1", "-U", "sfc_e2e",
                                   "-d", self.database, "-c", sql], capture_output=True, text=True,
                                  env={**os.environ, "PGPASSWORD": "sfc_e2e"})
            if proc.returncode != 0:
                raise ServiceError(f"loading {script} failed: {proc.stderr.strip()}")

    def stop(self):
        try:
            self._psql(f'DROP DATABASE IF EXISTS "{self.database}" WITH (FORCE)')
        except ServiceError:
            pass  # the cluster stays up for the run; a leftover database dies with the container

    def running(self):
        return True

    def command(self, env):
        return []


class AwsWireStubService(Service):
    """A stdlib AWS protocol stub with fault injection, for the error paths real AWS cannot produce on
    demand (throttling, 5xx bursts). Happy paths always use the real stack."""

    kind = "aws-wire-stub"

    def command(self, env):
        spec = self.args.get("spec", "stub.json")
        return _py("aws_wire_stub.py") + ["--port", str(self.port), "--spec",
                                          str(Path(env["SFC_E2E_CASE_DIR"]) / spec),
                                          "--capture", str(self.workdir / "capture.jsonl")]


KINDS: dict[str, type[Service]] = {cls.kind: cls for cls in (
    CommandService, TcpGateService, SilentService, MosquittoService, NatsService, HttpFakeService,
    OpcuaServerService, ModbusService, SnmpdService, SfcProcessService, PostgresService, AwsWireStubService,
)}


def missing(kind: str) -> list[str]:
    cls = KINDS.get(kind)
    if cls is None:
        return [f"unknown service kind {kind!r}"]
    out = [b for b in cls.binaries if shutil.which(b) is None]
    out += [f"python:{m}" for m in cls.python_modules if importlib.util.find_spec(m) is None]
    return out


def build(specs: list[dict], workdir: Path, env: dict) -> dict[str, Service]:
    services: dict[str, Service] = {}
    for spec in specs or []:
        cls = KINDS.get(spec.get("kind", ""))
        if cls is None:
            raise ServiceError(f"unknown service kind {spec.get('kind')!r}; known: {sorted(KINDS)}")
        if spec["name"] in services:
            raise ServiceError(f"duplicate service name {spec['name']!r}")
        services[spec["name"]] = cls(spec, workdir, env)
    return services


def udp_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False
