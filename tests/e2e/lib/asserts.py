# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""The assertion vocabulary a case can use.

Assertions are declarative so that adding a case is data, not code. Every kind returns a structured
result carrying both expected and observed values, because that pair is what the markdown report renders
on failure - an assertion that only reports "false" costs more time than it saves.

Two rules are baked in deliberately:

* **No assertion may depend on wall-clock duration.** Values come from record count, which the runner
  controls exactly (see ``sink.py``).
* **Ordering is only asserted where the transport guarantees it.** The file sink preserves pipeline
  order, so ``channel_sequence`` is valid there. Over SQS or SNS->SQS nothing is ordered, so those cases
  use ``channel_value_run``, which checks the *set* of values forms a contiguous run instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

#: Matches an ISO-8601 instant as SFC renders it, for normalisation before deep comparison.
ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class AssertError(RuntimeError):
    """A malformed assertion - a bug in the case, not a test failure."""


@dataclass
class Result:
    kind: str
    ok: bool
    detail: str = ""
    expected: Any = None
    actual: Any = None
    #: Set when the assertion could not be evaluated at all (missing path, empty input).
    invalid: bool = False

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "ok": self.ok,
            "detail": self.detail,
            "expected": self.expected,
            "actual": self.actual,
            "invalid": self.invalid,
        }


@dataclass
class Context:
    """Everything an assertion can look at."""

    records: list[dict]
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    metrics: Any = None  # MetricsSnapshot, avoided as an import to keep this module standalone
    files: list[Any] = field(default_factory=list)


_MISSING = object()


def select(obj: Any, path: str) -> Any:
    """Resolve a dotted path, with ``[n]`` for list indices.

    Returns the sentinel ``_MISSING`` rather than raising, so a missing path is reported as a failed
    assertion with a useful message instead of a harness traceback.
    """
    current = obj
    for raw in path.split("."):
        if not raw:
            continue
        key, *indices = re.split(r"\[(\d+)\]", raw)[:1] + re.findall(r"\[(\d+)\]", raw)
        if key:
            if not isinstance(current, dict) or key not in current:
                return _MISSING
            current = current[key]
        for idx in indices:
            i = int(idx)
            if not isinstance(current, list) or i >= len(current):
                return _MISSING
            current = current[i]
    return current


def normalise(value: Any, rules: dict | None) -> Any:
    """Replace volatile values so a golden comparison is stable.

    ``{"serial": "<UUID>", "isoTimestamps": "<ISO>"}`` is the usual pair: every record carries a fresh
    serial and fresh timestamps, and those are asserted separately by relationship rather than by value.
    """
    rules = rules or {}
    uuid_token = rules.get("serial")
    iso_token = rules.get("isoTimestamps")

    def walk(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str):
            if uuid_token and UUID_RE.fullmatch(v):
                return uuid_token
            if iso_token and ISO_RE.fullmatch(v):
                return iso_token
            if iso_token:
                return ISO_RE.sub(iso_token, v)
        return v

    return walk(value)


def _channel_values(records: list[dict], source: str, channel: str, element: str = "value") -> list[Any]:
    """Pull one channel's values out of every record, in record order.

    ``element`` is configurable because ``ElementNames`` can rename ``value``, and because a case that
    sets ``TimestampLevel`` to ``Channel`` or ``Both`` wraps the value in an object while ``None`` does
    not - a difference several cases exist specifically to pin.
    """
    out: list[Any] = []
    for rec in records:
        holder = select(rec, f"sources.{source}.values.{channel}")
        if holder is _MISSING:
            out.append(_MISSING)
        elif isinstance(holder, dict) and element in holder:
            out.append(holder[element])
        else:
            out.append(holder)
    return out


# --------------------------------------------------------------------------------------- assertions

def a_record_count(ctx: Context, spec: dict) -> Result:
    n = len(ctx.records)
    if "equals" in spec:
        want = int(spec["equals"])
        return Result("recordCount", n == want, f"{n} record(s)", want, n)
    lo = int(spec.get("min", 0))
    hi = spec.get("max")
    hi = int(hi) if hi is not None else None
    ok = n >= lo and (hi is None or n <= hi)
    return Result("recordCount", ok, f"{n} record(s)", {"min": lo, "max": hi}, n)


def a_every_record(ctx: Context, spec: dict) -> Result:
    """Every record must have ``path`` equal to ``equals`` (or merely present)."""
    path = spec["path"]
    if not ctx.records:
        return Result("everyRecord", False, "no records to check", spec.get("equals"), None, invalid=True)
    seen = [select(r, path) for r in ctx.records]
    if "equals" in spec:
        want = spec["equals"]
        bad = [i for i, v in enumerate(seen) if v != want]
        return Result(
            "everyRecord",
            not bad,
            f"{path} differed in record(s) {bad[:5]}" if bad else f"{path} == {want!r} in all {len(seen)}",
            want,
            [seen[i] for i in bad[:5]] if bad else want,
        )
    missing = [i for i, v in enumerate(seen) if v is _MISSING]
    return Result(
        "everyRecord",
        not missing,
        f"{path} missing from record(s) {missing[:5]}" if missing else f"{path} present in all {len(seen)}",
        f"{path} present",
        f"missing in {len(missing)}" if missing else "present",
    )


def a_keys_absent(ctx: Context, spec: dict) -> Result:
    """No record may contain any of ``paths`` - used for TimestampLevel and ElementNames contracts."""
    paths = spec["paths"]
    offenders = {p: i for p in paths for i, r in enumerate(ctx.records) if select(r, p) is not _MISSING}
    return Result(
        "keysAbsent",
        not offenders,
        f"unexpectedly present: {sorted(offenders)}" if offenders else f"absent: {paths}",
        {"absent": paths},
        sorted(offenders) or "none present",
    )


def a_channel_sequence(ctx: Context, spec: dict) -> Result:
    """A channel's values across records must be a contiguous run with the given step.

    Valid only for order-preserving sinks. The file sink qualifies; a queue does not.
    """
    source, channel = spec["source"], spec["channel"]
    step = spec.get("step", 1)
    element = spec.get("element", "value")
    values = _channel_values(ctx.records, source, channel, element)
    if any(v is _MISSING for v in values):
        return Result("channelSequence", False, f"{source}.{channel} missing from some records",
                      f"step {step}", "missing", invalid=True)
    if len(values) < 2:
        return Result("channelSequence", False, "need at least 2 records", f"step {step}", values, invalid=True)
    try:
        nums = [float(v) for v in values]
    except (TypeError, ValueError):
        return Result("channelSequence", False, f"{source}.{channel} is not numeric",
                      f"step {step}", values[:5], invalid=True)
    deltas = [round(b - a, 9) for a, b in zip(nums, nums[1:])]
    bad = [i for i, d in enumerate(deltas) if d != step]
    return Result(
        "channelSequence",
        not bad,
        f"delta != {step} at index {bad[:5]}" if bad else f"{len(nums)} values step by {step}",
        f"all deltas == {step}",
        [deltas[i] for i in bad[:5]] if bad else f"all {step}",
    )


def a_channel_value_run(ctx: Context, spec: dict) -> Result:
    """The *set* of a channel's values is a contiguous run - order-insensitive.

    This is the queue-safe form of ``channelSequence``: standard SQS gives best-effort ordering and
    SNS->SQS gives none, so asserting arrival-order deltas there would be flaky by construction.
    """
    source, channel = spec["source"], spec["channel"]
    element = spec.get("element", "value")
    values = [v for v in _channel_values(ctx.records, source, channel, element) if v is not _MISSING]
    if not values:
        return Result("channelValueRun", False, f"no values for {source}.{channel}", "a contiguous run",
                      None, invalid=True)
    try:
        nums = sorted({int(float(v)) for v in values})
    except (TypeError, ValueError):
        return Result("channelValueRun", False, "not numeric", "a contiguous run", values[:5], invalid=True)
    contiguous = len(nums) == (nums[-1] - nums[0] + 1)
    duplicates = len(values) != len(set(map(lambda v: int(float(v)), values)))
    ok = contiguous and not duplicates
    detail = "contiguous, no duplicates" if ok else (
        f"gaps in {nums[0]}..{nums[-1]} ({len(nums)} distinct)" if not contiguous else "duplicate values"
    )
    return Result("channelValueRun", ok, detail, "contiguous run, no duplicates",
                  {"min": nums[0], "max": nums[-1], "distinct": len(nums), "seen": len(values)})


def _matches(got: Any, want: Any, tolerance: float | None) -> bool:
    """Equality, with an optional absolute tolerance for floats.

    A tolerance exists because several cases assert the result of a transcendental function, and pinning
    those to the last bit of a double is asking for a failure the first time the JVM, the platform or the
    optimiser rounds differently. Exact comparison remains the default, so structural and integer
    assertions stay strict.
    """
    if tolerance is None:
        return got == want
    try:
        return abs(float(got) - float(want)) <= tolerance
    except (TypeError, ValueError):
        return got == want


def a_channel_value_set(ctx: Context, spec: dict) -> Result:
    """The distinct values of a channel must equal exactly ``values``.

    Only safe when the observation window provably spans a full cycle of the simulation. ``Square`` is a
    function of wall clock (``inCycle = (elapsed % CycleLength) / CycleLength``), so a short window can
    legitimately observe only one of its two levels - use ``channelValueIn`` there instead.

    ``tolerance`` compares numerically within an absolute epsilon instead of exactly.
    """
    source, channel = spec["source"], spec["channel"]
    want = list(spec["values"])
    tolerance = spec.get("tolerance")
    got_raw = [v for v in _channel_values(ctx.records, source, channel, spec.get("element", "value"))
               if v is not _MISSING]
    got = list(dict.fromkeys(got_raw))  # distinct, order preserved

    if tolerance is None:
        ok = set(got) == set(want)
    else:
        ok = len(got) == len(want) and all(
            any(_matches(g, w, tolerance) for w in want) for g in got
        ) and all(any(_matches(g, w, tolerance) for g in got) for w in want)

    return Result("channelValueSet", ok,
                  f"distinct values {sorted(got, key=str)}"
                  + (f" (tolerance {tolerance})" if tolerance is not None else ""),
                  sorted(want, key=str), sorted(got, key=str))


def a_channel_value_in(ctx: Context, spec: dict) -> Result:
    """Every observed value of a channel must be a member of ``values``."""
    source, channel = spec["source"], spec["channel"]
    allowed = set(spec["values"])
    got = [v for v in _channel_values(ctx.records, source, channel, spec.get("element", "value"))
           if v is not _MISSING]
    if not got:
        return Result("channelValueIn", False, f"no values for {source}.{channel}", sorted(allowed, key=str),
                      None, invalid=True)
    bad = [v for v in got if v not in allowed]
    return Result("channelValueIn", not bad,
                  f"{len(bad)} value(s) outside the allowed set" if bad else f"all {len(got)} values allowed",
                  sorted(allowed, key=str), sorted(set(bad), key=str) if bad else "all allowed")


def a_channel_numeric_range(ctx: Context, spec: dict) -> Result:
    """Every value of a channel must lie within [min, max].

    This is the assertion that pins the ``minValueForType`` clamp fix: before it, a ``"Min": 0``
    simulation emitted ``4.9E-324`` (Double.MIN_VALUE, the smallest *positive* denormal) instead of 0,
    which a bare "is it a number" check would happily accept.
    """
    source, channel = spec["source"], spec["channel"]
    lo, hi = float(spec["min"]), float(spec["max"])
    got = [v for v in _channel_values(ctx.records, source, channel, spec.get("element", "value"))
           if v is not _MISSING]
    if not got:
        return Result("channelNumericRange", False, "no values", [lo, hi], None, invalid=True)
    try:
        nums = [float(v) for v in got]
    except (TypeError, ValueError):
        return Result("channelNumericRange", False, "not numeric", [lo, hi], got[:5], invalid=True)
    bad = [v for v in nums if v < lo or v > hi]
    return Result("channelNumericRange", not bad,
                  f"{len(bad)} value(s) outside [{lo}, {hi}]" if bad else f"all {len(nums)} within [{lo}, {hi}]",
                  [lo, hi], {"min": min(nums), "max": max(nums), "outside": bad[:5]})


def a_deep_equals(ctx: Context, spec: dict) -> Result:
    """A record, after normalisation, must deep-equal ``value``.

    ``index`` defaults to 0. Used for the output-shape contracts - ElementNames, TimestampLevel,
    aggregation framing - where the whole point is that the structure has not silently changed.
    """
    index = int(spec.get("index", 0))
    if index >= len(ctx.records):
        return Result("deepEquals", False, f"no record at index {index}", spec["value"], None, invalid=True)
    got = normalise(ctx.records[index], spec.get("normalise"))
    want = spec["value"]
    if "path" in spec:
        got = select(got, spec["path"])
        if got is _MISSING:
            return Result("deepEquals", False, f"{spec['path']} missing", want, None, invalid=True)
    return Result("deepEquals", got == want, "deep equality", want, got)


def a_log_contains(ctx: Context, spec: dict) -> Result:
    """A string must appear in the process output.

    ``stream`` may be ``stdout`` (SFC's own logging - ConsoleLogWriter writes straight to System.out),
    ``stderr`` (JVM-level failures) or ``both``. Default is ``both``, because an oracle pointed at only
    one stream misses exactly the class of failure it was built for.
    """
    needle = spec["text"]
    stream = spec.get("stream", "both")
    haystack = {"stdout": ctx.stdout, "stderr": ctx.stderr}.get(stream, ctx.stdout + ctx.stderr)
    found = needle in haystack
    return Result("logContains", found, f"{needle!r} {'found' if found else 'not found'} in {stream}",
                  needle, "present" if found else "absent")


def a_log_absent(ctx: Context, spec: dict) -> Result:
    """No string in ``texts`` may appear in the output.

    Two uses. The security one: a secret from the configuration must never be printed, which SFC's
    logger is supposed to blank. The correctness one: a denylist of failure signatures -
    ``NoClassDefFoundError``, ``ClassNotFoundException``, ``NoSuchMethodError`` - that are the exact
    fingerprint of a dependency version split and that otherwise leave the process exiting 0.
    """
    stream = spec.get("stream", "both")
    haystack = {"stdout": ctx.stdout, "stderr": ctx.stderr}.get(stream, ctx.stdout + ctx.stderr)
    hits = [t for t in spec["texts"] if t in haystack]
    return Result("logAbsent", not hits,
                  f"found forbidden text: {hits}" if hits else f"none of {len(spec['texts'])} present",
                  {"absent": spec["texts"]}, hits or "none")


def a_exit_code(ctx: Context, spec: dict) -> Result:
    """Used by the negative cases: a malformed configuration must exit non-zero."""
    if "equals" in spec:
        want = int(spec["equals"])
        return Result("exitCode", ctx.exit_code == want, f"exit {ctx.exit_code}", want, ctx.exit_code)
    want_nonzero = bool(spec.get("nonZero", True))
    ok = (ctx.exit_code not in (0, None)) if want_nonzero else (ctx.exit_code == 0)
    return Result("exitCode", ok, f"exit {ctx.exit_code}",
                  "non-zero" if want_nonzero else 0, ctx.exit_code)


def a_metric(ctx: Context, spec: dict) -> Result:
    """Compare a metric total against a value.

    ``op`` is one of ``eq``, ``ne``, ``gt``, ``ge``, ``lt``, ``le``.
    """
    if ctx.metrics is None or ctx.metrics.is_empty():
        return Result("metric", False, "no metrics were recorded", spec, None, invalid=True)
    source, name = spec["source"], spec["name"]
    op = spec.get("op", "ge")
    want = float(spec["value"])
    got = ctx.metrics.total(source, name)
    ops: dict[str, Callable[[float, float], bool]] = {
        "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
        "gt": lambda a, b: a > b, "ge": lambda a, b: a >= b,
        "lt": lambda a, b: a < b, "le": lambda a, b: a <= b,
    }
    if op not in ops:
        raise AssertError(f"unknown metric op {op!r}")
    return Result("metric", ops[op](got, want), f"{source}.{name} {got} {op} {want}",
                  f"{op} {want}", got)


KINDS: dict[str, Callable[[Context, dict], Result]] = {
    "recordCount": a_record_count,
    "everyRecord": a_every_record,
    "keysAbsent": a_keys_absent,
    "channelSequence": a_channel_sequence,
    "channelValueRun": a_channel_value_run,
    "channelValueSet": a_channel_value_set,
    "channelValueIn": a_channel_value_in,
    "channelNumericRange": a_channel_numeric_range,
    "deepEquals": a_deep_equals,
    "logContains": a_log_contains,
    "logAbsent": a_log_absent,
    "exitCode": a_exit_code,
    "metric": a_metric,
}


def evaluate(ctx: Context, specs: list[dict]) -> list[Result]:
    results = []
    for spec in specs:
        kind = spec.get("kind")
        fn = KINDS.get(kind)
        if fn is None:
            raise AssertError(f"unknown assertion kind {kind!r}; known: {sorted(KINDS)}")
        try:
            results.append(fn(ctx, spec))
        except AssertError:
            raise
        except KeyError as e:
            raise AssertError(f"assertion {kind!r} is missing required field {e}") from None
    return results
