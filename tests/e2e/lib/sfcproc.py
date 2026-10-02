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
matters - a listening socket for an IPC service, or the first record arriving at the sink - never by a
log line and never by sleeping.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class ProcessError(RuntimeError):
    pass


@dataclass
class Launch:
    """One process to run: what to execute, where, and how to know it is up."""

    name: str
    argv: list[str]
    cwd: Path
    env: dict[str, str]
    stdout_path: Path
    stderr_path: Path
    #: When set, readiness is "this TCP port accepts a connection".
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

    def tail_stderr(self, lines: int = 40) -> str:
        return _tail(self.launch.stderr_path, lines)

    def tail_stdout(self, lines: int = 40) -> str:
        return _tail(self.launch.stdout_path, lines)


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
    """Reserve an ephemeral port by binding and immediately releasing it.

    This is what makes concurrent runs safe: each IPC service is handed a port the runner picked, so two
    builds on the same host never contend for a fixed 50051. There is a small race between release and
    the service binding; it is accepted because the alternative - a fixed range - collides far more often
    in practice.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


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
