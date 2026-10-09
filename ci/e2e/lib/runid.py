# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run identity: the run id, and the per case-and-mode marker.

The run id names everything a build creates and is what the janitor deletes by, so the derivation must be
identical here, in the buildspec and in the janitor. The same build is spelled two ways:

* inside the container ``$CODEBUILD_BUILD_ID`` is ``project-name:uuid``;
* in the EventBridge event ``detail["build-id"]`` is the full ARN, ``arn:aws:codebuild:...:build/project:uuid``.

Splitting on the *first* colon gives ``aws`` for the event and the project name for the container, which
would make the janitor delete nothing while appearing to work. Every implementation therefore splits on the
**last** colon (bash: ``${CODEBUILD_BUILD_ID##*:}``). ``ci/e2e/selftest/test_run_id.py`` pins all three.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets

RUN_PREFIX = "b_"


def run_id_from_build_id(build_id: str) -> str:
    """``arn:...:build/proj:uuid`` or ``proj:uuid`` -> ``b_<first 12 hex of the uuid>``."""
    uuid = build_id.rsplit(":", 1)[-1]
    return RUN_PREFIX + uuid.replace("-", "")[:12].lower()


def current_run_id() -> str:
    """The run id of this process: the CodeBuild build when there is one, random otherwise."""
    build_id = os.environ.get("CODEBUILD_BUILD_ID")
    if build_id:
        return run_id_from_build_id(build_id)
    return RUN_PREFIX + secrets.token_hex(6)


_SLUG = re.compile(r"[^a-z0-9]+")


def marker(run_id: str, case_id: str, mode_code: str, max_len: int = 64) -> str:
    """``<runId>_<case slug>_<mode code>``, ``[a-z0-9_]`` only.

    One string that is legal everywhere a case needs to name or tag something: an S3 key prefix, an IoT
    topic level, a Kafka topic, an Iceberg namespace or table, a SiteWise name and a string value. It is
    non-numeric on purpose - ``UnquoteNumericJsonValues`` unquotes any all-digit string.
    When the case id is long the slug is shortened and a hash suffix keeps markers unique.
    """
    slug = _SLUG.sub("_", case_id.lower()).strip("_")
    candidate = f"{run_id}_{slug}_{mode_code}"
    if len(candidate) <= max_len:
        return candidate
    digest = hashlib.sha1(case_id.encode()).hexdigest()[:6]
    room = max_len - len(run_id) - len(mode_code) - len(digest) - 3
    return f"{run_id}_{slug[:max(room, 1)]}{digest}_{mode_code}"


def retry_run_id(run_id: str, attempt: int) -> str:
    """The run id for retry ``attempt`` (1, 2, ...) of a unit: the last two hex digits shifted by ``attempt``.

    A retry needs a marker of its own - every destination is named by the marker, and a retry that shared
    the failed attempt's would read that attempt's leftovers. Only the hex part changes, so the result still
    matches ``b_[0-9a-f]{12}`` like every marker the cases' regexes expect.
    """
    return f"{run_id[:-2]}{(int(run_id[-2:], 16) + attempt) % 256:02x}"
