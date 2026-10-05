# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Timeline steps: what a case does to the world while SFC runs.

Most cases need none - they start, wait for N records and stop. The ones that test behaviour *under change*
need a timeline: stop the broker store-forward is forwarding to, wait until records are buffered, start it
again, wait until the buffer drains. Each step either waits for an observable condition or acts::

    "steps": [
      {"wait": {"sink": "main", "records": 5}},
      {"do": "gate-close", "service": "gate"},
      {"wait": {"files": {"dir": "buffer", "min": 3}}},
      {"do": "gate-open", "service": "gate"},
      {"wait": {"sink": "main", "records": 12}}
    ]

Actions: ``start``/``stop``/``restart`` a service, ``gate-close``/``gate-open`` a tcpgate,
``sigterm``/``sigkill`` a process, ``restart-sfc``, ``mark`` (snapshot sink counts for ``markDelta``),
``update-config`` (merge-patch the running configuration - live reload), ``write-file`` and ``run`` (a
command to completion; ``${COUNTERPARTS}`` and ``${SFC_E2E_...}`` expand, ``python`` is the harness
interpreter).

``{"wait": {"any": [<wait>, <wait>]}}`` waits for the first of several conditions.

Waits are on *conditions*, never on durations: ``{"seconds": n}`` exists only as a settle step and a case
using it must say why in a ``comment``. Every wait has a timeout (the case's ``timeoutSeconds`` unless the
step sets its own) and fails the case with what it was waiting for.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import metrics as metrics_mod
from .counterpart_paths import COUNTERPARTS


class StepError(RuntimeError):
    pass


def _until(pred, timeout: float, what: str, unit, poll: float = 0.2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = pred()
        if value:
            return value
        line = unit.fatal()
        if line:
            raise StepError(f"waiting for {what}, but none can follow - {line}")
        for proc in unit.sfc_processes():
            if proc.poll() is not None and not unit.expect_exit:
                raise StepError(f"{proc.name} exited with {proc.popen.returncode} while waiting for {what}\n"
                                f"--- stderr ---\n{proc.tail_stderr()}")
        time.sleep(poll)
    raise StepError(f"timed out after {timeout}s waiting for {what}")


def _condition(unit, spec: dict):
    """(predicate, description) for one wait condition; the predicate never blocks."""
    if "sink" in spec:
        sink, n, where = unit.sinks[spec["sink"]], int(spec["records"]), spec.get("where")
        if where:
            from .asserts import select

            def matching():
                return sum(1 for r in sink.records() if all(select(r, k) == v for k, v in where.items()))

            return (lambda: matching() >= n), f"{n} record(s) matching {where} in sink {spec['sink']!r}"
        return (lambda: sink.count() >= n), f"{n} record(s) in sink {spec['sink']!r}"
    if "files" in spec:
        f = spec["files"]
        directory, n = unit.dir_path(f["dir"]), int(f.get("min", 1))
        return (lambda: sum(1 for p in Path(directory).rglob("*") if p.is_file()) >= n), f">= {n} file(s) in {f['dir']!r}"
    if "log" in spec:
        text, count, process = spec["log"], int(spec.get("count", 1)), spec.get("process", "*")
        return (lambda: unit.log_text(process).count(text) >= count), f"{count}x {text!r} in the {process} log"
    if "metric" in spec:
        m = spec["metric"]
        ops = {"ge": lambda a, b: a >= b, "gt": lambda a, b: a > b, "eq": lambda a, b: a == b}
        op = ops[m.get("op", "ge")]

        def check():
            snap = metrics_mod.MetricsSnapshot.load(unit.metrics_path)
            return op(snap.total(m["source"], m["name"]), float(m["value"]))

        return check, f"metric {m['source']}.{m['name']} {m.get('op', 'ge')} {m['value']}"
    if "exit" in spec:
        proc = unit.process(spec["exit"])
        unit.expect_exit = True
        return (lambda: proc.poll() is not None), f"{spec['exit']} to exit"
    raise StepError(f"unknown wait {spec!r}")


def _wait(unit, spec: dict, timeout: float) -> None:
    if "timeoutSeconds" in spec:  # the default already includes the unit's allowance
        timeout = float(spec["timeoutSeconds"]) + getattr(unit, "allowance", 0.0)
    if "seconds" in spec:
        if not spec.get("comment"):
            raise StepError("a {'seconds': n} wait must carry a 'comment' saying why no condition works")
        time.sleep(float(spec["seconds"]))
        return
    if "any" in spec:
        # The first of several outcomes - for a known-defect pin that waits for either the correct
        # result or the defect's signature, so the same timeline serves assertCurrent and assertCorrect.
        conditions = [_condition(unit, s) for s in spec["any"]]
        _until(lambda: any(pred() for pred, _ in conditions), timeout,
               " or ".join(desc for _, desc in conditions), unit, poll=max(_poll(unit, s) for s in spec["any"]))
        return
    pred, desc = _condition(unit, spec)
    _until(pred, timeout, desc, unit, poll=_poll(unit, spec))


def _poll(unit, spec: dict) -> float:
    """A sink is polled at its own pace: each poll is an AWS call (a full S3 listing, GetRecords quota)."""
    return unit.sinks[spec["sink"]].poll_interval() if "sink" in spec else 0.2


def _expand(value: str, env: dict) -> str:
    out = value.replace("${COUNTERPARTS}", str(COUNTERPARTS))
    for k, v in env.items():
        out = out.replace("${" + k + "}", str(v))
    return out


def _merge(base: dict, patch: dict) -> None:
    """RFC 7386 merge patch: dicts merge, ``null`` deletes, anything else replaces."""
    for k, v in patch.items():
        if v is None:
            base.pop(k, None)
        elif isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def _do(unit, step: dict) -> None:
    action = step["do"]
    if action in ("start", "stop", "restart"):
        svc = unit.services[step["service"]]
        if action in ("stop", "restart"):
            svc.stop()
        if action in ("start", "restart"):
            svc.start(unit.env, timeout=float(step.get("timeoutSeconds", 30)))
    elif action in ("gate-close", "gate-open"):
        svc = unit.services[step["service"]]
        (svc.close if action == "gate-close" else svc.open)()
        time.sleep(0.2)  # let the forwarder act on the signal before the next condition is polled
    elif action in ("sigterm", "sigkill"):
        proc = unit.process(step["process"])
        unit.expect_exit = True
        proc.signal(signal.SIGTERM if action == "sigterm" else signal.SIGKILL)
    elif action == "restart-sfc":
        unit.stop_sfc()
        unit.start_sfc()
    elif action == "mark":
        unit.marks[step["name"]] = {name: s.count() for name, s in unit.sinks.items()}
    elif action == "update-config":
        # Live reload: SFC watches its configuration file. The patch is merged into the configuration
        # as rendered for this mode, so IPC server entries and JarFiles survive the rewrite.
        _merge(unit.plan.config, step["patch"])
        unit.plan.write_config()
    elif action == "write-file":
        path = Path(_expand(step["path"], unit.env))
        path.parent.mkdir(parents=True, exist_ok=True)
        content = step["content"]
        path.write_text(content if isinstance(content, str) else json.dumps(content, indent=2))
    elif action == "run":
        argv = [_expand(a, unit.env) for a in step["argv"]]
        argv = [sys.executable if a == "python" else a for a in argv]
        proc = subprocess.run(argv, cwd=str(unit.workdir), env={**os.environ, **unit.env},
                              capture_output=True, text=True, timeout=float(step.get("timeoutSeconds", 30)))
        if proc.returncode != 0 and not step.get("allowFailure"):
            raise StepError(f"{argv[0]} exited {proc.returncode}: {proc.stderr.strip()[-500:]}")
    else:
        raise StepError(f"unknown action {action!r}")


def run(unit, steps: list[dict], timeout: float) -> None:
    for i, step in enumerate(steps or []):
        try:
            if "wait" in step:
                _wait(unit, step["wait"], timeout)
            elif "do" in step:
                _do(unit, step)
            else:
                raise StepError(f"step {i} has neither 'wait' nor 'do'")
        except StepError as e:
            raise StepError(f"step {i + 1}/{len(steps)} {step}: {e}") from None
