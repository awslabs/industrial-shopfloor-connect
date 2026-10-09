# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""MSK administration for the suite: topics per case, read-back, and the stale-topic sweep.

The stack's MSK Provisioned cluster is reached the way SFC's MSK target reaches MSK from outside AWS:
its public bootstrap string (``BootstrapBrokerStringPublicSaslIam``, ``SASL_SSL`` + ``AWS_MSK_IAM`` on
9198, docs/targets/aws-msk.md), looked up at run time from the cluster's name ``SFC_E2E_MSK_CLUSTER_NAME``
(``SFC_E2E_MSK_BOOTSTRAP`` overrides it). MSK does not
auto-create topics by default, so each case creates its own one-partition topic before SFC starts, reads
it back by partition and offset (no consumer group, so no group permissions), and deletes it afterwards.
Topics are named ``sfc_it_<UTC yyyymmddHHMMSS>_<marker>``; the timestamp is what lets the sweep at the
start of every build remove leftovers.

    python3 ci/e2e/lib/kafka_admin.py sweep --older-than 7200
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import tempfile
from pathlib import Path

KAFKA_HOME = Path(os.environ.get("KAFKA_HOME", "/opt/kafka"))
TOPIC_RE = re.compile(r"^sfc_it_(\d{14})_")

CLIENT_PROPERTIES = """security.protocol=SASL_SSL
sasl.mechanism=AWS_MSK_IAM
sasl.jaas.config=software.amazon.msk.auth.iam.IAMLoginModule required;
sasl.client.callback.handler.class=software.amazon.msk.auth.iam.IAMClientCallbackHandler
"""


def bootstrap(cluster_name: str | None = None, override: str | None = None) -> str:
    """The cluster's public SASL/IAM bootstrap string, asked of MSK by cluster name."""
    override = override or os.environ.get("SFC_E2E_MSK_BOOTSTRAP")
    if override:
        return override
    import boto3

    name = cluster_name or os.environ.get("SFC_E2E_MSK_CLUSTER_NAME", "sfc-it-msk")
    kafka = boto3.client("kafka")
    arns = [c["ClusterArn"] for page in kafka.get_paginator("list_clusters_v2").paginate(ClusterNameFilter=name)
            for c in page.get("ClusterInfoList", []) if c.get("ClusterName") == name]
    if not arns:
        raise RuntimeError(f"no MSK cluster named {name!r}")
    return kafka.get_bootstrap_brokers(ClusterArn=arns[0])["BootstrapBrokerStringPublicSaslIam"]


def client_properties() -> Path:
    path = Path(tempfile.gettempdir()) / "sfc-e2e-msk-client.properties"
    if not path.is_file():
        path.write_text(CLIENT_PROPERTIES)
    return path


def topic_name(marker: str) -> str:
    return f"sfc_it_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S')}_{marker}"[:249]


def _tool(name: str) -> str:
    return str(KAFKA_HOME / "bin" / name)


def topics_cmd(bs: str, *args: str) -> list[str]:
    return [_tool("kafka-topics.sh"), "--bootstrap-server", bs, "--command-config", str(client_properties()), *args]


def create_topic(bs: str, topic: str) -> None:
    proc = subprocess.run(topics_cmd(bs, "--create", "--topic", topic, "--partitions", "1"),
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 and "already exists" not in proc.stderr + proc.stdout:
        raise RuntimeError(f"kafka-topics --create failed: {proc.stderr.strip()[:500]}")


def delete_command(bs: str, topic: str) -> list[str]:
    return topics_cmd(bs, "--delete", "--topic", topic)


def list_topics(bs: str) -> list[str]:
    proc = subprocess.run(topics_cmd(bs, "--list"), capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:500])
    return [t.strip() for t in proc.stdout.splitlines() if t.strip()]


def end_offset(bs: str, topic: str) -> int:
    """How many messages partition 0 holds (its log-end offset).

    The console consumer's ``--timeout-ms`` is an *idle* timeout: while SFC keeps producing it never returns.
    Reading exactly this many messages makes every read-back finish as soon as it has caught up.
    """
    proc = subprocess.run([_tool("kafka-get-offsets.sh"), "--bootstrap-server", bs, "--command-config",
                           str(client_properties()), "--topic", topic, "--partitions", "0", "--time", "-1"],
                          capture_output=True, text=True, timeout=120)
    for line in proc.stdout.splitlines():
        parts = line.strip().rsplit(":", 2)
        if len(parts) == 3 and parts[1] == "0":
            return int(parts[2])
    raise RuntimeError(f"kafka-get-offsets gave no offset for {topic}: {proc.stderr.strip()[:300]}")


def consume(bs: str, topic: str, max_messages: int, timeout_ms: int = 15000, headers: bool = False,
            values: bool = True) -> list[str]:
    """Read from partition 0, offset earliest. Returns raw message values (with headers if asked).

    ``values=False`` prints the headers only, one line per message: a binary value (protobuf) contains
    newlines and would split into several lines.
    """
    argv = [_tool("kafka-console-consumer.sh"), "--bootstrap-server", bs, "--consumer.config", str(client_properties()),
            "--topic", topic, "--partition", "0", "--offset", "earliest",
            "--max-messages", str(max_messages), "--timeout-ms", str(timeout_ms)]
    if headers:
        argv += ["--property", "print.headers=true", "--property", "headers.separator=|",
                 "--property", "headers.key.separator=:"]
    if not values:
        argv += ["--property", "print.value=false"]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_ms / 1000 + 60)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def sweep(older_than: int) -> int:
    bs = bootstrap()
    now = dt.datetime.now(dt.timezone.utc)
    deleted = 0
    for topic in list_topics(bs):
        m = TOPIC_RE.match(topic)
        if not m:
            continue
        created = dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
        if (now - created).total_seconds() > older_than:
            subprocess.run(delete_command(bs, topic), capture_output=True, timeout=120)
            deleted += 1
    print(f"kafka sweep: deleted {deleted} stale topic(s)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sweep")
    s.add_argument("--older-than", type=int, default=7200)
    a = ap.parse_args()
    raise SystemExit(sweep(a.older_than))
