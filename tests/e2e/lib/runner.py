# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""The end-to-end runner.

Runs declarative cases against a real SFC process in one or more deployment modes, asserts on the
output, and writes ``results.json`` / ``REPORT.md`` / ``junit.xml``.

    python3 tests/e2e/run.py --tier core --mode inprocess
    python3 tests/e2e/run.py --tier core --modes inprocess,ipc,uberjar --parity
    python3 tests/e2e/run.py --case FILT-CHG-ABS-01 --mode uberjar --keep

The shape of a case is deliberately boring: a directory holding ``case.json`` (the contract) and
``config.json`` (a real, complete SFC configuration). ``config.json`` is copied verbatim into the run
directory and passed to SFC unchanged apart from the mode transformation in ``modes.py``, so a failing
case can always be rerun by hand with the command the report prints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):  # allow `python3 tests/e2e/lib/runner.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from lib import artifacts as artifacts_mod  # type: ignore
    from lib import asserts, metrics as metrics_mod, modes as modes_mod, report, sfcproc, sink as sink_mod  # type: ignore
else:
    from . import artifacts as artifacts_mod
    from . import asserts, metrics as metrics_mod, modes as modes_mod, report, sfcproc, sink as sink_mod

PASS, FAIL, SKIP, ERROR = report.PASS, report.FAIL, report.SKIP, report.ERROR

E2E_DIR = Path(__file__).resolve().parents[1]
CASES_DIR = E2E_DIR / "cases"


class CaseError(RuntimeError):
    pass


@dataclass
class Case:
    id: str
    dir: Path
    spec: dict
    config: dict

    @property
    def area(self) -> str:
        return self.spec.get("area") or self.dir.parent.name

    @property
    def tier(self) -> str:
        return self.spec.get("tier", "core")

    @property
    def title(self) -> str:
        return self.spec.get("title", "")

    def modes(self, requested: list[str]) -> list[str]:
        """Intersect what the case supports with what was asked for.

        A case may restrict itself - a negative startup case has nothing mode-specific to prove three
        times over, and an IPC-only case cannot run any other way.
        """
        allowed = self.spec.get("modes") or list(modes_mod.MODES)
        return [m for m in requested if m in allowed]


def discover(case_filter: list[str] | None, areas: list[str] | None, tiers: list[str]) -> list[Case]:
    cases: list[Case] = []
    if not CASES_DIR.is_dir():
        raise CaseError(f"no cases directory at {CASES_DIR}")
    for case_json in sorted(CASES_DIR.rglob("case.json")):
        spec = json.loads(case_json.read_text(encoding="utf-8"))
        config_path = case_json.parent / "config.json"
        if not config_path.is_file():
            raise CaseError(f"{case_json.parent} has a case.json but no config.json")
        case = Case(
            id=spec.get("id") or case_json.parent.name,
            dir=case_json.parent,
            spec=spec,
            config=json.loads(config_path.read_text(encoding="utf-8")),
        )
        if case_filter and case.id not in case_filter:
            continue
        if areas and case.area not in areas:
            continue
        if tiers and case.tier not in tiers:
            continue
        cases.append(case)
    return cases


@dataclass
class CaseRun:
    case: Case
    mode: str
    verdict: str = PASS
    duration: float = 0.0
    records: list[dict] = field(default_factory=list)
    assertions: list[asserts.Result] = field(default_factory=list)
    metrics_rows: list[dict] = field(default_factory=list)
    error: str | None = None
    skip_reason: str | None = None
    repro: str = ""
    workdir: Path | None = None
    exit_code: int | None = None

    def as_dict(self) -> dict:
        d = {
            "id": self.case.id,
            "title": self.case.title,
            "area": self.case.area,
            "tier": self.case.tier,
            "mode": self.mode,
            "intent": self.case.spec.get("intent"),
            "pins": self.case.spec.get("pins", []),
            "verdict": self.verdict,
            "durationSeconds": round(self.duration, 3),
            "recordCount": len(self.records),
            "assertions": [a.as_dict() for a in self.assertions],
            "repro": self.repro,
            "exitCode": self.exit_code,
        }
        if self.metrics_rows:
            d["metrics"] = self.metrics_rows
        if self.error:
            d["error"] = self.error
        if self.skip_reason:
            d["skipReason"] = self.skip_reason
        if self.case.spec.get("knownDefect"):
            d["knownDefect"] = self.case.spec["knownDefect"]
        if self.workdir:
            d["artifacts"] = str(self.workdir)
        return d


def _assertions_for(case: Case, known_defect_policy: str) -> list[dict]:
    """The assertion list, with the known-defect expectation folded in.

    A case that guards an unfixed bug carries both expectations. By default the runner asserts
    ``assertCurrent``, so the suite is green and the bug is *pinned* - if someone fixes it, the case goes
    red and the report says so, which is what turns each defect into a tracked item rather than a
    forgotten note. ``--known-defects assert-correct`` flips to the correct expectation, which is how the
    suite proves its defect cases actually discriminate.
    """
    base = list(case.spec.get("assert", []))
    defect = case.spec.get("knownDefect")
    if not defect:
        return base
    key = "assertCurrent" if known_defect_policy == "assert-current" else "assertCorrect"
    extra = defect.get(key)
    if extra is None:
        raise CaseError(f"case {case.id} knownDefect is missing {key!r}")
    return base + (extra if isinstance(extra, list) else [extra])


def run_case(
    case: Case,
    mode: str,
    arts: artifacts_mod.Artifacts,
    out_root: Path,
    known_defect_policy: str,
) -> CaseRun:
    run = CaseRun(case=case, mode=mode)
    started = time.monotonic()

    workdir = out_root / "cases" / f"{case.id}.{mode}"
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    run.workdir = workdir

    # The file target validates that Directory already exists (FileTargetConfiguration.kt:100), so it
    # is created before SFC starts rather than by SFC.
    sink_dir = workdir / "sink"
    sink_dir.mkdir()
    metrics_path = workdir / "metrics.jsonl"

    # These are the placeholders a case configuration refers to. SFC substitutes them itself and
    # ConfigReader ERRORS on an unresolved one, so a typo in a config surfaces as a loud startup
    # failure rather than as a case that quietly wrote nowhere.
    env = {
        "SFC_E2E_SINK": str(sink_dir),
        "SFC_E2E_METRICS": str(metrics_path),
        "SFC_E2E_CASE": case.id,
    }
    env.update({k: str(v) for k, v in (case.spec.get("env") or {}).items()})
    # Anything the AWS tier published (queue URLs, bucket names) arrives through the real environment.
    for key, value in os.environ.items():
        if key.startswith("SFC_E2E_") and key not in env:
            env[key] = value

    processes: list[sfcproc.RunningProcess] = []
    try:
        plan = modes_mod.build_plan(
            mode=mode,
            base_config=case.config,
            artifacts=arts,
            case_dir=workdir,
            env=env,
            ipc_local_targets=set(case.spec.get("ipcLocalTargets") or []),
        )
        assert plan.main is not None
        run.repro = " ".join(plan.main.argv)

        timeout = float(case.spec.get("timeoutSeconds", 60))

        for launch in plan.services:
            proc = sfcproc.start(launch)
            processes.append(proc)
            assert launch.ready_port is not None
            # A listening socket, not a log line: the obvious readiness line in sfc-main is emitted
            # before the writer is constructed and therefore proves nothing.
            host = sfcproc.wait_for_port(launch.ready_port, timeout=timeout, proc=proc)
            # Write back the address that actually answered. A service binds
            # InetAddress.getLocalHost(), which may be a LAN address or loopback depending on how the
            # host resolves its own name, so guessing would make IPC mode environment-dependent.
            plan.set_server_host(launch.name, host)
        if plan.services:
            plan.write_config()

        main_proc = sfcproc.start(plan.main)
        processes.append(main_proc)

        expect_startup_failure = bool(case.spec.get("expectStartupFailure"))
        if expect_startup_failure:
            # Negative case: SFC must reject the configuration. ServiceMain calls exitProcess(1) on a
            # configuration error, so waiting for the exit is the assertion.
            try:
                main_proc.popen.wait(timeout=timeout)
            except Exception:
                raise CaseError(
                    f"expected a startup failure but the process was still running after {timeout}s"
                ) from None
            run.exit_code = main_proc.popen.returncode
        else:
            wanted = int(case.spec.get("records", 0))
            if wanted <= 0:
                raise CaseError(f"case {case.id} must declare a positive 'records' count")
            watcher = sink_mod.FileSink(sink_dir)
            # Record-count gating. Nothing sleeps; the case finishes as soon as the pipeline has
            # produced what it promised.
            run.records = watcher.wait_for_records(wanted, timeout=timeout, proc=main_proc)

        # Stop everything before reading logs, so the log files are complete. Buffered target data is
        # NOT expected to appear at this point - sfc-main installs no shutdown hook - which is exactly
        # why the records were awaited above instead.
        for proc in reversed(processes):
            proc.stop()
        if run.exit_code is None:
            run.exit_code = main_proc.popen.returncode

        stdout = main_proc.tail_stdout(100_000)
        stderr = main_proc.tail_stderr(100_000)
        snapshot = metrics_mod.MetricsSnapshot.load(metrics_path)
        run.metrics_rows = snapshot.summary()

        ctx = asserts.Context(
            records=run.records,
            stdout=stdout,
            stderr=stderr,
            exit_code=run.exit_code,
            metrics=snapshot,
        )
        run.assertions = asserts.evaluate(ctx, _assertions_for(case, known_defect_policy))

        # An independent oracle. A target can log an error, count a WriteError, drop a batch and still
        # let the process exit 0 - payload assertions alone would call that a pass.
        if not expect_startup_failure:
            for target, count in snapshot.write_errors().items():
                run.assertions.append(
                    asserts.Result(
                        "noWriteErrors", False,
                        f"target {target!r} reported {count:g} WriteErrors", 0, count,
                    )
                )

        if any(not a.ok for a in run.assertions):
            run.verdict = FAIL

    except Exception as e:  # a harness or startup problem, distinct from a failed assertion
        run.verdict = ERROR
        run.error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=6)}"
        for proc in reversed(processes):
            try:
                proc.stop()
            except Exception:
                pass
    finally:
        run.duration = time.monotonic() - started

    return run


def _parity(runs: list[CaseRun]) -> list[dict]:
    """Compare normalised records for the same case across modes.

    Serials and timestamps are per-run and are normalised away; everything else must match, because the
    simulator is deterministic from process start and every mode ran the same number of records. A
    divergence means a component behaves differently depending on how it was loaded - which is precisely
    the risk the uberjar rework introduced.
    """
    by_case: dict[str, list[CaseRun]] = {}
    for r in runs:
        if r.case.spec.get("modeParity") and r.verdict == PASS:
            by_case.setdefault(r.case.id, []).append(r)

    rules = {"serial": "<UUID>", "isoTimestamps": "<ISO>"}
    out = []
    for case_id, group in sorted(by_case.items()):
        if len(group) < 2:
            continue
        baseline = group[0]
        base_norm = asserts.normalise(baseline.records, rules)
        divergent = []
        for other in group[1:]:
            if asserts.normalise(other.records, rules) != base_norm:
                divergent.append(other.mode)
        out.append({
            "id": case_id,
            "modes": [r.mode for r in group],
            "identical": not divergent,
            "detail": (
                f"identical across {len(group)} modes"
                if not divergent
                else f"{baseline.mode} differs from {', '.join(divergent)}"
            ),
        })
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the SFC end-to-end suite")
    ap.add_argument("--tier", default="core", help="comma-separated: core,aws (default core)")
    ap.add_argument("--mode", help="a single deployment mode")
    ap.add_argument("--modes", help=f"comma-separated subset of {','.join(modes_mod.MODES)}")
    ap.add_argument("--case", action="append", help="run only this case id (repeatable)")
    ap.add_argument("--area", help="comma-separated areas")
    ap.add_argument("--out", type=Path, default=E2E_DIR / "out", help="output root")
    ap.add_argument("--parity", action="store_true", help="compare output across modes")
    ap.add_argument("--known-defects", choices=("assert-current", "assert-correct"),
                    default="assert-current",
                    help="assert-current pins today's buggy behaviour (default); "
                         "assert-correct proves the defect cases actually discriminate")
    ap.add_argument("--keep", action="store_true", help="keep unpacked artifacts between runs")
    ap.add_argument("--list", action="store_true", help="list matching cases and exit")
    args = ap.parse_args(argv)

    if args.mode and args.modes:
        ap.error("use --mode or --modes, not both")
    requested_modes = (
        [args.mode] if args.mode
        else (args.modes.split(",") if args.modes else ["inprocess"])
    )
    for m in requested_modes:
        if m not in modes_mod.MODES:
            ap.error(f"unknown mode {m!r}; expected {','.join(modes_mod.MODES)}")

    tiers = [t.strip() for t in args.tier.split(",") if t.strip()]
    areas = [a.strip() for a in args.area.split(",")] if args.area else None

    cases = discover(args.case, areas, tiers)
    if not cases:
        print("no cases matched", file=sys.stderr)
        return 2

    if args.list:
        for c in cases:
            print(f"{c.id:32} {c.area:16} {c.tier:6} {','.join(c.modes(requested_modes)) or '-'}")
        return 0

    run_id = f"e2e-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    out_root = args.out / run_id
    out_root.mkdir(parents=True, exist_ok=True)

    # Every module any selected case needs, in any selected mode, unpacked once.
    needed: set[str] = set()
    for case in cases:
        for mode in case.modes(requested_modes):
            needed.update(modes_mod.required_modules(case.config, mode))

    print(f"[e2e] run {run_id}")
    print(f"[e2e] {len(cases)} case(s) x {len(requested_modes)} mode(s): {', '.join(requested_modes)}")
    print(f"[e2e] unpacking {len(needed)} module tarball(s){' plus the uberjar' if needed else ''} ...")
    arts = artifacts_mod.prepare(
        sorted(needed), workdir=args.out / "artifacts", clean=not args.keep
    )

    runs: list[CaseRun] = []
    started = time.monotonic()
    for case in cases:
        case_modes = case.modes(requested_modes)
        if not case_modes:
            run = CaseRun(case=case, mode=requested_modes[0], verdict=SKIP,
                          skip_reason=f"case supports only {case.spec.get('modes')}")
            runs.append(run)
            print(f"  {report._MARK[SKIP]} {case.id:34} {run.skip_reason}")
            continue
        for mode in case_modes:
            result = run_case(case, mode, arts, out_root, args.known_defects)
            runs.append(result)
            mark = report._MARK[result.verdict]
            print(f"  {mark} {case.id:34} {mode:10} {result.duration:5.1f}s"
                  + (f"  {result.error.splitlines()[0]}" if result.error else ""))

    duration = time.monotonic() - started

    results = {
        "run": {
            "runId": run_id,
            "durationSeconds": round(duration, 2),
            "modes": requested_modes,
            "tiers": tiers,
            "uberjar": arts.uberjar.name,
            "uberjarSha256": _sha256(arts.uberjar),
            "sfcVersion": arts.uberjar.name.replace("sfc-uberjar-", "").replace(".jar", ""),
            # Provenance without running git: CI passes these in, and a local run simply reports
            # "local". The suite must work in a source archive that has no .git at all.
            "commit": os.environ.get("SFC_E2E_COMMIT", "local"),
            "ref": os.environ.get("SFC_E2E_REF", "local"),
            "dirty": os.environ.get("SFC_E2E_DIRTY") == "1",
            "knownDefectPolicy": args.known_defects,
            "environment": {
                "python": sys.version.split()[0],
                "platform": sys.platform,
                "buildId": os.environ.get("CODEBUILD_BUILD_ID", "-"),
                "computeType": os.environ.get("CODEBUILD_BUILD_NUMBER", "-"),
            },
        },
        "cases": [r.as_dict() for r in runs],
    }
    if args.parity:
        results["modeParity"] = _parity(runs)

    paths = report.write_all(results, out_root)

    failed = sum(1 for r in runs if r.verdict in (FAIL, ERROR))
    passed = sum(1 for r in runs if r.verdict == PASS)
    skipped = sum(1 for r in runs if r.verdict == SKIP)
    print()
    print(f"[e2e] {passed} passed, {failed} failed, {skipped} skipped in {duration:.1f}s")
    print(f"[e2e] report  {paths['markdown']}")
    print(f"[e2e] results {paths['results']}")
    print(f"[e2e] junit   {paths['junit']}")

    if args.parity and results.get("modeParity"):
        bad = [p for p in results["modeParity"] if not p["identical"]]
        print(f"[e2e] parity  {len(results['modeParity']) - len(bad)}/{len(results['modeParity'])} identical")
        if bad:
            failed += len(bad)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
