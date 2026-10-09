# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Shared definitions for the three SFC deployment modes: names, JVM bounds, the component table.

How a case's configuration becomes a deployment is in ``deploy.py``. Nothing here rewrites a configuration.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import sfcproc
from .artifacts import Artifacts

MODES = ("inprocess", "ipc", "uberjar")

#: Short codes used in run markers and resource names, which have tight length and charset limits.
MODE_CODES = {"inprocess": "ip", "ipc": "ipc", "uberjar": "uj"}

#: Bounds for every SFC JVM. An OOM becomes a visible non-zero exit instead of a container-wide stall.
#: The generated launchers ship DEFAULT_JVM_OPTS="" and honour JAVA_OPTS / <APP>_OPTS; the uberjar is
#: launched with java directly, so it gets these on the command line (it used to get none).
JVM_BOUNDS = ["-Xmx512m", "-XX:MaxMetaspaceSize=256m", "-XX:+ExitOnOutOfMemoryError"]

LOG_LEVELS = {"error": "-error", "warning": "-warning", "info": "-info", "trace": "-trace"}

#: Every SFC process logs without ANSI colour codes, so log assertions and the debug sink see plain text.
NO_COLOR = "-nocolor"

#: FactoryClassName -> (module directory name, IPC service main class).
#:
#: An explicit table rather than one derived at runtime: deriving it would mean parsing every
#: build.gradle.kts on every run, and a silent mis-derivation would send a case to the wrong module.
#: A missing entry raises, so adding a component to the suite is a deliberate edit.
COMPONENTS: dict[str, tuple[str, str]] = {
    # protocol adapters with a software counterpart in CodeBuild
    "com.amazonaws.sfc.simulator.SimulatorAdapter": ("simulator", "com.amazonaws.sfc.simulator.SimulatorService"),
    "com.amazonaws.sfc.opcua.OpcuaAdapter": ("opcua", "com.amazonaws.sfc.opcua.OpcuaProtocolService"),
    "com.amazonaws.sfc.mqtt.MqttAdapter": ("mqtt", "com.amazonaws.sfc.mqtt.MqttProtocolService"),
    "com.amazonaws.sfc.nats.NatsAdapter": ("nats", "com.amazonaws.sfc.nats.NatsProtocolService"),
    "com.amazonaws.sfc.rest.RestAdapter": ("rest", "com.amazonaws.sfc.rest.RestProtocolService"),
    "com.amazonaws.sfc.modbus.tcp.ModbusTcpAdapter": ("modbus-tcp", "com.amazonaws.sfc.modbus.tcp.ModbusTcpProtocolService"),
    "com.amazonaws.sfc.snmp.SnmpAdapter": ("snmp", "com.amazonaws.sfc.snmp.SnmpProtocolService"),
    "com.amazonaws.sfc.sql.SqlAdapter": ("sql", "com.amazonaws.sfc.sql.SqlProtocolService"),
    "com.amazonaws.sfc.s7.S7Adapter": ("s7", "com.amazonaws.sfc.s7.S7ProtocolService"),
    "com.amazonaws.sfc.ads.AdsAdapter": ("ads", "com.amazonaws.sfc.ads.AdsProtocolService"),
    "com.amazonaws.sfc.pccc.PcccAdapter": ("pccc", "com.amazonaws.sfc.pccc.PcccProtocolService"),
    "com.amazonaws.sfc.slmp.SlmpAdapter": ("slmp", "com.amazonaws.sfc.slmp.SlmpProtocolService"),
    # local targets
    "com.amazonaws.sfc.debugtarget.DebugTargetWriter": ("debug-target", "com.amazonaws.sfc.debugtarget.DebugTargetService"),
    "com.amazonaws.sfc.filetarget.FileTargetWriter": ("file-target", "com.amazonaws.sfc.filetarget.FileTargetService"),
    "com.amazonaws.sfc.mqtt.MqttTargetWriter": ("mqtt-target", "com.amazonaws.sfc.mqtt.MqttTargetService"),
    "com.amazonaws.sfc.natstarget.NatsTargetWriter": ("nats-target", "com.amazonaws.sfc.natstarget.NatsTargetService"),
    "com.amazonaws.sfc.opcuatarget.OpcuaTargetWriter": ("opcua-target", "com.amazonaws.sfc.opcuatarget.OpcuaTargetService"),
    "com.amazonaws.sfc.opcuawritetarget.OpcuaTargetWriter": ("opcua-writer-target", "com.amazonaws.sfc.opcuawritetarget.OpcuaWriterTargetService"),
    # intermediate targets
    "com.amazonaws.sfc.router.RouterTargetWriter": ("router-target", "com.amazonaws.sfc.router.AwsRouterTargetService"),
    "com.amazonaws.sfc.storeforward.StoreForwardTargetWriter": ("store-forward-target", "com.amazonaws.sfc.storeforward.AwsStoreForwardTargetService"),
    # AWS targets (SiteWise Edge is out of scope)
    "com.amazonaws.sfc.awss3.AwsS3TargetWriter": ("aws-s3-target", "com.amazonaws.sfc.awss3.AwsS3TargetService"),
    "com.amazonaws.sfc.awssqs.AwsSqsTargetWriter": ("aws-sqs-target", "com.amazonaws.sfc.awssqs.AwsSqsTargetService"),
    "com.amazonaws.sfc.awssns.AwsSnsTargetWriter": ("aws-sns-target", "com.amazonaws.sfc.awssns.AwsSnsTargetService"),
    "com.amazonaws.sfc.awsiotcore.AwsIotCoreTargetWriter": ("aws-iot-core-target", "com.amazonaws.sfc.awsiotcore.AwsIotCoreTargetService"),
    "com.amazonaws.sfc.awskinesis.AwsKinesisTargetWriter": ("aws-kinesis-target", "com.amazonaws.sfc.awskinesis.AwsKinesisTargetService"),
    "com.amazonaws.sfc.awsfirehose.AwsKinesisFirehoseTargetWriter": ("aws-kinesis-firehose-target", "com.amazonaws.sfc.awsfirehose.AwsKinesisFirehoseTargetService"),
    "com.amazonaws.sfc.awslambda.AwsLambdaTargetWriter": ("aws-lambda-target", "com.amazonaws.sfc.awslambda.AwsLambdaTargetService"),
    "com.amazonaws.sfc.awss3tables.AwsS3TablesTargetWriter": ("aws-s3-tables-target", "com.amazonaws.sfc.awss3tables.AwsS3TablesTargetService"),
    "com.amazonaws.sfc.awssitewise.AwsSiteWiseTargetWriter": ("aws-sitewise-target", "com.amazonaws.sfc.awssitewise.AwsSitewiseTargetService"),
    "com.amazonaws.sfc.awsmsk.AwsMskTargetWriter": ("aws-msk-target", "com.amazonaws.sfc.awsmsk.AwsMskTargetService"),
}

#: Writers that live in the CloudWatch metrics module rather than in a target module.
METRICS_WRITERS: dict[str, str] = {
    "com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriter": "aws-cloudwatch-metrics",
}

#: Test-support classes, shipped in ci/e2e-support rather than in a module tarball. In-process and IPC
#: mode point JarFiles at the support jar; uberjar mode puts it on the classpath.
SUPPORT_CLASSES = {
    "com.amazonaws.sfc.e2e.E2eMetricsWriter",
    "com.amazonaws.sfc.e2e.E2eLineFormatter",
}



class ModeError(RuntimeError):
    pass



@dataclass
class Plan:
    """Everything needed to run one case in one mode."""

    mode: str
    config_path: Path
    #: The configuration as written to config_path (live reload patches it and writes it again).
    config: dict = field(default_factory=dict)
    #: IPC service processes to start (and wait for) before sfc-main. Empty except in IPC mode.
    services: list[sfcproc.Launch] = field(default_factory=list)
    #: The sfc-main / uberjar process.
    main: sfcproc.Launch | None = None
    #: Launch name -> (section, server key) in AdapterServers/TargetServers, for address correction.
    server_keys: dict[str, tuple[str, str]] = field(default_factory=dict)

    def write_config(self) -> None:
        self.config_path.write_text(json.dumps(self.config, indent=2) + "\n", encoding="utf-8")



def _expand(value: str, env: dict[str, str]) -> str:
    for k, v in env.items():
        value = value.replace("${" + k + "}", str(v))
    return value


def java() -> str:
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / "java"
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("java")
    if not found:
        raise ModeError("no java on PATH and JAVA_HOME is unset")
    return found


def base_env(extra: dict[str, str]) -> dict[str, str]:
    """A deliberately narrow environment.

    Built from scratch so a developer's ``AWS_PROFILE``, locale or timezone cannot change a result.
    ``TZ=UTC`` matters concretely: FileTargetWriter partitions output into ``<dir>/YYYY/M/D/H/M/`` using
    the *local* calendar unless ``UtcTime`` is set. ``LC_ALL=C`` pins the JDK 17 default charset, which
    several targets use to encode payloads.
    """
    bounds = " ".join(JVM_BOUNDS)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TZ": "UTC",
        "LC_ALL": "C",
        "JAVA_OPTS": bounds,
        "SFC_MAIN_OPTS": bounds,
    }
    for key in ("JAVA_HOME", "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE",
                "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_CONTAINER_CREDENTIALS_FULL_URI",
                "AWS_CONTAINER_AUTHORIZATION_TOKEN", "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_ROLE_ARN"):
        if key in os.environ:
            env[key] = os.environ[key]
    env.update(extra)
    return env







