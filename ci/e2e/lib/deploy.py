# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""The three SFC deployments, each from its own explicit configuration.

A case carries one configuration per deployment mode, written the way an SFC user writes it (see the
examples directory). The runner runs that configuration as it is; nothing is rewritten.

* **uberjar** (``examples/uberjar-*``): ``AdapterTypes``/``TargetTypes`` entries name ``FactoryClassName``
  only. Every class is on the uberjar's classpath.
* **inprocess** (``examples/in-process-*``): the same entries add ``JarFiles``, by convention
  ``${SFC_DEPLOYMENT_DIR}/<module>/lib`` (docs/sfc-running-adapters.md). ``SFC_DEPLOYMENT_DIR`` is the
  directory the module tarballs are unpacked into.
* **ipc** (``examples/ipc-*``): no ``AdapterTypes``/``TargetTypes`` at all. Each adapter names an
  ``AdapterServer`` and each target a ``TargetServer``, defined in ``AdapterServers``/``TargetServers``
  with fixed ports from 50000, as in the examples. Each server is a separate process started first with
  ``bin/<module> -port <its port>``; then sfc-main starts and sends each one its configuration.

``check()`` enforces these rules on every case and mode. Other in-process components that still run
inside a process - the metrics writer, a target's ``Formatter``, a custom ``LogWriter`` or
``ConfigProvider`` - follow the in-process rule (``JarFiles``) in inprocess and ipc mode, and the
uberjar rule (``FactoryClassName`` only) in uberjar mode.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import sfcproc
from .artifacts import Artifacts
from .modes import (COMPONENTS, JVM_BOUNDS, LOG_LEVELS, MODES, NO_COLOR, ModeError, Plan, base_env, java)

#: The JarFiles convention from docs/sfc-running-adapters.md.
DEPLOYMENT_DIR_VAR = "SFC_DEPLOYMENT_DIR"
_MODULE_JAR = re.compile(r"^\$\{SFC_DEPLOYMENT_DIR\}/([^/]+)/lib/?$")


#: The address every IPC server entry points at: where the services listen. A service started with only
#: ``-port`` binds InetAddress.getLocalHost(); the runner sets this to the address the service reports
#: ("listening on <address>:<port>") before sfc-main reads its configuration.
IPC_HOST_VAR = "SFC_E2E_IPC_HOST"


def server_port(config: dict, section: str, key: str) -> int:
    """The fixed port of a server entry (``"Port": 50000``)."""
    port = ((config.get(section) or {}).get(key) or {}).get("Port")
    try:
        return int(port)
    except (TypeError, ValueError):
        raise ModeError(f"{section}.{key}: Port must be a fixed number (as in the examples), got {port!r}") from None


# ----------------------------------------------------------------------------------------- the rules

def _factory_entries(node, path="$"):
    """Every InProcessConfiguration-shaped dict (one with a FactoryClassName), with its JSON path."""
    if isinstance(node, dict):
        if "FactoryClassName" in node:
            yield path, node
        for k, v in node.items():
            yield from _factory_entries(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _factory_entries(v, f"{path}[{i}]")


def check(mode: str, config: dict) -> list[str]:
    """Violations of the deployment rules for ``mode``; empty when the configuration is well-formed."""
    errors: list[str] = []
    adapters = config.get("ProtocolAdapters") or {}
    targets = config.get("Targets") or {}
    if mode in ("uberjar", "inprocess"):
        for key in ("AdapterServers", "TargetServers"):
            if key in config:
                errors.append(f"{mode}: has {key} - servers are the IPC deployment")
        for aid, a in adapters.items():
            if isinstance(a, dict) and "AdapterServer" in a:
                errors.append(f"{mode}: ProtocolAdapters.{aid} names an AdapterServer")
        for tid, t in targets.items():
            if isinstance(t, dict) and "TargetServer" in t:
                errors.append(f"{mode}: Targets.{tid} names a TargetServer")
        for path, entry in _factory_entries(config):
            has_jars = bool(entry.get("JarFiles"))
            if mode == "uberjar" and "JarFiles" in entry:
                errors.append(f"uberjar: {path} has JarFiles - an uberjar config names the FactoryClassName only")
            if mode == "inprocess" and not has_jars:
                errors.append(f"inprocess: {path} has no JarFiles - an in-process config loads every class from JarFiles")
    elif mode == "ipc":
        for key in ("AdapterTypes", "TargetTypes"):
            if key in config:
                errors.append(f"ipc: has {key} - IPC adapters and targets are servers, not in-process types")
        servers_a = config.get("AdapterServers") or {}
        servers_t = config.get("TargetServers") or {}
        for aid, a in adapters.items():
            ref = a.get("AdapterServer") if isinstance(a, dict) else None
            if not ref:
                errors.append(f"ipc: ProtocolAdapters.{aid} has no AdapterServer")
            elif ref not in servers_a:
                errors.append(f"ipc: ProtocolAdapters.{aid}.AdapterServer {ref!r} is not in AdapterServers")
        for tid, t in targets.items():
            if not isinstance(t, dict) or t.get("Active") is False:
                continue
            ref = t.get("TargetServer")
            if not ref:
                errors.append(f"ipc: Targets.{tid} has no TargetServer")
            elif ref not in servers_t:
                errors.append(f"ipc: Targets.{tid}.TargetServer {ref!r} is not in TargetServers")
        for path, entry in _factory_entries(config):
            if not entry.get("JarFiles"):
                errors.append(f"ipc: {path} has no JarFiles - the processes of an IPC deployment load extension classes from JarFiles")
    else:
        errors.append(f"unknown mode {mode!r}")
    return errors


# ---------------------------------------------------------------------------------- what to unpack

def modules_from_jarfiles(config: dict) -> set[str]:
    out = set()
    for _path, entry in _factory_entries(config):
        for jar in entry.get("JarFiles") or []:
            m = _MODULE_JAR.match(str(jar))
            if m:
                out.add(m.group(1))
    return out


def ipc_servers(config: dict) -> list[tuple[str, str, str, dict]]:
    """``(server key, kind, component id, component)`` for every server an active component uses."""
    out = []
    for aid, a in (config.get("ProtocolAdapters") or {}).items():
        if isinstance(a, dict) and a.get("AdapterServer"):
            out.append((a["AdapterServer"], "adapter", aid, a))
    for tid, t in (config.get("Targets") or {}).items():
        if isinstance(t, dict) and t.get("TargetServer") and t.get("Active") is not False:
            out.append((t["TargetServer"], "target", tid, t))
    seen, unique = set(), []
    for item in out:
        if item[0] not in seen:
            seen.add(item[0])
            unique.append(item)
    return unique


def ipc_module(server_key: str, kind: str, component: dict, services: dict, other_configs: list[dict]) -> str:
    """Which module's service binary serves ``server_key``.

    ``ipcServices.<server>.module`` says it explicitly. Otherwise it is the module whose class the same
    adapter/target type names in the case's uberjar or in-process configuration - the same component,
    deployed differently."""
    explicit = (services.get(server_key) or {}).get("module")
    if explicit:
        return explicit
    type_key, section = ("AdapterType", "AdapterTypes") if kind == "adapter" else ("TargetType", "TargetTypes")
    type_name = component.get(type_key)
    for cfg in other_configs:
        entry = (cfg.get(section) or {}).get(type_name)
        factory = entry.get("FactoryClassName") if isinstance(entry, dict) else None
        if factory in COMPONENTS:
            return COMPONENTS[factory][0]
    raise ModeError(f"IPC server {server_key!r}: no module known for {type_key} {type_name!r} - "
                    f"add \"ipcServices\": {{\"{server_key}\": {{\"module\": \"<tarball name>\"}}}} to the case")


def required_modules(mode: str, config: dict, services: dict, other_configs: list[dict],
                     classpath: list[str] | None = None) -> set[str]:
    if mode == "uberjar":
        return {e.split(":", 1)[1] for e in classpath or [] if e.startswith("module:")}
    modules = {"sfc-main"} | modules_from_jarfiles(config)
    if mode == "ipc":
        for key, kind, _cid, comp in ipc_servers(config):
            modules.add(ipc_module(key, kind, comp, services, other_configs))
    return modules


# --------------------------------------------------------------------------------------------- plan

def _expand(value: str, env: dict) -> str:
    for k, v in env.items():
        value = value.replace("${" + k + "}", str(v))
    return value


def build_plan(*, mode: str, config: dict, artifacts: Artifacts, case_dir: Path, env: dict,
               log_level: str = "info", launch: dict | None = None, services: dict | None = None,
               other_configs: list[dict] | None = None, classpath: list[str] | None = None) -> Plan:
    """The processes that run ``config`` as a ``mode`` deployment. ``config`` is written out unchanged.

    ``env`` is updated in place with what the configuration's placeholders need: ``SFC_DEPLOYMENT_DIR``,
    ``SFC_E2E_SUPPORT_JAR`` and, in IPC mode, one ``SFC_E2E_IPC_<SERVER>_PORT`` per server.
    """
    if mode not in MODES:
        raise ModeError(f"unknown mode {mode!r}")
    problems = check(mode, config)
    if problems:
        raise ModeError("the configuration breaks the deployment rules:\n  " + "\n  ".join(problems))
    launch = launch or {}
    services = services or {}
    level_flag = LOG_LEVELS.get(log_level)
    if level_flag is None and log_level != "none":
        raise ModeError(f"unknown cliLogLevel {log_level!r}")
    level = [level_flag] if level_flag else []
    color = [] if launch.get("cliColor") else [NO_COLOR]
    case_dir.mkdir(parents=True, exist_ok=True)
    logs = case_dir / "logs"
    logs.mkdir(exist_ok=True)

    env[DEPLOYMENT_DIR_VAR] = str(artifacts.workdir)
    if artifacts.support_jar is not None:
        env["SFC_E2E_SUPPORT_JAR"] = str(artifacts.support_jar)

    launches: list[sfcproc.Launch] = []
    server_keys: dict[str, tuple[str, str]] = {}
    if mode == "ipc":
        for key, kind, cid, comp in ipc_servers(config):
            module = ipc_module(key, kind, comp, services, other_configs or [])
            section = "AdapterServers" if kind == "adapter" else "TargetServers"
            port = server_port(config, section, key)
            name = f"{kind}-{cid}"
            extra = [_expand(str(a), env) for a in (services.get(key) or {}).get("args", [])]
            launches.append(sfcproc.Launch(
                name=name,
                argv=[str(artifacts.module_launcher(module)), "-port", str(port), *level, *color, *extra],
                cwd=case_dir, env=base_env(env), stdout_path=logs / f"{name}.out", stderr_path=logs / f"{name}.err",
                ready_port=port))
            server_keys[name] = (section, key)
        argv = [str(artifacts.module_launcher("sfc-main"))]
    elif mode == "inprocess":
        argv = [str(artifacts.module_launcher("sfc-main"))]
    else:
        cp = [str(artifacts.uberjar)]
        if artifacts.support_jar is not None:
            cp.append(str(artifacts.support_jar))
        for pattern in classpath or []:
            if pattern.startswith("module:"):
                cp.append(str(artifacts.module_dir(pattern.split(":", 1)[1]) / "lib" / "*"))
                continue
            found = sorted(str(p) for p in Path(artifacts.root).glob(pattern))
            if not found:
                raise ModeError(f"uberjarClasspath: nothing matches {pattern!r}")
            cp.extend(found)
        argv = [java(), *JVM_BOUNDS, "-cp", os.pathsep.join(cp), "com.amazonaws.sfc.MainController"]

    config_path = case_dir / "config.json"
    config_args = [] if launch.get("cliNoConfig") else ["-config", str(config_path)]
    main = sfcproc.Launch(
        name="sfc-main",
        argv=argv + config_args + level + color + [_expand(str(a), env) for a in launch.get("cliArgs", [])],
        cwd=case_dir, env=base_env(env), stdout_path=logs / "sfc-main.out", stderr_path=logs / "sfc-main.err")
    plan = Plan(mode=mode, config_path=config_path, config=config, services=launches, main=main,
                server_keys=server_keys)
    plan.explicit = True
    plan.write_config()
    return plan
