#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Writes slmp-to-file.json: the uberjar configuration of the e2e case ADP-SLMP-PILOT (ci/e2e/cases/adapters/slmp.json),
# without the CI-only Metadata and Metrics sections. Needs jq.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cases="$here/../../ci/e2e/cases/adapters/slmp.json"
jq --arg id ADP-SLMP-PILOT '.cases[] | select(.id == $id) | .config * .uberjar | del(.Metadata, .Metrics)' "$cases" > "$here/slmp-to-file.json"
echo "wrote $here/slmp-to-file.json"
