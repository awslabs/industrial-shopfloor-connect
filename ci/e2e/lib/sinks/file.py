# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""The file-target sink: a deterministic record counter and reader.

This is the mechanism that lets the suite gate on **record count instead of wall-clock time**. A case
declares how many records it needs; the runner waits for exactly that many and then stops SFC.

The mechanics, verified against ``targets/file-target``:

* ``"BufferCount": 1`` flushes on every message (FileTargetWriter.kt:147), so one file == one record.
  ``Interval`` cannot be used for this - it is validated to ``60..900`` seconds.
* With ``"Json": true`` and no template each file holds a JSON **array** (FileTargetWriter.kt:278-295).
* Files land in ``<Directory>/YYYY/M/D/H/M/<uuid><extension>`` (buildFilePath) using the *local*
  calendar unless ``UtcTime`` is set; the search is recursive so partitioning never hides a record.
* ``Directory`` must already exist (FileTargetConfiguration.kt:100), so ``prepare()`` creates it.

Formats: ``json`` (default - one JSON document per file, array or object), ``lines`` (one JSON document
per line), ``text`` (raw text, one "record" per file: ``{"path", "text"}``) and ``bytes`` (``{"path",
"size", "data"}``). ``.gz`` and ``.zip`` files are decompressed transparently; zip entries are exposed.
"""

from __future__ import annotations

import calendar
import gzip
import io
import json
import re
import time
import zipfile
from pathlib import Path

from . import Sink


def _decode_bytes(path: Path, raw: bytes) -> list[tuple[str, bytes]]:
    """Return (entry name, content) pairs - one for a plain or gzip file, one per entry for a zip."""
    if raw[:2] == b"\x1f\x8b":
        return [(path.name, gzip.decompress(raw))]
    if raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            return [(n, zf.read(n)) for n in zf.namelist()]
    return [(path.name, raw)]


def iter_json_documents(text: str) -> list:
    """Parse one or more concatenated JSON documents (Firehose and Kafka bodies use this framing)."""
    decoder = json.JSONDecoder()
    out, i, n = [], 0, len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break
        doc, i = decoder.raw_decode(text, i)
        out.append(doc)
    return out


_INSTANT = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z")


def _instant_ns(value) -> int:
    """SFC's record timestamp (Instant.toString(): 0, 3, 6 or 9 fraction digits) as epoch nanoseconds; 0 if none."""
    m = _INSTANT.fullmatch(value) if isinstance(value, str) else None
    if not m:
        return 0
    seconds = calendar.timegm(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S"))
    return seconds * 1_000_000_000 + int((m.group(2) or "0").ljust(9, "0"))


class FileDirSink(Sink):
    kind = "file"

    def __init__(self, name, spec, ctx):
        super().__init__(name, spec, ctx)
        self.directory = Path(ctx.workdir) / "sinks" / name
        self.format = spec.get("format", "json")

    def prepare(self) -> dict[str, str]:
        self.directory.mkdir(parents=True, exist_ok=True)
        env = {f"SFC_E2E_SINK_{self.name.upper().replace('-', '_')}": str(self.directory)}
        if self.name == "main":
            env["SFC_E2E_SINK"] = str(self.directory)
        return env

    def files(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        files = [p for p in self.directory.rglob("*") if p.is_file()]
        return sorted(files, key=lambda p: (p.stat().st_mtime_ns, str(p)))

    def _parse(self, path: Path) -> list | None:
        """Records in ``path``, or None when it does not parse yet (being written)."""
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        if not raw:
            return None
        try:
            entries = _decode_bytes(path, raw)
        except (OSError, EOFError, zipfile.BadZipFile):
            return None
        out: list = []
        for entry_name, content in entries:
            if self.format == "bytes":
                out.append({"path": str(path), "entry": entry_name, "size": len(content), "data": content})
                continue
            text = content.decode("utf-8", errors="replace")
            if self.format == "text":
                out.append({"path": str(path), "entry": entry_name, "text": text})
                continue
            try:
                if self.format == "lines":
                    docs = [json.loads(line) for line in text.splitlines() if line.strip()]
                else:
                    docs = iter_json_documents(text)
            except json.JSONDecodeError:
                return None
            for doc in docs:
                out.extend(doc if isinstance(doc, list) else [doc])
        return out

    def records(self) -> list:
        """Every record from files that parse cleanly, in the order SFC wrote them.

        A file that does not parse yet is being written and is simply not counted. Write order is the files'
        mtime - but Linux stamps a file once per kernel tick and the file target names files with a random UUID
        (FileTargetWriter.kt:322), so files of one tick are ordered by their first record's own timestamp.
        """
        parsed = []
        for path in self.files():
            recs = self._parse(path)
            if recs is not None:
                first = recs[0] if recs and isinstance(recs[0], dict) else {}
                parsed.append((path.stat().st_mtime_ns, _instant_ns(first.get("timestamp")), recs))
        out: list = []
        for _, _, recs in sorted(parsed, key=lambda t: (t[0], t[1])):
            out.extend(recs)
        return out

    def file_count(self) -> int:
        return len(self.files())

    def describe(self) -> dict:
        return {"name": self.name, "kind": self.kind, "directory": str(self.directory),
                "files": self.file_count()}
