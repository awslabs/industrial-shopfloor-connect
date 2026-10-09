# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Where the AWS tier finds the stack's destinations.

The CDK stack defines one dictionary of ``SFC_E2E_*`` values - queue URLs, the stream name, the fixture
table bucket, the SiteWise aliases, the MSK cluster ARN - and uses it twice: as the CodeBuild project's
environment, and as a single ``E2eEnvironment`` stack output holding the same dictionary as JSON. So the
same keys reach a case in CodeBuild (from the environment) and on a laptop (from
``npx cdk deploy --outputs-file ci/cdk/outputs.json``) with nothing to look up at runtime and no extra IAM.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

#: Present in every stack environment; its presence is how the runner tells that the AWS tier is configured.
SENTINEL = "SFC_E2E_BUCKET"

OUTPUTS_FILE = Path(__file__).resolve().parents[2] / "cdk" / "outputs.json"


def load() -> dict[str, str]:
    """The stack values, from the environment first, then ``ci/cdk/outputs.json``."""
    env = {k: v for k, v in os.environ.items() if k.startswith("SFC_E2E_")}
    if SENTINEL in env:
        return env
    if OUTPUTS_FILE.is_file():
        outputs = json.loads(OUTPUTS_FILE.read_text(encoding="utf-8"))
        for stack in outputs.values():
            blob = stack.get("E2eEnvironment") if isinstance(stack, dict) else None
            if blob:
                values = json.loads(blob)
                values.update(env)  # an explicit environment variable always wins
                return {k: str(v) for k, v in values.items()}
    return env


def configured(values: dict[str, str]) -> bool:
    return SENTINEL in values
