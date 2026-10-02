# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""The three SFC deployment modes, from one mode-agnostic case configuration.

A case writes exactly one ``config.json``, in canonical form: components are named by
``FactoryClassName`` alone, with no ``JarFiles`` and no ``AdapterServer``/``TargetServer`` keys. This
module mechanically derives the three concrete configurations from it. That is deliberate - if each
mode had its own hand-written config, a mode-parity failure could always be dismissed as "the configs
differ", and the comparison would prove nothing.

The modes are genuinely different code paths, not packaging variations
(``core/sfc-core/.../util/InstanceFactory.kt:22-45``):

* **uberjar** - no ``JarFiles``, so ``Class.forName`` resolves the factory from the system classpath.
* **in-process** - ``JarFiles`` present, so a ``URLClassLoader`` is built over the module's jars. This
  is the branch a uberjar-only suite never touches, and where the v1.9.5 "InstanceFactory classloader"
  bug lived.
* **IPC** - no local class loading at all; sfc-main talks gRPC to separate service processes. It is
  also the only mode whose processes install JVM shutdown hooks.

sfc-main selects per component purely on the presence of a server key - ``TargetServer``
(MainControllerService.kt:303) and ``AdapterServer`` (:354) - which is what makes the transformation
below sufficient.
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

#: FactoryClassName -> (module directory name, IPC service main class).
#:
#: Kept as an explicit table rather than derived at runtime: deriving it would mean parsing 34
#: build.gradle.kts files on every run, and a silent mis-derivation would send a case to the wrong
#: module. A missing entry raises, so adding a component to the suite is a deliberate edit.
COMPONENTS: dict[str, tuple[str, str]] = {
    # adapters
    "com.amazonaws.sfc.simulator.SimulatorAdapter": ("simulator", "com.amazonaws.sfc.simulator.SimulatorService"),
    # local targets
    "com.amazonaws.sfc.debugtarget.DebugTargetWriter": ("debug-target", "com.amazonaws.sfc.debugtarget.DebugTargetService"),
    "com.amazonaws.sfc.filetarget.FileTargetWriter": ("file-target", "com.amazonaws.sfc.filetarget.FileTargetService"),
    "com.amazonaws.sfc.router.RouterTargetWriter": ("router-target", "com.amazonaws.sfc.router.AwsRouterTargetService"),
    "com.amazonaws.sfc.storeforward.StoreForwardTargetWriter": ("store-forward-target", "com.amazonaws.sfc.storeforward.AwsStoreForwardTargetService"),
    # AWS targets
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

#: The metrics writer is test-support code, so it has no module tarball and no IPC service. It is
#: handled separately from COMPONENTS: in-process mode points JarFiles at its jar, uberjar mode puts
#: that jar on the classpath, and IPC mode runs it in the sfc-main process like in-process mode does.
METRICS_FACTORY = "com.amazonaws.sfc.e2e.E2eMetricsWriter"


class ModeError(RuntimeError):
    pass


def module_for(factory_class: str) -> str:
    try:
        return COMPONENTS[factory_class][0]
    except KeyError:
        raise ModeError(
            f"no module known for FactoryClassName {factory_class!r}.\n"
            "  Add it to COMPONENTS in tests/e2e/lib/modes.py."
        ) from None


def service_class_for(factory_class: str) -> str:
    try:
        return COMPONENTS[factory_class][1]
    except KeyError:
        raise ModeError(f"no IPC service class known for {factory_class!r}") from None


def required_modules(config: dict, mode: str) -> list[str]:
    """Which module tarballs must be unpacked for this configuration in this mode."""
    if mode == "uberjar":
        return []
    modules = {"sfc-main"}
    for section in ("AdapterTypes", "TargetTypes"):
        for entry in (config.get(section) or {}).values():
            factory = entry.get("FactoryClassName")
            if factory:
                modules.add(module_for(factory))
    return sorted(modules)


@dataclass
class Plan:
    """Everything needed to run one case in one mode."""

    mode: str
    config_path: Path
    #: The rendered configuration. Kept so IPC mode can correct the server addresses once the services
    #: have actually bound, before sfc-main reads the file.
    config: dict = field(default_factory=dict)
    #: Service processes to start (and wait for) before sfc-main. Empty except in IPC mode.
    services: list[sfcproc.Launch] = field(default_factory=list)
    #: The sfc-main / uberjar process.
    main: sfcproc.Launch | None = None
    #: Launch name -> server key in AdapterServers/TargetServers, for address correction.
    server_keys: dict[str, tuple[str, str]] = field(default_factory=dict)

    def write_config(self) -> None:
        self.config_path.write_text(json.dumps(self.config, indent=2) + "\n", encoding="utf-8")

    def set_server_host(self, launch_name: str, host: str) -> None:
        """Record the address a service was actually reached on.

        An IPC service binds ``InetAddress.getLocalHost()`` when no ``-interface`` is given, and whether
        that resolves to a LAN address or to loopback depends on the host's own name resolution. Rather
        than guess, the runner probes, then writes back what answered - so sfc-main always dials an
        address that is known to be listening.
        """
        section, key = self.server_keys[launch_name]
        self.config[section][key]["Address"] = host


def _java() -> str:
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / "java"
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("java")
    if not found:
        raise ModeError("no java on PATH and JAVA_HOME is unset")
    return found


def _base_env(extra: dict[str, str]) -> dict[str, str]:
    """A deliberately narrow environment.

    Built from scratch rather than inherited so that a developer's ``AWS_PROFILE``, locale or timezone
    cannot change a result. ``TZ=UTC`` matters concretely: FileTargetWriter partitions output into
    ``<dir>/YYYY/M/D/H/M/`` using the *local* calendar unless ``UtcTime`` is set, so an inherited
    timezone would move files between directories depending on who ran the suite.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TZ": "UTC",
        "LC_ALL": "C",
        # Bound the JVM so an OOM is a visible non-zero exit rather than a container-wide stall. The
        # generated launchers ship DEFAULT_JVM_OPTS="" and honour these variables.
        "JAVA_OPTS": "-Xmx512m -XX:MaxMetaspaceSize=256m -XX:+ExitOnOutOfMemoryError",
        "SFC_MAIN_OPTS": "-Xmx512m -XX:MaxMetaspaceSize=256m -XX:+ExitOnOutOfMemoryError",
    }
    for key in ("JAVA_HOME", "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
                "AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_ROLE_ARN"):
        if key in os.environ:
            env[key] = os.environ[key]
    env.update(extra)
    return env


def _inject_jarfiles(config: dict, artifacts: Artifacts) -> None:
    """Point every component at its module's lib directory - the in-process contract."""
    for section in ("AdapterTypes", "TargetTypes"):
        for entry in (config.get(section) or {}).values():
            factory = entry.get("FactoryClassName")
            if factory:
                entry["JarFiles"] = [artifacts.module_lib_glob(module_for(factory))]

    writer = _metrics_writer_entry(config)
    if writer is not None:
        if artifacts.support_jar is None:
            raise ModeError(
                "the case configures E2eMetricsWriter but tests/e2e-support has not been built.\n"
                "  Run: ./gradlew :tests:e2e-support:build"
            )
        writer["JarFiles"] = [str(artifacts.support_jar)]


def _metrics_writer_entry(config: dict) -> dict | None:
    writer = ((config.get("Metrics") or {}).get("Writer") or {}).get("MetricsWriter")
    if isinstance(writer, dict) and writer.get("FactoryClassName") == METRICS_FACTORY:
        return writer
    return None


def _inject_ipc_servers(config: dict, ports: dict[str, int], host: str) -> dict[str, tuple[str, str]]:
    """Rewrite the configuration so every adapter and target is reached over gRPC.

    ``ports`` maps a component key (``adapter:<id>`` / ``target:<id>``) to its allocated port. Returns a
    map from launch name to (section, server key) so the runner can correct addresses after probing.
    """
    adapter_servers: dict[str, dict] = {}
    target_servers: dict[str, dict] = {}
    server_keys: dict[str, tuple[str, str]] = {}

    for adapter_id, adapter in (config.get("ProtocolAdapters") or {}).items():
        server = f"{adapter_id}Server"
        adapter["AdapterServer"] = server
        adapter_servers[server] = {"Address": host, "Port": ports[f"adapter:{adapter_id}"]}
        server_keys[f"adapter-{adapter_id}"] = ("AdapterServers", server)

    for target_id, target in (config.get("Targets") or {}).items():
        key = f"target:{target_id}"
        # Chained targets (router, store-forward) run in the sfc-main process even in IPC mode: they
        # have no device of their own to reach, and giving them a service would need one process per
        # link in the chain for no added coverage.
        if key not in ports:
            continue
        server = f"{target_id}Server"
        target["TargetServer"] = server
        target_servers[server] = {"Address": host, "Port": ports[key]}
        server_keys[f"target-{target_id}"] = ("TargetServers", server)

    config["AdapterServers"] = adapter_servers
    config["TargetServers"] = target_servers
    return server_keys


def build_plan(
    *,
    mode: str,
    base_config: dict,
    artifacts: Artifacts,
    case_dir: Path,
    env: dict[str, str],
    ipc_local_targets: set[str] | None = None,
) -> Plan:
    """Render the configuration for ``mode`` and describe the processes to run.

    ``ipc_local_targets`` names targets that stay in-process even in IPC mode (chained targets).
    """
    if mode not in MODES:
        raise ModeError(f"unknown mode {mode!r}, expected one of {MODES}")

    config = copy.deepcopy(base_config)
    case_dir.mkdir(parents=True, exist_ok=True)
    logs = case_dir / "logs"
    logs.mkdir(exist_ok=True)

    java = _java()
    services: list[sfcproc.Launch] = []
    # Populated only in IPC mode; see Plan.set_server_host.
    server_keys: dict[str, tuple[str, str]] = {}

    if mode == "uberjar":
        # No JarFiles anywhere: this is the branch that resolves factories from the system classpath.
        # -cp with an explicit main class rather than -jar, so the support jar can be appended; -jar
        # ignores -cp entirely.
        classpath = [str(artifacts.uberjar)]
        if artifacts.support_jar is not None:
            classpath.append(str(artifacts.support_jar))
        argv = [java, "-cp", os.pathsep.join(classpath), "com.amazonaws.sfc.MainController"]

    elif mode == "inprocess":
        _inject_jarfiles(config, artifacts)
        argv = [str(artifacts.module_launcher("sfc-main"))]

    else:  # ipc
        _inject_jarfiles(config, artifacts)
        local = ipc_local_targets or set()
        ports: dict[str, int] = {}
        # The address the services will bind, resolved the same way SFC resolves it. Ports are reserved
        # on that address too, so the reservation is against the interface actually used.
        ipc_host = sfcproc.local_host_address()

        for adapter_id, adapter in (config.get("ProtocolAdapters") or {}).items():
            adapter_type = adapter.get("AdapterType")
            factory = ((config.get("AdapterTypes") or {}).get(adapter_type) or {}).get("FactoryClassName")
            if not factory:
                raise ModeError(f"adapter {adapter_id!r} has no resolvable FactoryClassName")
            ports[f"adapter:{adapter_id}"] = sfcproc.free_port(ipc_host)

        for target_id, target in (config.get("Targets") or {}).items():
            if target_id in local:
                continue
            target_type = target.get("TargetType")
            factory = ((config.get("TargetTypes") or {}).get(target_type) or {}).get("FactoryClassName")
            if not factory:
                raise ModeError(f"target {target_id!r} has no resolvable FactoryClassName")
            ports[f"target:{target_id}"] = sfcproc.free_port(ipc_host)

        for adapter_id, adapter in (config.get("ProtocolAdapters") or {}).items():
            factory = config["AdapterTypes"][adapter["AdapterType"]]["FactoryClassName"]
            port = ports[f"adapter:{adapter_id}"]
            module = module_for(factory)
            services.append(
                sfcproc.Launch(
                    name=f"adapter-{adapter_id}",
                    # -port directly, with a port the runner reserved. The documented -envport
                    # indirection exists for orchestrators that own the environment; here the runner
                    # owns both sides, so one less indirection is one less thing to get wrong.
                    argv=[str(artifacts.module_launcher(module)), "-port", str(port), "-info"],
                    cwd=case_dir,
                    env=_base_env(env),
                    stdout_path=logs / f"adapter-{adapter_id}.out",
                    stderr_path=logs / f"adapter-{adapter_id}.err",
                    ready_port=port,
                )
            )

        for target_id, target in (config.get("Targets") or {}).items():
            key = f"target:{target_id}"
            if key not in ports:
                continue
            factory = config["TargetTypes"][target["TargetType"]]["FactoryClassName"]
            port = ports[key]
            module = module_for(factory)
            services.append(
                sfcproc.Launch(
                    name=f"target-{target_id}",
                    argv=[str(artifacts.module_launcher(module)), "-port", str(port), "-info"],
                    cwd=case_dir,
                    env=_base_env(env),
                    stdout_path=logs / f"target-{target_id}.out",
                    stderr_path=logs / f"target-{target_id}.err",
                    ready_port=port,
                )
            )

        server_keys = _inject_ipc_servers(config, ports, ipc_host)
        argv = [str(artifacts.module_launcher("sfc-main"))]

    config_path = case_dir / "config.json"

    main = sfcproc.Launch(
        name="sfc-main",
        argv=argv + ["-config", str(config_path), "-info"],
        cwd=case_dir,
        env=_base_env(env),
        stdout_path=logs / "sfc-main.out",
        stderr_path=logs / "sfc-main.err",
    )

    plan = Plan(
        mode=mode,
        config_path=config_path,
        config=config,
        services=services,
        main=main,
        server_keys=server_keys,
    )
    # Written now so non-IPC modes need no further step; IPC rewrites it after probing.
    plan.write_config()
    return plan
