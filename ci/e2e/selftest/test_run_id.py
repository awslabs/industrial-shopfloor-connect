# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""The run id must be derived identically in the runner, the buildspec and the janitor.

The same build is spelled two ways: ``project:uuid`` inside the container, the full build ARN in the
EventBridge event. Splitting on the first colon yields the literal ``aws`` for the event, which would make
the janitor compute a run id that matches nothing and delete nothing while appearing to work.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))                 # ci/e2e
sys.path.insert(0, str(HERE.parents[2] / "cdk" / "lambda"))  # ci/cdk/lambda

from lib import runid  # noqa: E402
import janitor  # noqa: E402

UUID = "0e5e1b9c-4a71-4f0e-9d3a-1b2c3d4e5f60"
CONTAINER = f"sfc-integration-test:{UUID}"
EVENT = f"arn:aws:codebuild:us-east-1:123456789012:build/sfc-integration-test:{UUID}"
EXPECTED = "b_0e5e1b9c4a71"


def bash_suffix(build_id: str) -> str:
    out = subprocess.run(["bash", "-c", f'B="{build_id}"; echo "${{B##*:}}"'],
                         capture_output=True, text=True, check=True).stdout.strip()
    return "b_" + out.replace("-", "")[:12]


class RunIdTest(unittest.TestCase):
    def test_runner_both_forms(self):
        self.assertEqual(runid.run_id_from_build_id(CONTAINER), EXPECTED)
        self.assertEqual(runid.run_id_from_build_id(EVENT), EXPECTED)

    def test_janitor_both_forms(self):
        self.assertEqual(janitor.run_id_from_build_id(CONTAINER), EXPECTED)
        self.assertEqual(janitor.run_id_from_build_id(EVENT), EXPECTED)

    def test_bash_expansion_used_by_the_buildspec(self):
        self.assertEqual(bash_suffix(CONTAINER), EXPECTED)
        self.assertEqual(bash_suffix(EVENT), EXPECTED)

    def test_naive_first_colon_split_is_still_wrong(self):
        # Negative control: if this ever passes, the tests above stopped discriminating.
        self.assertEqual(EVENT.split(":")[1], "aws")

    def test_marker_charset_and_length(self):
        m = runid.marker(EXPECTED, "AWS-S3T-03 Auto/Create.namespace", "ipc")
        self.assertRegex(m, r"^[a-z0-9_]+$")
        self.assertLessEqual(len(m), 64)
        long = runid.marker(EXPECTED, "X" * 200, "uj")
        self.assertLessEqual(len(long), 64)
        self.assertNotEqual(long, runid.marker(EXPECTED, "X" * 199 + "Y", "uj"))


if __name__ == "__main__":
    unittest.main()
