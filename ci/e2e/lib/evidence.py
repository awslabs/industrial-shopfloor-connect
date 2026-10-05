# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Incremental evidence upload.

Each case run is uploaded the moment it finishes, and the report files are re-uploaded after every case.
That is what makes a timed-out or stopped build still leave a usable partial report: CodeBuild skips
``post_build`` in exactly those two situations, so evidence uploaded only at the end is evidence lost.

Uses the ``aws`` CLI rather than boto3 so the core tier stays free of Python dependencies.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path


class Uploader:
    def __init__(self, destination: str | None):
        self.destination = destination.rstrip("/") + "/" if destination else None
        self.enabled = bool(self.destination) and shutil.which("aws") is not None
        self.errors: list[str] = []
        self._lock = threading.Lock()

    def _cp(self, args: list[str]) -> None:
        if not self.enabled:
            return
        proc = subprocess.run(["aws", "s3", "cp", *args, "--only-show-errors"],
                              capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            with self._lock:
                self.errors.append(proc.stderr.strip()[:300])

    def case_dir(self, path: Path, name: str) -> None:
        self._cp(["--recursive", str(path), f"{self.destination}cases/{name}/"])

    def files(self, paths: list[Path]) -> None:
        for p in paths:
            self._cp([str(p), f"{self.destination}{p.name}"])
