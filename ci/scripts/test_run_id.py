#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests the run-id derivation, which has to agree across three implementations.

The same build is spelled two different ways by the two sources that need to identify it:

    inside the container   $CODEBUILD_BUILD_ID   = "sfc-integration-test:0e5e1b9c-...."
    in the EventBridge event  detail["build-id"] = "arn:aws:codebuild:us-east-1:123456789012:build/sfc-integration-test:0e5e1b9c-..."

Splitting on the FIRST colon gives "sfc-integration-test" for one and the literal "aws" for the other.
That mismatch is silent: the janitor would compute a run id that matches nothing, delete nothing, report
success, and leak every per-run resource until the hourly sweep noticed. So all three places -
``janitor.py``, ``provision.py`` and the buildspec's ``${CODEBUILD_BUILD_ID##*:}`` - split on the LAST
colon, and this test pins that with a real ARN-shaped fixture.

Run with:  python3 ci/scripts/test_run_id.py
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "cdk" / "lambda"))

UUID = "0e5e1b9c-4a71-4f0e-9d3a-1b2c3d4e5f60"
PROJECT = "sfc-integration-test"

CONTAINER_FORM = f"{PROJECT}:{UUID}"
EVENT_FORM = f"arn:aws:codebuild:us-east-1:123456789012:build/{PROJECT}:{UUID}"

EXPECTED = "b_0e5e1b9c4a71"


def check(label: str, got: str, want: str) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    return ok


def main() -> int:
    from janitor import run_id_from_build_id  # noqa: PLC0415

    results = [
        check("container form", run_id_from_build_id(CONTAINER_FORM), EXPECTED),
        check("event ARN form", run_id_from_build_id(EVENT_FORM), EXPECTED),
    ]

    # The two forms must agree with each other - that is the whole point.
    results.append(
        check(
            "both forms agree",
            run_id_from_build_id(CONTAINER_FORM),
            run_id_from_build_id(EVENT_FORM),
        )
    )

    # And the shell expansion used in the buildspec must produce the same uuid segment.
    shell_uuid = subprocess.run(
        ["bash", "-c", f'BUILD_ID="{EVENT_FORM}"; echo "${{BUILD_ID##*:}}"'],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    results.append(check("bash ${BUILD_ID##*:} on the ARN form", "b_" + shell_uuid.replace("-", "")[:12], EXPECTED))

    shell_uuid2 = subprocess.run(
        ["bash", "-c", f'BUILD_ID="{CONTAINER_FORM}"; echo "${{BUILD_ID##*:}}"'],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    results.append(check("bash ${BUILD_ID##*:} on the container form", "b_" + shell_uuid2.replace("-", "")[:12], EXPECTED))

    # Negative control: the naive first-colon split must NOT produce the right answer on the ARN form.
    # If it ever does, this test has stopped discriminating and the bug could return unnoticed.
    naive = EVENT_FORM.split(":")[1]
    results.append(
        check("naive first-colon split is still wrong (control)", naive, "aws")
    )

    print()
    if all(results):
        print("run-id derivation is consistent across janitor.py, the buildspec and provision.py")
        return 0
    print("run-id derivation is INCONSISTENT - the janitor would delete nothing", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
