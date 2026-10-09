# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Install the Kafka CLI tools and the MSK IAM jar (no broker): idempotent, checksum-verified.

    python3 ci/e2e/lib/install_kafka.py --home /opt/kafka --version 3.9.0 --scala 2.13 --msk-iam 2.3.8

The tarball is verified against the ``.sha512`` file Apache publishes next to it. Apache formats that file
as ``name: HEX HEX ...`` in upper case, split into groups and sometimes across lines, so it is normalised
before comparison. A no-op when ``bin/kafka-topics.sh`` and the IAM jar already exist (the CodeBuild cache).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path


def _fetch(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as resp, dest.open("wb") as fh:  # noqa: S310 - fixed https URLs
        shutil.copyfileobj(resp, fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", required=True, type=Path)
    ap.add_argument("--version", required=True)
    ap.add_argument("--scala", required=True)
    ap.add_argument("--msk-iam", required=True)
    a = ap.parse_args()

    iam_jar = a.home / "libs" / f"aws-msk-iam-auth-{a.msk_iam}-all.jar"
    if (a.home / "bin" / "kafka-topics.sh").is_file() and iam_jar.is_file():
        print(f"kafka CLI present at {a.home}")
        return 0

    name = f"kafka_{a.scala}-{a.version}.tgz"
    base = f"https://archive.apache.org/dist/kafka/{a.version}/{name}"
    with tempfile.TemporaryDirectory() as tmp:
        tgz, sums = Path(tmp) / name, Path(tmp) / f"{name}.sha512"
        _fetch(base, tgz)
        _fetch(base + ".sha512", sums)
        published = "".join(sums.read_text().split(":", 1)[1].split()).lower()
        actual = hashlib.sha512(tgz.read_bytes()).hexdigest()
        if actual != published:
            raise SystemExit(f"checksum mismatch for {name}: {actual} != {published}")
        a.home.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tgz) as tf:
            root = tf.getmembers()[0].name.split("/")[0]
            try:
                tf.extractall(tmp, filter="data")  # type: ignore[call-arg]
            except TypeError:
                tf.extractall(tmp)
        for item in (Path(tmp) / root).iterdir():
            target = a.home / item.name
            if target.exists():
                shutil.rmtree(target) if target.is_dir() else target.unlink()
            shutil.move(str(item), str(target))
    _fetch(f"https://github.com/aws/aws-msk-iam-auth/releases/download/v{a.msk_iam}/aws-msk-iam-auth-{a.msk_iam}-all.jar", iam_jar)
    print(f"installed kafka {a.version} CLI and aws-msk-iam-auth {a.msk_iam} into {a.home}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
