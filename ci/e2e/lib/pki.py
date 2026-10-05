# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""A throwaway PKI per run, for the TLS cases (IPC ServerSideTLS/MutualTLS, MQTT over TLS).

Generated once per run with the openssl CLI into ``<out>/artifacts/pki`` and exported to cases as
``SFC_E2E_PKI``. Nothing is checked in, so no key in the repository can ever be mistaken for a real one.

    ca.crt ca.key              the run CA
    server.crt server.key      SAN: localhost, the host name, 127.0.0.1 and every local IPv4 - IPC services
                               bind InetAddress.getLocalHost(), so clients may reach them on any of those
    client.crt client.key      signed by the run CA (mutual TLS)
    rogue-ca.crt rogue-client.crt rogue-client.key
                               a second, unrelated CA and a client it signed: the "wrong CA" negatives

Keys are PKCS#8 PEM (OpenSSL 3's default), which is what gRPC's netty TLS expects.
"""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

from . import sfcproc


class PkiError(RuntimeError):
    pass


def _openssl(*args: str, cwd: Path) -> None:
    proc = subprocess.run(["openssl", *args], cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise PkiError(f"openssl {' '.join(args[:2])} failed: {proc.stderr.strip()}")


def _issue(d: Path, name: str, cn: str, ca: str, ext: str) -> None:
    _openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{name}.key", "-out", f"{name}.csr",
             "-subj", f"/O=sfc-e2e/CN={cn}", cwd=d)
    (d / f"{name}.ext").write_text(ext)
    _openssl("x509", "-req", "-in", f"{name}.csr", "-CA", f"{ca}.crt", "-CAkey", f"{ca}.key",
             "-CAcreateserial", "-days", "2", "-sha256", "-out", f"{name}.crt", "-extfile", f"{name}.ext", cwd=d)


def generate(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    if (d / "server.crt").is_file() and (d / "rogue-client.crt").is_file():
        return d  # --keep: reuse
    names = ["DNS:localhost", f"DNS:{socket.gethostname()}", "IP:127.0.0.1"]
    names += [f"IP:{ip}" for ip in sfcproc.local_ipv4_addresses() if ip != "127.0.0.1"]
    san = "subjectAltName=" + ",".join(dict.fromkeys(names))
    for ca in ("ca", "rogue-ca"):
        _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-sha256",
                 "-keyout", f"{ca}.key", "-out", f"{ca}.crt", "-subj", f"/O=sfc-e2e/CN=sfc-e2e-{ca}", cwd=d)
    _issue(d, "server", "sfc-e2e-server", "ca", f"{san}\nextendedKeyUsage=serverAuth\n")
    _issue(d, "client", "sfc-e2e-client", "ca", f"{san}\nextendedKeyUsage=clientAuth\n")
    _issue(d, "rogue-client", "sfc-e2e-rogue-client", "rogue-ca", f"{san}\nextendedKeyUsage=clientAuth\n")
    for p in d.glob("*.csr"):
        p.unlink()
    return d
