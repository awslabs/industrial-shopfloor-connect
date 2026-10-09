#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Writes s7-to-file.json: the uberjar configuration of the e2e case ADP-S7-PILOT (ci/e2e/cases/adapters/s7.json),
# without the CI-only Metadata and Metrics sections. Needs jq.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cases="$here/../../ci/e2e/cases/adapters/s7.json"
jq --arg id ADP-S7-PILOT '.cases[] | select(.id == $id) | .config * .uberjar | del(.Metadata, .Metrics)' "$cases" > "$here/s7-to-file.json"
echo "wrote $here/s7-to-file.json"
