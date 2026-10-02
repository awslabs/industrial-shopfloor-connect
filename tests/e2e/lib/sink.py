# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""The file-target sink: a deterministic record counter and reader.

This is the mechanism that lets the suite gate on **record count instead of wall-clock time**, which is
the single most important determinism decision in the harness. A case declares how many records it
needs; the runner waits for exactly that many to appear and then stops SFC. Nothing sleeps for "long
enough", so the suite is neither slow nor flaky, and the expected values are exact because the
simulator's Counter advances once per read.

The mechanics, all verified against ``targets/file-target``:

* ``"BufferCount": 1`` flushes on every message (FileTargetWriter.kt:147), so one file == one record.
  ``Interval`` cannot be used for this - it is validated to ``60..900`` seconds - and ``BufferSize`` is
  validated to ``1..1024`` KB, so neither can force a fast flush. ``BufferCount`` is the only lever.
* With ``"Json": true`` and no template, each file holds a JSON **array** (FileTargetWriter.kt:278-295),
  so a one-record file is ``[{...}]``.
* Files land in ``<Directory>/YYYY/M/D/H/M/<uuid><extension>`` (buildFilePath, :307) using the *local*
  calendar unless ``"UtcTime": true``. Cases set UtcTime and the runner forces ``TZ=UTC``, but the
  search is recursive regardless so partitioning cannot hide a record.
* ``Directory`` must already exist - FileTargetConfiguration validates it (:100) - so the runner creates
  it before launching.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path


class SinkError(RuntimeError):
    pass


@dataclass
class SinkFile:
    path: Path
    #: Records parsed out of this file, in file order.
    records: list[dict]


class FileSink:
    """Watches a file-target output directory."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def _files(self) -> list[Path]:
        # Everything that is a file, at any depth, sorted by (mtime, name). Extension is not assumed:
        # buildExtension() returns whatever `Extension` was configured, and compression changes it.
        files = [p for p in self.directory.rglob("*") if p.is_file()]
        return sorted(files, key=lambda p: (p.stat().st_mtime_ns, p.name))

    def count(self) -> int:
        """Number of complete files currently present.

        A file being written is excluded by requiring it to parse, which is what makes polling safe
        without any locking: a torn half-written file simply does not count yet.
        """
        return len(self.read_all(strict=False))

    def read_all(self, strict: bool = True) -> list[SinkFile]:
        out: list[SinkFile] = []
        for path in self._files():
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                if strict:
                    raise
                continue
            text = text.strip()
            if not text:
                if strict:
                    raise SinkError(f"{path} is empty")
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as e:
                # Mid-write when polling; a genuine problem once the run has finished.
                if strict:
                    raise SinkError(f"{path} is not valid JSON: {e}\n{text[:400]}") from None
                continue
            records = parsed if isinstance(parsed, list) else [parsed]
            out.append(SinkFile(path=path, records=records))
        return out

    def records(self) -> list[dict]:
        """Every record, in arrival order.

        Arrival order at the sink *is* pipeline order, which is what an ordered assertion means. Sorting
        by the record's own timestamp would not be a total order - two records can share a millisecond.
        """
        return [r for f in self.read_all() for r in f.records]

    def wait_for_records(
        self,
        n: int,
        timeout: float,
        proc=None,
        poll: float = 0.05,
    ) -> list[dict]:
        """Block until at least ``n`` records have been written, then return all of them.

        If ``proc`` is supplied and exits first, its own diagnostics are raised instead of a timeout -
        a configuration error should report itself, not masquerade as a slow pipeline.
        """
        deadline = time.monotonic() + timeout
        last = 0
        while time.monotonic() < deadline:
            files = self.read_all(strict=False)
            last = sum(len(f.records) for f in files)
            if last >= n:
                # One more pass in strict mode: everything must parse cleanly now.
                return [r for f in self.read_all() for r in f.records]
            if proc is not None and proc.poll() is not None:
                raise SinkError(
                    f"{proc.name} exited with {proc.popen.returncode} after {last}/{n} record(s)\n"
                    f"--- stderr ---\n{proc.tail_stderr()}\n--- stdout (tail) ---\n{proc.tail_stdout()}"
                )
            time.sleep(poll)

        raise SinkError(
            f"only {last}/{n} record(s) reached {self.directory} within {timeout}s"
            + (f"\n--- stdout (tail) ---\n{proc.tail_stdout()}" if proc is not None else "")
        )
