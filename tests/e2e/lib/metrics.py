# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Reading the JSONL written by ``E2eMetricsWriter``.

These counters are the suite's second, independent oracle. Destination-side assertions prove that data
arrived; SFC's own counters prove that SFC *thinks* it succeeded. The interesting case is when the two
disagree, and one direction in particular is a silent data-loss bug that payload assertions cannot see:
a target that logs an error, increments ``WriteErrors`` and drops a batch while the process carries on
and exits 0.

So the runner treats a non-zero ``WriteErrors`` on a target under test as a failure even when every
payload assertion passed. That rule is the reason this module exists.

Metric names come from ``core/sfc-core/.../metrics/MetricsCollector.kt`` and are documented in
``docs/sfc-logging-metrics.md``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Per-target metrics that SFC collects for every target writer.
WRITES = "Writes"
WRITE_ERRORS = "WriteErrors"
WRITE_SUCCESS = "WriteSuccess"
WRITE_DURATION = "WriteDuration"
MESSAGES = "Messages"
BYTES_WRITTEN = "BytesWritten"
ERRORS = "Errors"
WARNINGS = "Warnings"


@dataclass
class Series:
    """All values recorded for one (source, metric name) pair."""

    source: str
    name: str
    units: str = ""
    values: list[float] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(self.values)

    @property
    def count(self) -> int:
        return len(self.values)

    @property
    def maximum(self) -> float | None:
        return max(self.values) if self.values else None

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "name": self.name,
            "units": self.units,
            "total": self.total,
            "samples": self.count,
            "max": self.maximum,
        }


class MetricsSnapshot:
    """Aggregated view of one run's metrics file."""

    def __init__(self, points: list[dict]):
        self.points = points
        self._series: dict[tuple[str, str], Series] = {}
        for p in points:
            key = (p.get("source", ""), p.get("name", ""))
            series = self._series.setdefault(
                key, Series(source=key[0], name=key[1], units=p.get("units", ""))
            )
            # Only single-valued points contribute to a total. MetricsValues/MetricsStatistics points
            # are kept in .points for inspection but summing them would silently mix distributions
            # with counts.
            if p.get("valueType") == "single":
                series.values.append(float(p.get("value", 0.0)))
        self.series = self._series

    @classmethod
    def load(cls, path: Path) -> "MetricsSnapshot":
        """Read a JSONL metrics file. A missing file yields an empty snapshot.

        Empty rather than an error: metrics are written on an interval, so a case short enough to finish
        inside the first interval legitimately produces nothing. Assertions that need metrics state that
        explicitly and fail on an empty snapshot themselves, which keeps the distinction between
        "nothing was recorded" and "nothing was asserted" visible.
        """
        if not path.is_file():
            return cls([])
        points: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                points.append(json.loads(line))
            except json.JSONDecodeError:
                # A torn final line can only happen if the process was killed mid-append; skip it
                # rather than fail the case for a harness artefact.
                continue
        return cls(points)

    def total(self, source: str, name: str) -> float:
        s = self.series.get((source, name))
        return s.total if s else 0.0

    def sources(self, category: str | None = None) -> set[str]:
        """Distinct metric sources, optionally filtered by the category dimension.

        The dimension key is ``Category`` - capitalised. ``docs/sfc-logging-metrics.md`` documents the
        default dimensions as lowercase "source", "category" and "type", but the collector emits
        ``Source``, ``Category`` and ``Type`` (observed in a real run, and consistent with
        MetricsCollector's constants). Both spellings are accepted here so the suite is not the thing
        that breaks if the documentation is ever made true.
        """
        out = set()
        for p in self.points:
            if category is None:
                out.add(p.get("source", ""))
                continue
            dims = p.get("dimensions") or {}
            if dims.get("Category", dims.get("category")) == category:
                out.add(p.get("source", ""))
        return out

    def target_sources(self) -> set[str]:
        return self.sources(category="Target")

    def write_errors(self) -> dict[str, float]:
        """``{target id: total WriteErrors}``, only for targets that reported any."""
        out: dict[str, float] = {}
        for (source, name), series in self.series.items():
            if name == WRITE_ERRORS and series.total > 0:
                out[source] = series.total
        return out

    def summary(self) -> list[dict]:
        """Per-target rows for the report, ordered for stable output."""
        interesting = (WRITES, WRITE_SUCCESS, WRITE_ERRORS, MESSAGES, BYTES_WRITTEN, ERRORS, WARNINGS)
        rows = []
        for source in sorted(self.target_sources()):
            row = {"target": source}
            for name in interesting:
                row[name] = self.total(source, name)
            rows.append(row)
        return rows

    def is_empty(self) -> bool:
        return not self.points
