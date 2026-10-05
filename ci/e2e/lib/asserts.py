# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""The assertion vocabulary a case can use.

Assertions are declarative so that adding a case is data, not code. Every kind returns a structured result
carrying expected and observed values, because that pair is what the report renders on failure.

Common options on record-based kinds:

* ``sink``   which sink's records to use (default: the gate's sink, usually ``main``);
* ``where``  ``{"path": value, ...}`` - only records whose values at those paths match;
* ``strictTypes`` on ``everyRecord``/``deepEquals`` - ``1``, ``1.0`` and ``"1"`` are all different.

Rules baked in deliberately:

* **No assertion depends on wall-clock duration.** Values come from record count, which the runner gates.
* **Ordering is asserted only where the transport preserves it.** The file sink does, so
  ``channelSequence`` is valid there. Over SQS or SNS->SQS use ``channelValueRun`` (the *set* of values is
  a contiguous run).
* **Logs mean every SFC process, both streams.** ERROR lines go to stderr (ConsoleLogWriter.kt:12) and IPC
  services write their own files; an oracle that read only sfc-main's stdout missed exactly the failures it
  existed for. ``process`` and ``stream`` narrow it when a case needs to.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

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
    invalid: bool = False

    def as_dict(self) -> dict:
        return {"kind": self.kind, "ok": self.ok, "detail": self.detail, "expected": self.expected,
                "actual": self.actual, "invalid": self.invalid}


@dataclass
class Context:
    records: list
    sinks: dict = field(default_factory=dict)          # name -> records
    logs: dict = field(default_factory=dict)           # process -> (stdout, stderr)
    exit_code: int | None = None
    metrics: Any = None
    workdir: Path | None = None
    marks: dict = field(default_factory=dict)
    env: dict = field(default_factory=dict)
    sink_objects: dict = field(default_factory=dict)   # name -> Sink (for raw/file inspection)

    # Backwards compatible views used by older cases.
    @property
    def stdout(self) -> str:
        return "\n".join(o for o, _ in self.logs.values())

    @property
    def stderr(self) -> str:
        return "\n".join(e for _, e in self.logs.values())


_MISSING = object()


def select(obj: Any, path: str) -> Any:
    """Resolve a dotted path with ``[n]`` indices. ``pathList`` style keys containing dots can be given
    as a list instead of a string."""
    parts = path if isinstance(path, list) else _split(path)
    current = obj
    for part in parts:
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                return _MISSING
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                return _MISSING
            current = current[part]
    return current


def _split(path: str) -> list:
    out: list = []
    for raw in path.split("."):
        if not raw:
            continue
        m = re.match(r"^([^\[]*)((?:\[\d+\])*)$", raw)
        if not m:
            out.append(raw)
            continue
        if m.group(1):
            out.append(m.group(1))
        out.extend(int(i) for i in re.findall(r"\[(\d+)\]", m.group(2)))
    return out


def typed(value: Any) -> Any:
    if isinstance(value, bool):
        return ("b", value)
    if isinstance(value, int):
        return ("i", value)
    if isinstance(value, float):
        return ("f", value)
    if isinstance(value, dict):
        return ("o", tuple(sorted((k, typed(v)) for k, v in value.items())))
    if isinstance(value, list):
        return ("a", tuple(typed(v) for v in value))
    return ("s", value)


def normalise(value: Any, rules: dict | None) -> Any:
    rules = rules or {}
    uuid_token, iso_token = rules.get("serial"), rules.get("isoTimestamps")

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


def _records(ctx: Context, spec: dict) -> list:
    recs = ctx.sinks.get(spec["sink"], []) if "sink" in spec else ctx.records
    where = spec.get("where")
    if where:
        recs = [r for r in recs if all(select(r, p) == v for p, v in where.items())]
    return recs


def _logs(ctx: Context, spec: dict) -> str:
    process = spec.get("process", "*")
    stream = spec.get("stream", "both")
    parts = []
    for name, (out, err) in ctx.logs.items():
        if process != "*" and not (name == process or (process.endswith("*") and name.startswith(process[:-1]))):
            continue
        if stream in ("both", "stdout"):
            parts.append(out)
        if stream in ("both", "stderr"):
            parts.append(err)
    return "\n".join(parts)


def _channel_values(records: list, source: str, channel: str, element: str = "value") -> list:
    out: list = []
    for rec in records:
        holder = select(rec, ["sources", source, "values", channel])
        if holder is _MISSING:
            out.append(_MISSING)
        elif isinstance(holder, dict) and element in holder:
            out.append(holder[element])
        else:
            out.append(holder)
    return out


def _bounds(n: float, spec: dict) -> tuple[bool, Any]:
    if "equals" in spec:
        return n == spec["equals"], spec["equals"]
    lo, hi = spec.get("min"), spec.get("max")
    ok = (lo is None or n >= lo) and (hi is None or n <= hi)
    return ok, {"min": lo, "max": hi}


# ------------------------------------------------------------------------------------------- records

def a_record_count(ctx, spec):
    recs = _records(ctx, spec)
    ok, want = _bounds(len(recs), spec)
    return Result("recordCount", ok, f"{len(recs)} record(s)", want, len(recs))


def a_every_record(ctx, spec):
    path = spec["path"]
    recs = _records(ctx, spec)
    if not recs:
        return Result("everyRecord", False, "no records to check", spec.get("equals"), None, invalid=True)
    seen = [select(r, path) for r in recs]
    if "equals" in spec or "in" in spec:
        strict = spec.get("strictTypes")
        allowed = [spec["equals"]] if "equals" in spec else list(spec["in"])
        key = typed if strict else (lambda x: x)
        allowed_keys = [key(a) for a in allowed]
        bad = [i for i, v in enumerate(seen) if v is _MISSING or key(v) not in allowed_keys]
        return Result("everyRecord", not bad,
                      f"{path} differed in record(s) {bad[:5]}" if bad else f"{path} ok in all {len(seen)}",
                      allowed[0] if "equals" in spec else allowed,
                      [None if seen[i] is _MISSING else seen[i] for i in bad[:5]] or "all match")
    if "regex" in spec:
        rx = re.compile(spec["regex"])
        bad = [i for i, v in enumerate(seen) if not (isinstance(v, str) and rx.fullmatch(v))]
        return Result("everyRecord", not bad, f"{path} regex", spec["regex"],
                      [None if seen[i] is _MISSING else seen[i] for i in bad[:5]] or "all match")
    if "type" in spec:
        types = {"int": int, "float": float, "str": str, "bool": bool, "list": list, "dict": dict}
        want = types[spec["type"]]
        bad = [i for i, v in enumerate(seen)
               if v is _MISSING or not isinstance(v, want) or (want is int and isinstance(v, bool))]
        return Result("everyRecord", not bad, f"{path} type {spec['type']}", spec["type"],
                      [type(seen[i]).__name__ for i in bad[:5]] or "all match")
    missing = [i for i, v in enumerate(seen) if v is _MISSING]
    return Result("everyRecord", not missing,
                  f"{path} missing from record(s) {missing[:5]}" if missing else f"{path} present in all {len(seen)}",
                  "present", f"missing in {len(missing)}" if missing else "present")


def a_keys_absent(ctx, spec):
    recs = _records(ctx, spec)
    offenders = sorted({p for p in spec["paths"] for r in recs if select(r, p) is not _MISSING})
    return Result("keysAbsent", not offenders,
                  f"unexpectedly present: {offenders}" if offenders else f"absent: {spec['paths']}",
                  {"absent": spec["paths"]}, offenders or "none present")


def a_key_order(ctx, spec):
    """Every record's object at ``path`` (root when empty) has exactly ``keys``, in that order."""
    recs = _records(ctx, spec)
    want = list(spec["keys"])
    path = spec.get("path", "")
    bad = []
    for i, r in enumerate(recs):
        node = select(r, path) if path else r
        if not isinstance(node, dict) or list(node.keys()) != want:
            bad.append((i, list(node.keys()) if isinstance(node, dict) else node))
    if not recs:
        return Result("keyOrder", False, "no records", want, None, invalid=True)
    return Result("keyOrder", not bad, f"{len(bad)} record(s) differ" if bad else f"order ok in {len(recs)}",
                  want, bad[0][1] if bad else want)


def a_key_set(ctx, spec):
    recs = _records(ctx, spec)
    want = set(spec["keys"])
    path = spec.get("path", "")
    bad = []
    for r in recs:
        node = select(r, path) if path else r
        if not isinstance(node, dict) or set(node.keys()) != want:
            bad.append(sorted(node.keys()) if isinstance(node, dict) else node)
    if not recs:
        return Result("keySet", False, "no records", sorted(want), None, invalid=True)
    return Result("keySet", not bad, f"{len(bad)} record(s) differ" if bad else "key set ok",
                  sorted(want), bad[0] if bad else sorted(want))


def a_channel_sequence(ctx, spec):
    source, channel, step = spec["source"], spec["channel"], spec.get("step", 1)
    values = _channel_values(_records(ctx, spec), source, channel, spec.get("element", "value"))
    if spec.get("skipMissing"):
        values = [v for v in values if v is not _MISSING]
    if any(v is _MISSING for v in values):
        return Result("channelSequence", False, f"{source}.{channel} missing from some records", f"step {step}",
                      "missing", invalid=True)
    if len(values) < 2:
        return Result("channelSequence", False, "need at least 2 records", f"step {step}", values, invalid=True)
    try:
        nums = [float(v) for v in values]
    except (TypeError, ValueError):
        return Result("channelSequence", False, "not numeric", f"step {step}", values[:5], invalid=True)
    deltas = [round(b - a, 9) for a, b in zip(nums, nums[1:])]
    bad = [i for i, d in enumerate(deltas) if d != step]
    return Result("channelSequence", not bad,
                  f"delta != {step} at index {bad[:5]}" if bad else f"{len(nums)} values step by {step}",
                  f"all deltas == {step}", [deltas[i] for i in bad[:5]] if bad else f"all {step}")


def a_channel_value_run(ctx, spec):
    source, channel = spec["source"], spec["channel"]
    values = [v for v in _channel_values(_records(ctx, spec), source, channel, spec.get("element", "value"))
              if v is not _MISSING]
    if not values:
        return Result("channelValueRun", False, f"no values for {source}.{channel}", "a contiguous run", None, invalid=True)
    try:
        ints = [int(float(v)) for v in values]
    except (TypeError, ValueError):
        return Result("channelValueRun", False, "not numeric", "a contiguous run", values[:5], invalid=True)
    nums = sorted(set(ints))
    contiguous = len(nums) == nums[-1] - nums[0] + 1
    dupes = len(ints) != len(set(ints))
    ok = contiguous and (not dupes or spec.get("allowDuplicates"))
    return Result("channelValueRun", ok,
                  "contiguous" if ok else ("duplicates" if contiguous else f"gaps in {nums[0]}..{nums[-1]}"),
                  "contiguous run, no duplicates",
                  {"min": nums[0], "max": nums[-1], "distinct": len(nums), "seen": len(values)})


def _matches(got, want, tolerance):
    if tolerance is None:
        return got == want
    try:
        return abs(float(got) - float(want)) <= tolerance
    except (TypeError, ValueError):
        return got == want


def a_channel_value_set(ctx, spec):
    source, channel = spec["source"], spec["channel"]
    want, tol = list(spec["values"]), spec.get("tolerance")
    got = list(dict.fromkeys(v for v in _channel_values(_records(ctx, spec), source, channel,
                                                        spec.get("element", "value")) if v is not _MISSING))
    if tol is None:
        ok = set(map(repr, got)) == set(map(repr, want)) if spec.get("strictTypes") else set(got) == set(want)
    else:
        ok = len(got) == len(want) and all(any(_matches(g, w, tol) for w in want) for g in got) \
            and all(any(_matches(g, w, tol) for g in got) for w in want)
    return Result("channelValueSet", ok, f"distinct values {sorted(got, key=str)}", sorted(want, key=str),
                  sorted(got, key=str))


def a_value_set(ctx, spec):
    """The distinct values at ``path`` across the records are exactly ``values`` (optional ``tolerance``).
    The path-based twin of channelValueSet, for sinks whose records are not SFC target data (an OPC-UA
    probe, SiteWise history, S3 Tables rows)."""
    want, tol = list(spec["values"]), spec.get("tolerance")
    got = list(dict.fromkeys(v for v in (select(r, spec["path"]) for r in _records(ctx, spec)) if v is not _MISSING))
    if tol is None:
        ok = {repr(typed(g)) for g in got} == {repr(typed(w)) for w in want} if spec.get("strictTypes") \
            else {repr(g) for g in got} == {repr(w) for w in want}
    else:
        ok = all(any(_matches(g, w, tol) for w in want) for g in got) and \
            all(any(_matches(g, w, tol) for g in got) for w in want)
    return Result("valueSet", ok, f"distinct values at {spec['path']}", sorted(want, key=str), sorted(got, key=str)[:20])


def a_channel_value_in(ctx, spec):
    source, channel = spec["source"], spec["channel"]
    allowed = set(spec["values"])
    got = [v for v in _channel_values(_records(ctx, spec), source, channel, spec.get("element", "value"))
           if v is not _MISSING]
    if not got:
        return Result("channelValueIn", False, f"no values for {source}.{channel}", sorted(allowed, key=str), None, invalid=True)
    bad = [v for v in got if v not in allowed]
    return Result("channelValueIn", not bad, f"{len(bad)} outside" if bad else f"all {len(got)} allowed",
                  sorted(allowed, key=str), sorted(set(map(str, bad))) if bad else "all allowed")


def a_channel_numeric_range(ctx, spec):
    source, channel = spec["source"], spec["channel"]
    lo, hi = float(spec["min"]), float(spec["max"])
    got = [v for v in _channel_values(_records(ctx, spec), source, channel, spec.get("element", "value"))
           if v is not _MISSING]
    if not got:
        return Result("channelNumericRange", False, "no values", [lo, hi], None, invalid=True)
    try:
        nums = [float(v) for v in got]
    except (TypeError, ValueError):
        return Result("channelNumericRange", False, "not numeric", [lo, hi], got[:5], invalid=True)
    bad = [v for v in nums if v < lo or v > hi]
    return Result("channelNumericRange", not bad, f"{len(bad)} outside" if bad else f"all within [{lo}, {hi}]",
                  [lo, hi], {"min": min(nums), "max": max(nums), "outside": bad[:5]})


def a_cycle(ctx, spec):
    """Values at ``path`` follow ``cycle`` repeatedly (any rotation), over at least ``minLength`` records."""
    recs = _records(ctx, spec)
    cyc = list(spec["cycle"])
    vals = [select(r, spec["path"]) for r in recs]
    vals = [v for v in vals if v is not _MISSING] if spec.get("skipMissing", True) else vals
    if len(vals) < spec.get("minLength", len(cyc)):
        return Result("cycle", False, f"only {len(vals)} value(s)", cyc, vals, invalid=True)
    for offset in range(len(cyc)):
        if all(v == cyc[(i + offset) % len(cyc)] for i, v in enumerate(vals)):
            return Result("cycle", True, f"{len(vals)} values follow the cycle", cyc, vals[:len(cyc) * 2])
    return Result("cycle", False, "values do not follow the cycle", cyc, vals[:len(cyc) * 2])


def a_distinct(ctx, spec):
    vals = [select(r, spec["path"]) for r in _records(ctx, spec)]
    distinct = {repr(v) for v in vals if v is not _MISSING}
    ok, want = _bounds(len(distinct), spec)
    return Result("distinct", ok, f"{len(distinct)} distinct value(s) at {spec['path']}", want, len(distinct))


def a_no_duplicates(ctx, spec):
    path = spec.get("path", "serial")
    vals = [select(r, path) for r in _records(ctx, spec)]
    vals = [v for v in vals if v is not _MISSING]
    dupes = sorted({repr(v) for v in vals if vals.count(v) > 1})
    return Result("noDuplicates", not dupes, f"{len(dupes)} duplicated" if dupes else f"{len(vals)} unique",
                  "no duplicates", dupes[:5] or "none")


def a_serial_set(ctx, spec):
    """Record identity across two sinks: ``equal`` (no loss, no duplicates) or ``subset``."""
    path = spec.get("path", "serial")
    a = [select(r, path) for r in ctx.sinks.get(spec["a"], [])]
    b = [select(r, path) for r in ctx.sinks.get(spec["b"], [])]
    sa, sb = set(map(repr, a)), set(map(repr, b))
    relation = spec.get("relation", "equal")
    ok = sa == sb if relation == "equal" else sa <= sb
    return Result("serialSet", ok, f"{spec['a']}={len(sa)} {relation} {spec['b']}={len(sb)}",
                  relation, {"onlyIn_" + spec["a"]: sorted(sa - sb)[:5], "onlyIn_" + spec["b"]: sorted(sb - sa)[:5]})


def a_paths_equal(ctx, spec):
    recs = _records(ctx, spec)
    bad = [i for i, r in enumerate(recs) if select(r, spec["a"]) != select(r, spec["b"])]
    return Result("pathsEqual", bool(recs) and not bad, f"{len(bad)} record(s) differ", f"{spec['a']} == {spec['b']}",
                  bad[:5] or "all equal", invalid=not recs)


def _ts(v):
    import datetime as dt

    if not isinstance(v, str):
        return None
    try:
        return dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def a_ts_delta(ctx, spec):
    """Per record, ``to - from`` in milliseconds lies within [minMs, maxMs]."""
    recs = _records(ctx, spec)
    deltas = []
    for r in recs:
        a, b = _ts(select(r, spec["from"])), _ts(select(r, spec["to"]))
        if a is None or b is None:
            return Result("tsDelta", False, "timestamp missing or unparseable", spec, None, invalid=True)
        deltas.append((b - a).total_seconds() * 1000)
    lo, hi = spec.get("minMs", float("-inf")), spec.get("maxMs", float("inf"))
    bad = [d for d in deltas if d < lo or d > hi]
    return Result("tsDelta", bool(recs) and not bad, f"{len(bad)} outside", [lo, hi],
                  {"min": min(deltas, default=None), "max": max(deltas, default=None)}, invalid=not recs)


def a_deep_equals(ctx, spec):
    recs = _records(ctx, spec)
    index = int(spec.get("index", 0))
    if index >= len(recs):
        return Result("deepEquals", False, f"no record at index {index}", spec["value"], None, invalid=True)
    got = normalise(recs[index], spec.get("normalise"))
    if "path" in spec:
        got = select(got, spec["path"])
        if got is _MISSING:
            return Result("deepEquals", False, f"{spec['path']} missing", spec["value"], None, invalid=True)
    want = spec["value"]
    ok = typed(got) == typed(want) if spec.get("strictTypes") else got == want
    return Result("deepEquals", ok, "deep equality", want, got)


# ---------------------------------------------------------------------------------------------- logs

def a_log_contains(ctx, spec):
    hay = _logs(ctx, spec)
    n = hay.count(spec["text"])
    want = int(spec.get("min", 1))
    return Result("logContains", n >= want, f"{spec['text']!r} found {n}x in {spec.get('process', '*')}",
                  f">= {want}", n)


def a_log_absent(ctx, spec):
    hay = _logs(ctx, spec)
    hits = [t for t in spec["texts"] if t in hay]
    return Result("logAbsent", not hits, f"forbidden text present: {hits}" if hits else f"none of {len(spec['texts'])} present",
                  {"absent": spec["texts"]}, hits or "none")


def a_log_count(ctx, spec):
    n = _logs(ctx, spec).count(spec["text"])
    ok, want = _bounds(n, spec)
    return Result("logCount", ok, f"{spec['text']!r} x{n}", want, n)


def a_log_regex(ctx, spec):
    m = re.search(spec["regex"], _logs(ctx, spec), re.MULTILINE)
    return Result("logRegex", bool(m), "matched" if m else "no match", spec["regex"], m.group(0)[:200] if m else None)


def a_exit_code(ctx, spec):
    if "equals" in spec:
        return Result("exitCode", ctx.exit_code == spec["equals"], f"exit {ctx.exit_code}", spec["equals"], ctx.exit_code)
    nonzero = bool(spec.get("nonZero", True))
    ok = (ctx.exit_code not in (0, None)) if nonzero else ctx.exit_code == 0
    return Result("exitCode", ok, f"exit {ctx.exit_code}", "non-zero" if nonzero else 0, ctx.exit_code)


# ------------------------------------------------------------------------------------------- metrics

_OPS: dict[str, Callable[[float, float], bool]] = {
    "eq": lambda a, b: a == b, "ne": lambda a, b: a != b, "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b, "lt": lambda a, b: a < b, "le": lambda a, b: a <= b,
}


def a_metric(ctx, spec):
    if ctx.metrics is None or ctx.metrics.is_empty():
        return Result("metric", False, "no metrics were recorded", spec, None, invalid=True)
    got = ctx.metrics.total(spec["source"], spec["name"])
    op = spec.get("op", "ge")
    return Result("metric", _OPS[op](got, float(spec["value"])), f"{spec['source']}.{spec['name']} {got} {op} {spec['value']}",
                  f"{op} {spec['value']}", got)


def a_metric_ratio(ctx, spec):
    if ctx.metrics is None or ctx.metrics.is_empty():
        return Result("metricRatio", False, "no metrics", spec, None, invalid=True)
    num = ctx.metrics.total(spec["numerator"]["source"], spec["numerator"]["name"])
    den = ctx.metrics.total(spec["denominator"]["source"], spec["denominator"]["name"])
    if den == 0:
        return Result("metricRatio", False, "denominator is 0", spec, None, invalid=True)
    ratio = num / den
    op = spec.get("op", "ge")
    return Result("metricRatio", _OPS[op](ratio, float(spec["value"])), f"ratio {ratio:.3f} {op} {spec['value']}",
                  f"{op} {spec['value']}", round(ratio, 4))


def a_metric_absent(ctx, spec):
    names = {name for (_s, name) in (ctx.metrics.series if ctx.metrics else {})}
    hits = [n for n in spec["names"] if n in names]
    return Result("metricAbsent", not hits, f"present: {hits}" if hits else "absent", spec["names"], hits or "none")


# --------------------------------------------------------------------------------------- files/raw

def _sink_files(ctx, name):
    sink = ctx.sink_objects.get(name)
    if sink is None or not hasattr(sink, "files"):
        raise AssertError(f"sink {name!r} has no files")
    return sink.files()


def a_raw_contains(ctx, spec):
    texts = [p.read_text(errors="replace") for p in _sink_files(ctx, spec.get("sink", "main"))]
    joined = "\n".join(texts)
    n = joined.count(spec["text"])
    return Result("rawContains", n >= int(spec.get("min", 1)), f"{spec['text']!r} x{n}", f">= {spec.get('min', 1)}", n)


def a_raw_absent(ctx, spec):
    joined = "\n".join(p.read_text(errors="replace") for p in _sink_files(ctx, spec.get("sink", "main")))
    hits = [t for t in spec["texts"] if t in joined]
    return Result("rawAbsent", not hits, f"present: {hits}" if hits else "absent", spec["texts"], hits or "none")


def a_file_name_regex(ctx, spec):
    rx = re.compile(spec["regex"])
    files = _sink_files(ctx, spec.get("sink", "main"))
    root = ctx.sink_objects[spec.get("sink", "main")].directory
    rel = [str(p.relative_to(root)) if spec.get("relative") else p.name for p in files]
    bad = [r for r in rel if not rx.fullmatch(r)]
    return Result("fileNameRegex", bool(files) and not bad, f"{len(bad)}/{len(files)} do not match", spec["regex"],
                  bad[:5] or "all match", invalid=not files)


def a_file_count(ctx, spec):
    n = len(_sink_files(ctx, spec.get("sink", "main")))
    ok, want = _bounds(n, spec)
    return Result("fileCount", ok, f"{n} file(s)", want, n)


def a_file_record_count(ctx, spec):
    """Each file in the sink holds exactly ``perFile`` records (or within min/max)."""
    sink = ctx.sink_objects[spec.get("sink", "main")]
    counts = [len(sink._parse(p) or []) for p in sink.files()]
    if "perFile" in spec:
        bad = [c for c in counts if c != spec["perFile"]]
        ok = bool(counts) and not bad
        return Result("fileRecordCount", ok, f"per-file counts {counts[:10]}", spec["perFile"], bad[:5] or "all ok")
    ok = bool(counts) and all(_bounds(c, spec)[0] for c in counts)
    return Result("fileRecordCount", ok, f"per-file counts {counts[:10]}", {"min": spec.get("min"), "max": spec.get("max")}, counts[:10])


def a_zip_entries(ctx, spec):
    import zipfile

    rx = re.compile(spec["regex"])
    names = []
    for p in _sink_files(ctx, spec.get("sink", "main")):
        if zipfile.is_zipfile(p):
            with zipfile.ZipFile(p) as zf:
                names.extend(zf.namelist())
    bad = [n for n in names if not rx.fullmatch(n)]
    return Result("zipEntries", bool(names) and not bad, f"{len(names)} entries", spec["regex"], bad[:5] or "all match",
                  invalid=not names)


def a_dir_files(ctx, spec):
    d = Path(ctx.workdir) / "dirs" / spec["dir"] if ctx.workdir else Path(spec["dir"])
    files = [p for p in d.rglob("*") if p.is_file()] if d.is_dir() else []
    if "nameRegex" in spec:
        rx = re.compile(spec["nameRegex"])
        files = [p for p in files if rx.fullmatch(p.name)]
    ok, want = _bounds(len(files), spec)
    return Result("dirFiles", ok, f"{len(files)} file(s) in {spec['dir']}", want, len(files))


def a_xml_path(ctx, spec):
    """Text at an XPath-like ``path`` in every text record of a sink equals/matches."""
    recs = ctx.sinks.get(spec.get("sink", "main"), [])
    bad = []
    for r in recs:
        try:
            root = ET.fromstring(r["text"] if isinstance(r, dict) and "text" in r else r)
        except (ET.ParseError, TypeError):
            bad.append("unparseable")
            continue
        node = root.find(spec["path"])
        text = node.text if node is not None else None
        if "equals" in spec and text != spec["equals"]:
            bad.append(text)
        if "regex" in spec and not (text and re.fullmatch(spec["regex"], text)):
            bad.append(text)
    return Result("xmlPath", bool(recs) and not bad, f"{len(bad)} mismatch(es)", spec.get("equals", spec.get("regex")),
                  bad[:5] or "all ok", invalid=not recs)


def a_mark_delta(ctx, spec):
    """A sink grew by at least/exactly N records since a timeline ``mark``."""
    before = ctx.marks.get(spec["mark"], {}).get(spec["sink"])
    if before is None:
        return Result("markDelta", False, f"no mark {spec['mark']!r}", spec, None, invalid=True)
    delta = len(ctx.sinks.get(spec["sink"], [])) - before
    ok, want = _bounds(delta, spec)
    return Result("markDelta", ok, f"{spec['sink']} grew by {delta} since {spec['mark']}", want, delta)


KINDS: dict[str, Callable[[Context, dict], Result]] = {
    "recordCount": a_record_count, "everyRecord": a_every_record, "keysAbsent": a_keys_absent,
    "keyOrder": a_key_order, "keySet": a_key_set,
    "channelSequence": a_channel_sequence, "channelValueRun": a_channel_value_run,
    "channelValueSet": a_channel_value_set, "channelValueIn": a_channel_value_in, "valueSet": a_value_set,
    "channelNumericRange": a_channel_numeric_range, "cycle": a_cycle, "distinct": a_distinct,
    "noDuplicates": a_no_duplicates, "serialSet": a_serial_set, "pathsEqual": a_paths_equal,
    "tsDelta": a_ts_delta, "deepEquals": a_deep_equals,
    "logContains": a_log_contains, "logAbsent": a_log_absent, "logCount": a_log_count, "logRegex": a_log_regex,
    "exitCode": a_exit_code, "metric": a_metric, "metricRatio": a_metric_ratio, "metricAbsent": a_metric_absent,
    "rawContains": a_raw_contains, "rawAbsent": a_raw_absent, "fileNameRegex": a_file_name_regex,
    "fileCount": a_file_count, "fileRecordCount": a_file_record_count, "zipEntries": a_zip_entries,
    "dirFiles": a_dir_files, "xmlPath": a_xml_path, "markDelta": a_mark_delta,
}


def evaluate(ctx: Context, specs: list[dict]) -> list[Result]:
    out = []
    for spec in specs:
        fn = KINDS.get(spec.get("kind"))
        if fn is None:
            raise AssertError(f"unknown assertion kind {spec.get('kind')!r}; known: {sorted(KINDS)}")
        try:
            out.append(fn(ctx, spec))
        except AssertError:
            raise
        except KeyError as e:
            raise AssertError(f"assertion {spec.get('kind')!r} is missing required field {e}") from None
    return out
