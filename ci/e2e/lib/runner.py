# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""The end-to-end runner.

Runs declarative cases against the real SFC process in one or more deployment modes, asserts on what the
destinations received, and writes ``results.json`` / ``REPORT.md`` / ``junit.xml``.

    python3 ci/e2e/run.py --profile push
    python3 ci/e2e/run.py --tier core --modes inprocess,ipc,uberjar --parity
    python3 ci/e2e/run.py --case CORE-SIM-COUNTER-01 --mode uberjar --keep
    python3 ci/e2e/run.py --list

Cases live in one file per area, ``cases/<group>/<area>.json`` = ``{"cases": [...]}``. Each case holds its
SFC configuration per deployment mode: ``config`` (what every mode shares) plus an ``uberjar``,
``inprocess`` and/or ``ipc`` section, each written in that deployment's own style (see ``deploy.py``). The
runner merges the section for the mode into ``config`` and runs the result unchanged, so a failing case
can always be rerun by hand with the command the report prints.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import json
import os
import shutil
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):  # allow `python3 ci/e2e/lib/runner.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from lib import (artifacts as artifacts_mod, asserts, cleanup as cleanup_mod, evidence as evidence_mod,  # type: ignore
                     metrics as metrics_mod, modes as modes_mod, pki as pki_mod, report, runid,
                     services as services_mod, sfcproc, stackenv, steps as steps_mod)
    from lib import deploy as deploy_mod  # type: ignore
    from lib.sinks import SinkContext, SinkError, make_sink  # type: ignore
else:
    from . import (artifacts as artifacts_mod, asserts, cleanup as cleanup_mod, evidence as evidence_mod,
                   metrics as metrics_mod, modes as modes_mod, pki as pki_mod, report, runid,
                   services as services_mod, sfcproc, stackenv, steps as steps_mod)
    from . import deploy as deploy_mod
    from .sinks import SinkContext, SinkError, make_sink

PASS, FAIL, SKIP, ERROR = report.PASS, report.FAIL, report.SKIP, report.ERROR

E2E_DIR = Path(__file__).resolve().parents[1]
CASES_DIR = E2E_DIR / "cases"
TIERS = ("core", "local-infra", "aws")
PROFILES = {"push": ("P0", "P1"), "full": ("P0", "P1", "P2")}
IN_CI = bool(os.environ.get("CODEBUILD_BUILD_ID"))
#: Seconds between a failed attempt's teardown and its retry (--retries).
RETRY_COOLDOWN = 10.0
#: Stand-in stack values for --offline-aws: syntactically right, unresolvable (.invalid), never real.
OFFLINE_STACK = {
    "SFC_E2E_BUCKET": "sfc-it-offline", "SFC_E2E_REGION": "us-east-1", "SFC_E2E_ACCOUNT": "000000000000",
    "SFC_E2E_SQS_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/000000000000/sfc-it-offline",
    "SFC_E2E_SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:000000000000:sfc-it-offline",
    "SFC_E2E_SNS_SINK_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/000000000000/sfc-it-offline-sns",
    "SFC_E2E_IOT_SINK_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/000000000000/sfc-it-offline-iot",
    "SFC_E2E_IOT_ERROR_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/000000000000/sfc-it-offline-iot-err",
    "SFC_E2E_KINESIS_STREAM": "sfc-it-offline", "SFC_E2E_FIREHOSE_STREAM": "sfc-it-offline",
    "SFC_E2E_LAMBDA_FUNCTION": "sfc-it-offline",
    "SFC_E2E_S3T_BUCKET": "sfc-it-fixture-offline",
    "SFC_E2E_S3T_BUCKET_ARN": "arn:aws:s3tables:us-east-1:000000000000:bucket/sfc-it-fixture-offline",
    "SFC_E2E_S3T_NAMESPACE": "sfc_it", "SFC_E2E_S3T_TABLE_A": "sim_a", "SFC_E2E_S3T_TABLE_B": "sim_b",
    "SFC_E2E_SW_MODEL_ID": "00000000-0000-0000-0000-000000000000",
    "SFC_E2E_SW_ASSET_A1_ID": "00000000-0000-0000-0000-0000000000a1",
    "SFC_E2E_SW_ASSET_A2_ID": "00000000-0000-0000-0000-0000000000a2",
    "SFC_E2E_SW_ALIAS_A1": "/sfc-it/fixture/a1", "SFC_E2E_SW_ALIAS_A2": "/sfc-it/fixture/a2",
    "SFC_E2E_MSK_CLUSTER_NAME": "sfc-it-msk",
    "SFC_E2E_MSK_BOOTSTRAP": "b-1-public.sfc-it-msk.offline.invalid:9198,b-2-public.sfc-it-msk.offline.invalid:9198",
    "SFC_E2E_SECRET_NAME": "sfc-it/secret",
    "SFC_E2E_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:000000000000:secret:sfc-it/secret-AbCdEf",
    "SFC_E2E_IOT_ROLE_ALIAS": "sfc-it-role-alias", "SFC_E2E_IOT_DEVICE_POLICY": "sfc-it-device-us-east-1",
    "SFC_E2E_CW_NAMESPACE": "SFC-IT",
}
#: Log lines that mean a component never came up, whatever the case expects.
CLASS_LOADING_ERRORS = ["NoClassDefFoundError", "ClassNotFoundException", "NoSuchMethodError", "NoSuchFieldError",
                        "UnsupportedClassVersionError", "ServiceConfigurationError"]

#: Log lines after which no gate can be met (see Unit.fatal).
FAIL_FAST = ["Error creating instance of", "Error creating service instance"]
#: Extra seconds for every gate and wait in IPC mode (see Unit.allowance).
IPC_ALLOWANCE = 15.0
#: case keys passed to deploy.build_plan as launch options.
LAUNCH_KEYS = ("cliArgs", "cliNoConfig", "cliColor")
#: Sinks that read local state, so they still work with --offline-aws.
LOCAL_SINKS = {"file", "debug", "jsonl", "aws-stub", "aws-stub-requests", "mqtt", "nats", "opcua", "opcua-writes"}


class CaseError(RuntimeError):
    pass


@dataclass
class Case:
    id: str
    file: Path
    spec: dict
    order: int = 0

    @property
    def area(self) -> str:
        return self.file.stem

    @property
    def group(self) -> str:
        return self.file.parent.name

    @property
    def tier(self) -> str:
        return self.spec.get("tier", "core")

    @property
    def priority(self) -> str:
        return self.spec.get("priority", "P1")

    @property
    def title(self) -> str:
        return self.spec.get("title", "")

    def modes(self, requested: list[str]) -> list[str]:
        """The requested modes this case has a configuration for."""
        return [m for m in requested if isinstance(self.spec.get(m), dict)]

    def config_for(self, mode: str) -> dict:
        """``config`` with the mode's section merged in (RFC 7386: objects merge, null deletes)."""
        merged = json.loads(json.dumps(self.spec.get("config") or {}))
        steps_mod._merge(merged, json.loads(json.dumps(self.spec.get(mode) or {})))
        return merged

    def other_configs(self, mode: str) -> list[dict]:
        return [self.config_for(m) for m in modes_mod.MODES if m != mode and isinstance(self.spec.get(m), dict)]

    def gates(self) -> list[dict]:
        """Normalised gates. ``"records": N`` is shorthand for a gate on the ``main`` sink."""
        if "gates" in self.spec:
            return list(self.spec["gates"])
        if "gate" in self.spec:
            return [self.spec["gate"]]
        if self.spec.get("records"):
            return [{"sink": "main", "records": int(self.spec["records"])}]
        return []

    def sink_specs(self) -> dict:
        sinks = dict(self.spec.get("sinks") or {})
        if "main" not in sinks and not self.spec.get("expectStartupFailure"):
            sinks["main"] = {"kind": "file"}
        return sinks


def discover(case_filter, areas, tiers, priorities) -> list[Case]:
    if not CASES_DIR.is_dir():
        raise CaseError(f"no cases directory at {CASES_DIR}")
    out: list[Case] = []
    order = 0
    for area_file in sorted(CASES_DIR.glob("*/*.json")):
        try:
            doc = json.loads(area_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CaseError(f"{area_file}: not valid JSON: {e}") from None
        if not isinstance(doc, dict) or not isinstance(doc.get("cases"), list):
            raise CaseError(f"{area_file}: expected {{\"cases\": [...]}}")
        for spec in doc["cases"]:
            case = Case(id=spec["id"], file=area_file, spec=spec, order=order)
            order += 1
            if case_filter and case.id not in case_filter:
                continue
            if areas and case.area not in areas:
                continue
            if tiers and case.tier not in tiers:
                continue
            if priorities and not case_filter and case.priority not in priorities:
                continue
            out.append(case)
    ids = [c.id for c in out]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise CaseError(f"duplicate case ids: {sorted(dupes)}")
    return out


# --------------------------------------------------------------------------------------------- a unit

class Unit:
    """One case in one mode: the processes, counterparts and sinks of a single run."""

    def __init__(self, case: Case, mode: str, run_id: str, arts, out_root: Path, stack: dict,
                 known_defect_policy: str, offline_aws: bool = False):
        self.case, self.mode, self.run_id, self.arts = case, mode, run_id, arts
        self.offline = offline_aws and case.tier == "aws"
        self.known_defect_policy = known_defect_policy
        self.workdir = out_root / "cases" / f"{case.id}.{mode}"
        self.marker = runid.marker(run_id, case.id, modes_mod.MODE_CODES[mode])
        self.metrics_path = self.workdir / "metrics.jsonl"
        self.stack = stack
        self.cleanup = cleanup_mod.Registry()
        self.services: dict = {}
        self.sinks: dict = {}
        self.plan = None
        self.procs: list[sfcproc.RunningProcess] = []
        self.marks: dict = {}
        self.expect_exit = bool(case.spec.get("expectStartupFailure"))
        # In IPC mode sfc-main's first read stream to each adapter service fails and is retried after
        # IpcSourceReader.WAIT_AFTER_ERROR (10 s, IpcSourceReader.kt:194). Every wait gets that much
        # more time in IPC mode, so no case has to budget for it.
        self.allowance = IPC_ALLOWANCE if mode == "ipc" else 0.0
        self.env: dict[str, str] = {}

    # -- helpers used by steps and sinks -------------------------------------------------------------
    def sfc_processes(self) -> list[sfcproc.RunningProcess]:
        return list(self.procs)

    def process(self, name: str) -> sfcproc.RunningProcess:
        for p in self.procs:
            if p.name == name:
                return p
        raise CaseError(f"no SFC process named {name!r}; have {[p.name for p in self.procs]}")

    def fatal(self) -> str | None:
        """A log line proving the case cannot succeed, so a gate fails at once instead of timing out.

        SFC logs a component it cannot construct and carries on running without it - an MQTT target with
        a bad endpoint means zero records and a 60 s timeout otherwise. Cases that expect such an error
        set ``"failFast": []`` (or their own list)."""
        patterns = self.case.spec.get("failFast", FAIL_FAST)
        for p in self.procs:
            line = p.scan(patterns)
            if line:
                return f"{p.name}: {line}"
        return None

    def dir_path(self, name: str) -> Path:
        return self.workdir / "dirs" / name

    def log_text(self, process: str = "*") -> str:
        return "\n".join(o + "\n" + e for n, (o, e) in self.logs().items() if process in ("*", n))

    def logs(self) -> dict[str, tuple[str, str]]:
        return {p.name: (p.read_stdout(), p.read_stderr()) for p in self.procs}

    # -- SFC lifecycle -------------------------------------------------------------------------------
    def start_sfc(self) -> None:
        timeout = float(self.case.spec.get("timeoutSeconds", 60))
        for launch in self.plan.services:
            # The documented IPC regime (examples/ipc-slmp-s3/README.md): every adapter and target service
            # runs first - it has logged "... service started, listening on <address>:<port>" - and only
            # then is sfc-main started, which sends each service its configuration.
            host = self._start_service(launch, timeout)
            # Services started with only -port bind InetAddress.getLocalHost(): the server entries'
            # Address is ${SFC_E2E_IPC_HOST}, set to the address the service reports.
            self.env[deploy_mod.IPC_HOST_VAR] = host
            self.plan.main.env[deploy_mod.IPC_HOST_VAR] = host
        self.procs.append(sfcproc.start(self.plan.main))

    def _start_service(self, launch: sfcproc.Launch, timeout: float) -> str:
        """Start one IPC service on its fixed port; a lost bind is retried once (see sfcproc.PortGuard)."""
        attempt = 1
        while True:
            sfcproc.IPC_PORTS.before_start(launch.ready_port)
            proc = sfcproc.start(launch)
            self.procs.append(proc)
            try:
                return sfcproc.wait_for_listening(proc, timeout)
            except sfcproc.BindError:
                if attempt == 2:
                    raise
            attempt += 1
            sfcproc.IPC_PORTS.bind_failed(launch.ready_port)
            self.procs.remove(proc)
            for path in (launch.stdout_path, launch.stderr_path):  # kept as evidence next to the retry's
                if path.is_file():
                    path.rename(path.with_name(path.name + ".bindfail"))
            print(f"  [e2e] {self.case.id} {self.mode}: {launch.name} could not bind port {launch.ready_port}; "
                  f"retrying", flush=True)

    def stop_sfc(self) -> None:
        for proc in reversed(self.procs):
            try:
                proc.stop()
            except Exception:  # noqa: BLE001 - keep stopping the rest
                pass
        # Keep the stopped processes for log collection; a restart appends new ones.

    # -- the run -------------------------------------------------------------------------------------
    def run(self) -> "UnitResult":
        result = UnitResult(case=self.case, mode=self.mode, marker=self.marker, workdir=self.workdir)
        started = time.monotonic()
        try:
            if self.workdir.exists():
                shutil.rmtree(self.workdir)
            (self.workdir / "dirs").mkdir(parents=True)
            missing = self._missing_requirements()
            if missing:
                reason = "missing counterpart(s): " + ", ".join(missing)
                if IN_CI:
                    raise CaseError(reason + " - CodeBuild must provide every counterpart")
                result.verdict, result.skip_reason = SKIP, reason
                return result
            if self.case.tier == "aws" and not self.offline and not stackenv.configured(self.stack):
                result.verdict = SKIP
                result.skip_reason = ("AWS tier not configured: no SFC_E2E_* environment and no "
                                      "ci/cdk/outputs.json")
                return result
            self._prepare_env()
            self._run_body(result)
        except Exception as e:  # a harness or startup problem, distinct from a failed assertion
            result.verdict = ERROR
            result.error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=6)}"
        finally:
            self._teardown()
            result.duration = time.monotonic() - started
            result.cleanup_rows = self.cleanup.as_rows()
            if self.plan is not None:
                result.repro = " ".join(self.plan.main.argv)
        return result

    def _missing_requirements(self) -> list[str]:
        missing = []
        for spec in self.case.spec.get("services") or []:
            missing += services_mod.missing(spec.get("kind", ""))
        for req in self.case.spec.get("requires") or []:
            if req.startswith("python:"):
                import importlib.util

                if importlib.util.find_spec(req.split(":", 1)[1]) is None:
                    missing.append(req)
            elif shutil.which(req) is None:
                missing.append(req)
        return sorted(set(missing))

    def _prepare_env(self) -> None:
        case_dir = self.workdir / "case"
        case_dir.mkdir(parents=True, exist_ok=True)
        # A case's fixtures - included files, counterpart specs, templates - are inline in its "files".
        for rel, content in (self.case.spec.get("files") or {}).items():
            path = case_dir / rel
            if rel.endswith("/"):
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, dict) and "base64" in content:
                import base64

                path.write_bytes(base64.b64decode(content["base64"]))
            elif isinstance(content, str):
                path.write_text(content, encoding="utf-8")
            else:
                path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        for d in self.case.spec.get("dirs") or []:
            self.dir_path(d).mkdir(parents=True, exist_ok=True)
        env = dict(OFFLINE_STACK if self.offline else self.stack)
        env.update({
            "SFC_E2E_RUN_ID": self.run_id,
            "SFC_E2E_CASE": self.case.id,
            "SFC_E2E_MODE": self.mode,
            "SFC_E2E_MODE_CODE": modes_mod.MODE_CODES[self.mode],
            "SFC_E2E_MARKER": self.marker,
            # Hyphen forms, for names that forbid underscores (S3 Tables buckets). Bucket names are capped
            # at 63 characters, so per-run buckets compose RUN_DASH with a short case code, not the marker.
            "SFC_E2E_MARKER_DASH": self.marker.replace("_", "-"),
            "SFC_E2E_RUN_DASH": self.run_id.replace("_", "-"),
            "SFC_E2E_METRICS": str(self.metrics_path),
            "SFC_E2E_WORK": str(self.workdir),
            "SFC_E2E_CASE_DIR": str(case_dir),
            "SFC_E2E_DEAD_PORT": str(sfcproc.free_port("127.0.0.1")),
            "SFC_E2E_UBERJAR": str(self.arts.uberjar),
            "SFC_E2E_REPO": str(artifacts_mod.repo_root()),
        })
        if self.arts.support_jar is not None:
            env["SFC_E2E_SUPPORT_JAR"] = str(self.arts.support_jar)
        pki = self.arts.workdir / "pki"
        if pki.is_dir():
            env["SFC_E2E_PKI"] = str(pki)
        for d in self.case.spec.get("dirs") or []:
            env[f"SFC_E2E_DIR_{d.upper().replace('-', '_')}"] = str(self.dir_path(d))
        self.services = services_mod.build(self.case.spec.get("services") or [], self.workdir, env)
        for svc in self.services.values():
            env.update(svc.exports())
        env.update({k: str(v) for k, v in (self.case.spec.get("env") or {}).items()})
        if self.offline:
            # Nothing may reach AWS: every SDK endpoint is a dead local port, the credentials are inert, and
            # no profile, SSO cache or instance metadata is consulted.
            env.update({
                "AWS_ACCESS_KEY_ID": "offline", "AWS_SECRET_ACCESS_KEY": "offline", "AWS_REGION": "us-east-1",
                "AWS_ENDPOINT_URL": f"http://127.0.0.1:{env['SFC_E2E_DEAD_PORT']}",
                "AWS_CONFIG_FILE": os.devnull, "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
                "AWS_EC2_METADATA_DISABLED": "true", "AWS_PROFILE": "",
            })
        self.env = env

    def _run_body(self, result: "UnitResult") -> None:
        case, spec = self.case, self.case.spec
        timeout = float(spec.get("timeoutSeconds", 60)) + self.allowance

        for svc in self.services.values():
            if not svc.deferred:
                svc.start(self.env)

        ctx = SinkContext(case_id=case.id, mode=self.mode, run_id=self.run_id, marker=self.marker,
                          workdir=self.workdir, env=self.env, started_at=time.time(),
                          cleanup=self.cleanup, processes=self.sfc_processes, fatal=self.fatal)
        for name, sink_spec in case.sink_specs().items():
            sink = make_sink(name, sink_spec, ctx)
            if self.offline and sink_spec.get("kind", "file") not in LOCAL_SINKS:
                self.env.update(sink.offline_exports())
                continue
            self.env.update(sink.prepare())
            self.sinks[name] = sink

        self.plan = deploy_mod.build_plan(
            mode=self.mode, config=case.config_for(self.mode), artifacts=self.arts, case_dir=self.workdir,
            env=self.env, log_level=spec.get("cliLogLevel", "info"),
            launch={k: spec[k] for k in LAUNCH_KEYS if k in spec},
            services=spec.get("ipcServices") or {}, other_configs=case.other_configs(self.mode),
            classpath=spec.get("uberjarClasspath") or [],
        )
        self.start_sfc()
        main = self.procs[-1]

        if self.offline and not spec.get("expectStartupFailure"):
            self._offline_smoke(result, main)
            return

        if spec.get("expectStartupFailure"):
            # ServiceMain calls exitProcess(1) on a configuration error, so the exit IS the observable.
            try:
                main.popen.wait(timeout=timeout)
            except Exception:
                raise CaseError(f"expected a startup failure but sfc-main was still running after {timeout}s") from None
        else:
            steps_mod.run(self, spec.get("steps") or [], timeout)
            gates = case.gates()
            if not gates and not spec.get("steps"):
                raise CaseError("the case declares no gate (records/gate/gates) and no steps")
            for gate in gates:
                sink = self.sinks[gate.get("sink", "main")]
                if gate.get("orExit"):
                    try:
                        sink.wait(int(gate["records"]), self._gate_timeout(gate, timeout))
                    except SinkError:
                        if main.poll() is None:
                            raise
                else:
                    sink.wait(int(gate["records"]), self._gate_timeout(gate, timeout))

        # Collect BEFORE stopping: nothing may rely on the process flushing on exit.
        collected = {name: sink.records() for name, sink in self.sinks.items()}
        self.stop_sfc()
        # Except a destination that keeps no order: read to the end now that nothing more can come. The gates
        # were met before the stop, so no case depends on what an IPC service still sends on SIGTERM.
        for name, sink in self.sinks.items():
            if sink.drain():
                collected[name] = sink.records()
        # Evidence: what each sink saw, as read - a queue or a broker leaves nothing behind to inspect.
        collected_dir = self.workdir / "collected"
        collected_dir.mkdir(exist_ok=True)
        for name, recs in collected.items():
            with open(collected_dir / f"{name}.jsonl", "w", encoding="utf-8") as f:
                for rec in recs:
                    f.write(json.dumps(rec, default=str) + "\n")
        result.exit_code = main.popen.returncode
        for svc in self.services.values():
            svc.stop()

        snapshot = metrics_mod.MetricsSnapshot.load(self.metrics_path)
        result.metrics_rows = snapshot.summary()
        default_sink = (case.gates()[0].get("sink", "main") if case.gates() else "main")
        result.records = collected.get(default_sink, [])
        result.sink_counts = {k: len(v) for k, v in collected.items()}

        ctx_assert = asserts.Context(
            records=result.records, sinks=collected, logs=self.logs(), exit_code=result.exit_code,
            metrics=snapshot, workdir=self.workdir, marks=self.marks, env=self.env,
            sink_objects=self.sinks,
        )
        result.assertions = asserts.evaluate(ctx_assert, self._assertions())

        # The independent oracle: a target can count a WriteError, drop data and still exit 0.
        if not spec.get("expectStartupFailure"):
            allowed = spec.get("allowWriteErrors", [])
            core_errors_logged = any(t in self.log_text() for t in (
                "Timeout writing to target", "Error writing to target",  # ScheduleWriter.kt:252-257
                "Error IPC initializing", "Error communicating with target IPC service"))  # IpcTargetWriter.kt:126, :163-166
            for target, count in snapshot.write_errors().items():
                if allowed is True or target in allowed:
                    continue
                if target == "SfcCore" and self.mode == "ipc" and not core_errors_logged:
                    # ScheduleWriter.kt:243-249: a record for an IPC target that has not finished initializing is
                    # dropped and counted as a core WriteError, logged at TRACE only: start-up loss. A target that
                    # failed to initialize or lost its stream drops the same way, but logs it - that still fails.
                    continue
                result.assertions.append(asserts.Result(
                    "noWriteErrors", False, f"target {target!r} reported {count:g} {metrics_mod.WRITE_ERRORS}", 0, count))

        if any(not a.ok for a in result.assertions):
            result.verdict = FAIL

    def _offline_smoke(self, result: "UnitResult", main) -> None:
        """--offline-aws: the configuration loads in this mode and the targets come up and try to write.

        Proves what can be proven without the account - the case's config parses and validates, every
        component loads from this mode's artifacts, nothing crashes - and nothing more: there is no
        destination to read back, so the case's own assertions are not evaluated."""
        seconds = float(self.case.spec.get("offlineSeconds", 10))
        deadline = time.monotonic() + seconds
        fatal = None
        while time.monotonic() < deadline and fatal is None and all(p.poll() is None for p in self.procs):
            fatal = self.fatal()
            time.sleep(0.25)
        exited = [f"{p.name} exited {p.popen.returncode}" for p in self.procs if p.poll() is not None]
        self.stop_sfc()
        result.exit_code = main.popen.returncode
        logs = "\n".join(o + "\n" + e for o, e in self.logs().values())
        loading = [t for t in CLASS_LOADING_ERRORS if t in logs]
        snapshot = metrics_mod.MetricsSnapshot.load(self.metrics_path)
        dead = f"127.0.0.1:{self.env['SFC_E2E_DEAD_PORT']}"
        attempted = bool(snapshot.write_errors()) or dead in logs
        result.assertions = [
            asserts.Result("offlineStartup", fatal is None, fatal or f"no fatal log line in {seconds:g}s", "none", fatal),
            asserts.Result("offlineAlive", not exited, ", ".join(exited) or "all processes running", "running", exited or "running"),
            asserts.Result("offlineClassLoading", not loading, f"present: {loading}" if loading else "clean", "none", loading or "none"),
        ]
        if self.case.spec.get("offlineExpectWrite", True):
            # The target got as far as its write path: a WriteError metric, or the dead endpoint in a log.
            result.assertions.append(asserts.Result(
                "offlineWriteAttempted", attempted, "write path reached" if attempted else
                f"no WriteError and no attempt on {dead} - did the target ever receive data?", "attempted", attempted))
        result.skip_reason = "offline smoke: configuration and loading only, no destination read back"
        if any(not a.ok for a in result.assertions):
            result.verdict = FAIL

    def _gate_timeout(self, gate: dict, default: float) -> float:
        return float(gate["timeoutSeconds"]) + self.allowance if "timeoutSeconds" in gate else default

    def _assertions(self) -> list[dict]:
        base = list(self.case.spec.get("assert", []))
        defect = self.case.spec.get("knownDefect")
        if not defect:
            return base
        key = "assertCurrent" if self.known_defect_policy == "assert-current" else "assertCorrect"
        extra = defect.get(key)
        if extra is None:
            raise CaseError(f"knownDefect is missing {key!r}")
        return base + (extra if isinstance(extra, list) else [extra])

    def _teardown(self) -> None:
        self.stop_sfc()
        for svc in self.services.values():
            try:
                svc.stop()
            except Exception:  # noqa: BLE001
                pass
        for sink in self.sinks.values():
            try:
                sink.cleanup()
            except Exception:  # noqa: BLE001
                pass
        self.cleanup.run()


@dataclass
class UnitResult:
    case: Case
    mode: str
    marker: str
    workdir: Path
    verdict: str = PASS
    duration: float = 0.0
    records: list = field(default_factory=list)
    sink_counts: dict = field(default_factory=dict)
    assertions: list = field(default_factory=list)
    metrics_rows: list = field(default_factory=list)
    cleanup_rows: list = field(default_factory=list)
    error: str | None = None
    skip_reason: str | None = None
    repro: str = ""
    exit_code: int | None = None
    attempts: int = 1
    earlier: list = field(default_factory=list)        # one {attempt, verdict, reason} per failed attempt
    attempt_dirs: list = field(default_factory=list)   # the failed attempts' kept workdirs, uploaded too

    def reason(self) -> str:
        """The first failed assertion, else the first error line: why this attempt did not pass."""
        bad = next((a for a in self.assertions if not a.ok), None)
        if bad is not None:
            return f"{bad.kind}: {bad.detail}"
        return (self.error or "").splitlines()[0] if self.error else ""

    def as_dict(self) -> dict:
        c = self.case
        d = {
            "id": c.id, "title": c.title, "area": c.area, "tier": c.tier, "priority": c.priority,
            "mode": self.mode, "marker": self.marker, "intent": c.spec.get("intent"),
            "pins": c.spec.get("pins", []), "verdict": self.verdict,
            "durationSeconds": round(self.duration, 3), "recordCount": len(self.records),
            "sinkCounts": self.sink_counts, "assertions": [a.as_dict() for a in self.assertions],
            "repro": self.repro, "exitCode": self.exit_code, "artifacts": str(self.workdir),
        }
        if self.metrics_rows:
            d["metrics"] = self.metrics_rows
        if self.cleanup_rows:
            d["cleanup"] = self.cleanup_rows
        if self.error:
            d["error"] = self.error
        if self.skip_reason:
            d["skipReason"] = self.skip_reason
        if c.spec.get("knownDefect"):
            d["knownDefect"] = c.spec["knownDefect"]
        if self.attempts > 1:
            d["attempts"] = self.attempts
            d["earlier"] = self.earlier
        return d


# --------------------------------------------------------------------------------------------- parity

def _typed(value):
    """Type-tagged canonical form: ``1`` and ``1.0`` must NOT compare equal across modes.

    Python's ``==`` treats them as equal, which made an int-versus-double divergence between modes (the
    IPC hop crosses protobuf) invisible to the parity check.
    """
    if isinstance(value, bool):
        return ["b", value]
    if isinstance(value, int):
        return ["i", value]
    if isinstance(value, float):
        return ["f", repr(value)]
    if isinstance(value, dict):
        return ["o", sorted((k, _typed(v)) for k, v in value.items())]
    if isinstance(value, list):
        return ["a", [_typed(v) for v in value]]
    return ["s", value]


def parity(results: list[UnitResult]) -> list[dict]:
    """Compare normalised output for the same case across modes.

    Serials, timestamps and the per-mode marker are normalised away; everything else must match, because
    the simulator is deterministic from process start and every mode ran to the same record count.
    """
    by_case: dict[str, list[UnitResult]] = {}
    for r in results:
        if r.case.spec.get("modeParity") and r.verdict == PASS:
            by_case.setdefault(r.case.id, []).append(r)
    out = []
    for case_id, group in sorted(by_case.items()):
        if len(group) < 2:
            continue
        n = min(len(r.records) for r in group)

        def canon(r: UnitResult):
            # Normalise what legitimately differs per mode: serials and timestamps (anywhere, also inside
            # template text), the run identity (marker, mode, run id - wherever ElementNames put them),
            # and the file sink's bookkeeping (file name, path).
            identity = {r.marker: "<MARKER>", r.workdir.name: "<UNIT>"}
            rid = r.marker.split("_" + r.case.id.lower().replace("-", "_"))[0] if r.marker else ""

            def scrub(v):
                if isinstance(v, dict):
                    return {k: scrub(x) for k, x in v.items() if k not in ("path", "entry")}
                if isinstance(v, list):
                    return [scrub(x) for x in v]
                if isinstance(v, str):
                    for needle, token in identity.items():
                        if needle:
                            v = v.replace(needle, token)
                    if rid:
                        v = v.replace(rid, "<RUN>")
                    if v in (r.mode, modes_mod.MODE_CODES.get(r.mode)):
                        return "<MODE>"
                    v = v.replace(f'"{r.mode}"', '"<MODE>"')  # the mode inside raw text (JSON-in-a-file, templates)
                    v = asserts.UUID_RE.sub("<UUID>", v)
                    return asserts.ISO_RE.sub("<ISO>", v)
                return v

            return json.dumps(_typed(scrub(r.records[:n])), sort_keys=True)

        base = canon(group[0])
        divergent = [r.mode for r in group[1:] if canon(r) != base]
        out.append({"id": case_id, "modes": [r.mode for r in group], "identical": not divergent,
                    "detail": (f"identical across {len(group)} modes ({n} records)" if not divergent
                               else f"{group[0].mode} differs from {', '.join(divergent)}")})
    return out


# ----------------------------------------------------------------------------------------------- main

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the SFC end-to-end suite")
    ap.add_argument("--profile", choices=sorted(PROFILES), help="push = P0+P1, full = everything")
    ap.add_argument("--tier", help=f"comma-separated subset of {','.join(TIERS)} (default: all)")
    ap.add_argument("--mode", help="a single deployment mode")
    ap.add_argument("--modes", help=f"comma-separated subset of {','.join(modes_mod.MODES)} (default: all)")
    ap.add_argument("--case", action="append", help="run only this case id (repeatable)")
    ap.add_argument("--area", help="comma-separated areas")
    ap.add_argument("--jobs", type=int, default=1, help="case runs in parallel")
    ap.add_argument("--retries", type=int, default=3,
                    help="re-run a failed or errored case run up to N times, each with a fresh marker (0: never)")
    ap.add_argument("--out", type=Path, default=E2E_DIR / "out", help="output root")
    ap.add_argument("--evidence", help="s3://bucket/prefix/ - upload each case run as it finishes")
    ap.add_argument("--parity", action="store_true", help="compare output across modes")
    ap.add_argument("--known-defects", choices=("assert-current", "assert-correct"), default="assert-current",
                    help="assert-current pins today's behaviour (default); assert-correct proves the "
                         "defect cases actually discriminate")
    ap.add_argument("--offline-aws", action="store_true",
                    help="run aws-tier cases with no account: stand-in stack values, every AWS endpoint a dead "
                         "local port; checks configuration and loading only")
    ap.add_argument("--keep", action="store_true", help="keep unpacked artifacts between runs")
    ap.add_argument("--list", action="store_true", help="list matching cases and exit")
    ap.add_argument("--render", type=Path, metavar="DIR",
                    help="write the configuration SFC would get in each mode to DIR/<ID>.<mode>.json and exit "
                         "(nothing is started)")
    args = ap.parse_args(argv)
    # Every launcher, jar, config and service path is derived from --out, and each process runs in its own
    # case directory: a relative --out (CodeBuild passes "e2e-out") would resolve against the wrong cwd.
    args.out = args.out.resolve()
    if args.render:
        args.render = args.render.resolve()

    if args.mode and args.modes:
        ap.error("use --mode or --modes, not both")
    requested_modes = [args.mode] if args.mode else (args.modes.split(",") if args.modes else list(modes_mod.MODES))
    for m in requested_modes:
        if m not in modes_mod.MODES:
            ap.error(f"unknown mode {m!r}")
    tiers = [t for t in (args.tier.split(",") if args.tier else TIERS) if t]
    priorities = PROFILES.get(args.profile) if args.profile else None
    areas = [a.strip() for a in args.area.split(",")] if args.area else None

    cases = discover(args.case, areas, tiers, priorities)
    if not cases:
        print("no cases matched", file=sys.stderr)
        return 2
    if args.list:
        for c in cases:
            print(f"{c.id:40} {c.area:22} {c.tier:11} {c.priority} {','.join(c.modes(requested_modes)) or '-'}")
        return 0

    stack = stackenv.load()
    run_id = runid.current_run_id()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_root = args.out / f"e2e-{stamp}-{run_id}"
    out_root.mkdir(parents=True, exist_ok=True)

    needed: set[str] = set()
    for case in cases:
        for mode in case.modes(requested_modes):
            try:
                needed.update(deploy_mod.required_modules(mode, case.config_for(mode), case.spec.get("ipcServices") or {},
                                                          case.other_configs(mode), case.spec.get("uberjarClasspath") or []))
            except modes_mod.ModeError:
                pass  # reported per unit
    print(f"[e2e] run {run_id} -> {out_root}")
    print(f"[e2e] {len(cases)} case(s) x {len(requested_modes)} mode(s), jobs={args.jobs}, "
          f"profile={args.profile or 'all'}, aws tier "
          f"{'offline smoke' if args.offline_aws else 'configured' if stackenv.configured(stack) else 'not configured'}")
    arts = artifacts_mod.prepare(sorted(needed), workdir=args.out / "artifacts", clean=not args.keep)
    if shutil.which("openssl"):
        pki_mod.generate(arts.workdir / "pki")
    if args.render:
        return _render(cases, requested_modes, arts, args.render, run_id)

    units: list[tuple[Case, str]] = []
    skipped: list[UnitResult] = []
    for case in cases:
        case_modes = case.modes(requested_modes)
        if not case_modes:
            r = UnitResult(case=case, mode=requested_modes[0], marker="", workdir=out_root)
            r.verdict, r.skip_reason = SKIP, f"case supports only {case.spec.get('modes')}"
            skipped.append(r)
            continue
        units.extend((case, m) for m in case_modes)

    uploader = evidence_mod.Uploader(args.evidence)
    lock = threading.Lock()
    results: list[UnitResult] = list(skipped)
    started = time.monotonic()

    def finish(r: UnitResult) -> None:
        mark = report._MARK[r.verdict]
        tail = f"  {r.error.splitlines()[0]}" if r.error else (f"  {r.skip_reason}" if r.skip_reason else "")
        with lock:
            results.append(r)
            print(f"  {mark} {r.case.id:40} {r.mode:9} {r.duration:5.1f}s{tail}", flush=True)
            paths = _write(results, out_root, run_id, arts, requested_modes, tiers, args, started, stack)
        uploader.case_dir(r.workdir, f"{r.case.id}.{r.mode}")
        for d in r.attempt_dirs:
            uploader.case_dir(d, d.name)
        uploader.files(list(paths.values()))

    # IPC units use the fixed ports of their configuration (from 50000, as in the examples), so only one
    # runs at a time; in-process and uberjar units run in parallel alongside. Those ports are held for
    # the whole run, so no outgoing connection of the parallel units can take one (sfcproc.PortGuard).
    ipc_lane = threading.Lock()
    ipc_ports: set[int] = set()
    for case, mode in units:
        if mode == "ipc":
            config = case.config_for(mode)
            for section in ("AdapterServers", "TargetServers"):
                ipc_ports.update(deploy_mod.server_port(config, section, k) for k in config.get(section) or {})
    sfcproc.IPC_PORTS.reserve(sorted(ipc_ports))

    # IoT Core is read back through the topic rule's one shared queue: two IoT units reading it at once starve
    # each other, so they run one at a time too (taken before the IPC lane, which must never wait on it).
    iot_lane = threading.Lock()

    def run_one(case: Case, mode: str) -> UnitResult:
        iot = any(s.get("kind") == "iot" and not s.get("retainedTopic") for s in case.sink_specs().values())
        with iot_lane if iot else contextlib.nullcontext(), ipc_lane if mode == "ipc" else contextlib.nullcontext():
            earlier, kept, retries = [], [], max(0, args.retries)
            for attempt in range(1 + retries):
                # A retry gets a run id - and so a marker and destinations - of its own: it must never read
                # the failed attempt's leftovers.
                rid = run_id if attempt == 0 else runid.retry_run_id(run_id, attempt)
                r = Unit(case, mode, rid, arts, out_root, stack, args.known_defects, args.offline_aws).run()
                if r.verdict not in (FAIL, ERROR) or attempt == retries:
                    break
                earlier.append({"attempt": attempt + 1, "verdict": r.verdict, "reason": r.reason()})
                # Keep the failed attempt's evidence; Unit.run() starts by wiping its workdir.
                kept_dir = r.workdir.with_name(f"{r.workdir.name}.attempt{attempt + 1}")
                if r.workdir.is_dir():
                    shutil.rmtree(kept_dir, ignore_errors=True)
                    r.workdir.rename(kept_dir)
                    kept.append(kept_dir)
                print(f"  ↻ {case.id:40} {mode:9} attempt {attempt + 1} {r.verdict}: {earlier[-1]['reason'][:120]}"
                      f" - retrying in {RETRY_COOLDOWN:g}s", flush=True)
                time.sleep(RETRY_COOLDOWN)  # teardown has run; let ports, brokers and services settle
            r.attempts, r.earlier, r.attempt_dirs = attempt + 1, earlier, kept
            return r

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(run_one, c, m) for c, m in units]
        for fut in concurrent.futures.as_completed(futures):
            finish(fut.result())

    paths = _write(results, out_root, run_id, arts, requested_modes, tiers, args, started, stack, final=True)
    uploader.files(list(paths.values()))

    failed = sum(1 for r in results if r.verdict in (FAIL, ERROR))
    passed = sum(1 for r in results if r.verdict == PASS)
    skips = sum(1 for r in results if r.verdict == SKIP)
    print(f"\n[e2e] {passed} passed, {failed} failed, {skips} skipped in {time.monotonic() - started:.1f}s")
    print(f"[e2e] report  {paths['markdown']}")
    data = json.loads(paths["results"].read_text())
    if args.parity and data.get("modeParity"):
        bad = [p for p in data["modeParity"] if not p["identical"]]
        print(f"[e2e] parity  {len(data['modeParity']) - len(bad)}/{len(data['modeParity'])} identical")
        failed += len(bad)
    if uploader.errors:
        print(f"[e2e] evidence upload had {len(uploader.errors)} error(s); first: {uploader.errors[0]}")
    return 1 if failed else 0


def _render(cases: list[Case], requested_modes: list[str], arts, out: Path, run_id: str) -> int:
    """--render: each case's configuration per mode as SFC gets it, plus the process command lines."""
    out.mkdir(parents=True, exist_ok=True)
    for case in cases:
        for mode in case.modes(requested_modes):
            scratch = out / ".scratch" / f"{case.id}.{mode}"
            target = out / f"{case.id}.{mode}.json"
            try:
                plan = deploy_mod.build_plan(
                    mode=mode, config=case.config_for(mode), artifacts=arts, case_dir=scratch, env={},
                    log_level=case.spec.get("cliLogLevel", "info"),
                    launch={k: case.spec[k] for k in LAUNCH_KEYS if k in case.spec},
                    services=case.spec.get("ipcServices") or {}, other_configs=case.other_configs(mode),
                    classpath=case.spec.get("uberjarClasspath") or [])
            except modes_mod.ModeError as e:
                print(f"  {case.id:40} {mode:10} not renderable: {e}")
                continue
            target.write_text(json.dumps(plan.config, indent=2) + "\n", encoding="utf-8")
            procs = [" ".join(l.argv) for l in plan.services] + [" ".join(plan.main.argv)]
            procs = [p.replace(str(plan.config_path), str(target)) for p in procs]
            (out / f"{case.id}.{mode}.argv.txt").write_text("\n".join(procs) + "\n", encoding="utf-8")
            print(f"  {case.id:40} {mode:10} -> {target}")
    shutil.rmtree(out / ".scratch", ignore_errors=True)
    return 0


def _write(results, out_root, run_id, arts, modes, tiers, args, started, stack, final=False):
    ordered = sorted(results, key=lambda r: (r.case.order, modes_mod.MODES.index(r.mode)
                                             if r.mode in modes_mod.MODES else 9))
    data = {
        "run": {
            "runId": run_id, "durationSeconds": round(time.monotonic() - started, 2), "final": final,
            "modes": modes, "tiers": tiers, "profile": args.profile or "all",
            "uberjar": arts.uberjar.name,
            "uberjarSha256": _sha256(arts.uberjar) if final else "-",
            "sfcVersion": arts.uberjar.name.replace("sfc-uberjar-", "").replace(".jar", ""),
            # Provenance without git: CI passes these in; a local run reports "local".
            "commit": os.environ.get("SFC_E2E_COMMIT", "local"),
            "ref": os.environ.get("SFC_E2E_REF", "local"),
            "dirty": os.environ.get("SFC_E2E_DIRTY") == "1",
            "knownDefectPolicy": args.known_defects,
            # Where each case run's evidence lands (evidence.py), for the report's S3 console links.
            "evidence": args.evidence,
            "region": os.environ.get("SFC_E2E_REGION") or os.environ.get("AWS_REGION"),
            "awsTier": ("offline smoke" if args.offline_aws else
                        "configured" if stackenv.configured(stack) else "not configured"),
            "environment": {"python": sys.version.split()[0], "platform": sys.platform,
                            "buildId": os.environ.get("CODEBUILD_BUILD_ID", "-"), "jobs": args.jobs},
        },
        "cases": [r.as_dict() for r in ordered],
    }
    if args.parity:
        data["modeParity"] = parity(ordered)
    untestable = E2E_DIR / "untestable.json"
    if untestable.is_file():
        data["untestable"] = json.loads(untestable.read_text(encoding="utf-8"))
    return report.write_all(data, out_root)


if __name__ == "__main__":
    raise SystemExit(main())
