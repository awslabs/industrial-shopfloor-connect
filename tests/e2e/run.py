#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Entry point for the SFC end-to-end suite.

    ./tests/e2e/run.py --tier core --mode inprocess
    ./tests/e2e/run.py --tier core --modes inprocess,ipc,uberjar --parity
    ./tests/e2e/run.py --list

Requires only a JVM and a prior `./gradlew build` - the core tier touches no AWS service and no network.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
