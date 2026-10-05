# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Launching, waiting on and stopping SFC processes.

Two facts about SFC shape everything here.

**There is no shutdown hook in sfc-main.** ``Runtime.getRuntime().addShutdownHook`` appears only in
core/sfc-ipc (IpcAdapterService, IpcTargetServer, IpcMetricsServer). So in in-process and uberjar mode
a SIGTERM does *not* flush buffered target data: whatever a target is holding is lost. No case may
therefore assert "stop the process and the data appears". Cases force a flush through configuration
instead - ``"BufferCount": 1`` on the file target writes one file per record - and the runner waits for
those records to appear *before* stopping anything.

**A liveness log line is not a readiness signal.** MainControllerService.kt:309 logs "Creating in
process target writer for target ID ..." and line 310 *then* constructs the writer, so the line appears
even when construction throws. Readiness is therefore established by observing the thing that actually
matters - the first record arriving at the sink - never by such a line and never by sleeping. The one
log line that is a fact is an IPC service's "service started, listening on <address>:<port>": it is
written only after ``grpcServer.start()`` has bound and listens (IpcAdapterService.kt:88-91,
IpcTargetServer.kt:89-92).
"""

from __future__ import annotations

import os
import random
import re
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path


class ProcessError(RuntimeError):
    pass


class BindError(ProcessError):
    """An IPC service exited because its server could not bind its port."""


@dataclass
class Launch:
    """One process to run: what to execute, where, and how to know it is up."""

    name: str
    argv: list[str]
    cwd: Path
    env: dict[str, str]
    stdout_path: Path
    stderr_path: Path
    #: The fixed port of an IPC service (``-port``), which :data:`IPC_PORTS` keeps free for it.
    ready_port: int | None = None


class RunningProcess:
    def __init__(self, launch: Launch, popen: subprocess.Popen):
        self.launch = launch
        self.popen = popen
        self.stopped_at: float | None = None

    @property
    def name(self) -> str:
        return self.launch.name

    def poll(self) -> int | None:
        return self.popen.poll()

    def stop(self, term_grace: float = 10.0) -> int | None:
        """SIGTERM the process group, then SIGKILL if it does not go.

        The whole group is signalled because the generated ``bin/<module>`` launchers are shell scripts
        that exec a JVM; signalling only the script would orphan the JVM, which then keeps the port and
        breaks the next case.
        """
        if self.popen.poll() is not None:
            return self.popen.returncode

        pgid = None
        try:
            pgid = os.getpgid(self.popen.pid)
        except (ProcessLookupError, PermissionError):
            pass

        try:
            if pgid is not None:
                os.killpg(pgid, signal.SIGTERM)
            else:
                self.popen.terminate()
        except ProcessLookupError:
            return self.popen.returncode

        try:
            self.popen.wait(timeout=term_grace)
        except subprocess.TimeoutExpired:
            try:
                if pgid is not None:
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    self.popen.kill()
            except ProcessLookupError:
                pass
            try:
                self.popen.wait(timeout=10)
            except subprocess.TimeoutExpired:
                raise ProcessError(f"{self.name} survived SIGKILL") from None

        self.stopped_at = time.time()
        return self.popen.returncode

    def signal(self, sig: int) -> None:
        """Signal the whole process group (the launchers are shell scripts that exec a JVM)."""
        if self.popen.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.popen.pid), sig)
        except ProcessLookupError:
            pass

    def scan(self, patterns: list[str]) -> str | None:
        """The first new log line (either stream) containing one of ``patterns``, reading incrementally."""
        if not patterns:
            return None
        offsets = self.__dict__.setdefault("_scan_offsets", {})
        for path in (self.launch.stdout_path, self.launch.stderr_path):
            try:
                with open(path, "rb") as f:
                    f.seek(offsets.get(path, 0))
                    chunk = f.read()
            except FileNotFoundError:
                continue
            # Only consume complete lines, so a pattern split across two reads is still found.
            cut = chunk.rfind(b"\n") + 1
            offsets[path] = offsets.get(path, 0) + cut
            for line in chunk[:cut].decode("utf-8", errors="replace").splitlines():
                if any(p in line for p in patterns):
                    return line.strip()
        return None

    def read_stdout(self) -> str:
        return _read(self.launch.stdout_path)

    def read_stderr(self) -> str:
        return _read(self.launch.stderr_path)

    def tail_stderr(self, lines: int = 40) -> str:
        return _tail(self.launch.stderr_path, lines)

    def tail_stdout(self, lines: int = 40) -> str:
        return _tail(self.launch.stdout_path, lines)


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _tail(path: Path, lines: int) -> str:
    if not path.is_file():
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        return "".join(fh.readlines()[-lines:])


def primary_ipv4() -> str:
    """The address a default outbound connection would leave from.

    Found by opening an unconnected UDP socket towards a documentation address - no packet is sent, the
    kernel just performs the route lookup. This is the closest match to Java's
    ``InetAddress.getLocalHost()`` in practice.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 1))  # TEST-NET-1, never routed
            return str(s.getsockname()[0])
    except OSError:
        return "127.0.0.1"


def local_ipv4_addresses() -> tuple[str, ...]:
    """Every address an SFC IPC service might have bound, best candidate first.

    An SFC IPC service with no ``-interface`` binds ``getIp4NetworkAddress(null)``, which is
    ``InetAddress.getLocalHost().hostAddress`` (``core/sfc-core/.../util/Networking.kt:27-29``) - the
    host's primary IPv4, **not** loopback.

    Python's obvious equivalent, ``gethostbyname(gethostname())``, does **not** reliably agree with it:
    on macOS it returns ``127.0.0.1`` while the JVM returns the LAN address, so a harness that trusted it
    would sit and time out against a service that was listening perfectly well. Rather than try to
    out-guess either resolver, every plausible local address is collected and probed.
    """
    candidates: list[str] = [primary_ipv4()]
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = str(info[4][0])
            if addr not in candidates:
                candidates.append(addr)
    except (socket.gaierror, OSError):
        pass
    if "127.0.0.1" not in candidates:
        candidates.append("127.0.0.1")
    return tuple(candidates)


def local_host_address() -> str:
    """Best single guess at the address an IPC service will bind."""
    return local_ipv4_addresses()[0]


def free_port(host: str = "127.0.0.1") -> int:
    """A port no other unit of this run has been given, that nothing is listening on right now.

    Ports are picked at random from 20000-32767, below the ephemeral ranges of Linux (32768-60999) and
    macOS (49152-65535): a port the kernel hands out to outgoing connections can never collide with a
    server port allocated here, and the kernel recycling a just-released port into the next bind(0) -
    which made two parallel units race for one port - cannot happen. A run uses a few thousand ports;
    the range has 12768.
    """
    for _ in range(500):
        port = random.randint(20000, 32767)
        with _PORTS_LOCK:
            if port in _PORTS_HANDED_OUT:
                continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind((host, port))
                except OSError:
                    continue
            _PORTS_HANDED_OUT.add(port)
            return port
    raise ProcessError("no free port in 20000-32767 after 500 attempts")


_PORTS_LOCK = threading.Lock()
_PORTS_HANDED_OUT: set[int] = set()


class PortGuard:
    """Keeps the fixed IPC ports free for the services that bind them.

    The IPC ports of the examples (50000 and up) lie inside Linux's ephemeral range (32768-60999), and
    since Linux 4.6 connect() takes even source ports first. Any outgoing connection in the container -
    the parallel units, the harness's AWS clients, sfc-main's IPC metrics client reconnecting without
    back-off - can sit on 50000 or 50002 or leave it in TIME_WAIT for 60 s, and the next service then
    exits with "Failed to start server ... Failed to bind". connect() never picks a port that has a bound
    socket, so the harness keeps one bound on every IPC port - SO_REUSEADDR, never listening: a user-space
    ``ip_local_reserved_ports``. With SO_REUSEADDR a socket may bind unless a *listening* socket holds the
    address (socket(7)), and the services' server sockets set it (the Netty and java.nio default), so each
    service binds over the hold. If one ever cannot, the guard falls back to releasing each port just
    before its service starts.
    """

    #: Long enough for a TIME_WAIT (60 s on Linux) to expire.
    WAIT = 75.0

    def __init__(self) -> None:
        self._held: dict[int, socket.socket] = {}
        self._lock = threading.Lock()
        self.bind_over = True

    def reserve(self, ports) -> None:
        """Hold every port that is free right now; :meth:`before_start` waits for the others."""
        for port in ports:
            self._hold(port, wait=0)

    def before_start(self, port: int) -> None:
        """Make sure ``port`` is free for its service, waiting until whatever sits on it has gone."""
        self._hold(port, wait=self.WAIT)
        if not self.bind_over:
            self.release(port)

    def bind_failed(self, port: int) -> None:
        """A service could not bind ``port``. Over a hold, nothing else can have taken it: stop holding."""
        with self._lock:
            if port in self._held:
                self.bind_over = False
        self.release(port)

    def release(self, port: int) -> None:
        with self._lock:
            s = self._held.pop(port, None)
        if s is not None:
            s.close()

    def _hold(self, port: int, wait: float) -> None:
        deadline = time.monotonic() + wait
        while True:
            with self._lock:
                if port in self._held:
                    return
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind(("0.0.0.0", port))
                    self._held[port] = s
                    return
                except OSError:
                    s.close()
            if time.monotonic() >= deadline:
                if wait:
                    raise ProcessError(f"port {port} stayed in use for {wait:.0f}s: {port_holders(port) or '?'}")
                return
            time.sleep(0.25)


#: The IPC ports of this run. IPC units run one at a time, so one guard serves them all.
IPC_PORTS = PortGuard()

_TCP_STATES = {"01": "ESTABLISHED", "02": "SYN_SENT", "06": "TIME_WAIT", "08": "CLOSE_WAIT", "0A": "LISTEN"}


def port_holders(port: int) -> str:
    """The sockets on local ``port``, from /proc/net/tcp (Linux) - for a "port stayed in use" error."""
    def addr(h: str) -> str:
        ip, p = h.split(":")
        return f"{socket.inet_ntoa(bytes.fromhex(ip)[::-1])}:{int(p, 16)}"

    try:
        rows = Path("/proc/net/tcp").read_text().splitlines()[1:]
    except OSError:
        return ""
    found = [f"{_TCP_STATES.get(f[3], f[3])} {addr(f[1])} -> {addr(f[2])}"
             for f in (r.split() for r in rows) if int(f[1].split(":")[1], 16) == port]
    return "; ".join(found[:5])


def start(launch: Launch) -> RunningProcess:
    launch.stdout_path.parent.mkdir(parents=True, exist_ok=True)
    # Merging is tempting but wrong: SFC's own output goes to stdout (ConsoleLogWriter writes straight
    # to System.out) while JVM-level failures - UnsupportedClassVersionError, OOM, a stack trace from a
    # failed class load - land on stderr. Keeping them apart is what lets a case distinguish "SFC logged
    # an error" from "the JVM died".
    out = launch.stdout_path.open("wb")
    err = launch.stderr_path.open("wb")
    popen = subprocess.Popen(
        launch.argv,
        cwd=str(launch.cwd),
        env=launch.env,
        stdout=out,
        stderr=err,
        start_new_session=True,
    )
    return RunningProcess(launch, popen)


def wait_for_port(
    port: int,
    timeout: float,
    proc: RunningProcess | None = None,
    hosts: tuple[str, ...] | None = None,
) -> str:
    """Block until ``port`` accepts a connection on one of ``hosts``; return the host that answered.

    Several hosts are tried because the address an IPC service binds depends on how the host resolves
    its own name (see :func:`local_host_address`). Probing both the primary address and loopback means
    the harness works on a developer laptop and in a container without per-environment configuration.

    If ``proc`` is given and exits first, that is reported instead of timing out - a service that dies on
    a bad configuration should surface its own error, not a misleading "timed out waiting for port".
    """
    candidates = hosts or local_ipv4_addresses()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise ProcessError(
                f"{proc.name} exited with {proc.popen.returncode} before binding port {port}\n"
                f"--- stderr ---\n{proc.tail_stderr()}\n--- stdout ---\n{proc.tail_stdout()}"
            )
        for host in candidates:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex((host, port)) == 0:
                    return host
        time.sleep(0.1)
    raise ProcessError(
        f"port {port} was not listening on any of {candidates} within {timeout}s"
        + (f"\n--- stdout ---\n{proc.tail_stdout()}" if proc is not None else "")
    )


def wait_for_log(path: Path, needle: str, timeout: float, proc: RunningProcess | None = None) -> None:
    """Block until ``needle`` appears in ``path``.

    Used only where there is no socket to probe. Prefer :func:`wait_for_port` or waiting on the sink.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise ProcessError(
                f"{proc.name} exited with {proc.popen.returncode} before logging {needle!r}\n"
                f"--- stderr ---\n{proc.tail_stderr()}"
            )
        if path.is_file():
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                if needle in fh.read():
                    return
        time.sleep(0.1)
    raise ProcessError(f"{needle!r} did not appear in {path.name} within {timeout}s")


_LISTENING = re.compile(r"service started, listening on\s+(\S+):(\d+),")


def wait_for_listening(proc: RunningProcess, timeout: float) -> str:
    """Block until IPC service ``proc`` logs that it listens; return the address it bound.

    Not a TCP probe: the IPC ports lie in Linux's ephemeral range, where a probe's connect() to a port
    nothing listens on yet can pick that very port as its source and connect to itself. The probe then
    reports the port open, and its closed socket blocks the service's bind for 60 s of TIME_WAIT.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        exited = proc.poll() is not None
        m = _LISTENING.search(proc.read_stdout())
        if m:
            return m.group(1)
        if exited:
            # The "Failed to start server" ERROR goes to stderr (ConsoleLogWriter.kt:12).
            out, err = proc.tail_stdout(), proc.tail_stderr()
            kind = BindError if any("Failed to bind" in t or "Address already in use" in t
                                    for t in (out, err)) else ProcessError
            raise kind(f"{proc.name} exited with {proc.popen.returncode} before listening\n"
                       f"--- stderr ---\n{err}\n--- stdout ---\n{out}")
        time.sleep(0.1)
    raise ProcessError(f"{proc.name} did not log 'service started, listening on' within {timeout}s\n"
                       f"--- stdout ---\n{proc.tail_stdout()}")
