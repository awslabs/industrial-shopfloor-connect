#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Writes pccc-to-file.json: the uberjar configuration of the e2e case ADP-PCCC-PILOT (ci/e2e/cases/adapters/pccc.json),
# without the CI-only Metadata and Metrics sections. Needs jq.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cases="$here/../../ci/e2e/cases/adapters/pccc.json"
jq --arg id ADP-PCCC-PILOT '.cases[] | select(.id == $id) | .config * .uberjar | del(.Metadata, .Metrics)' "$cases" > "$here/pccc-to-file.json"
echo "wrote $here/pccc-to-file.json"
