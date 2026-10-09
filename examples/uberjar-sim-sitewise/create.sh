#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Writes sim-to-sitewise.json: the uberjar configuration of the e2e case AWS-SW-01 (ci/e2e/cases/aws/sitewise.json),
# without the CI-only Metadata and Metrics sections. Needs jq.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cases="$here/../../ci/e2e/cases/aws/sitewise.json"
jq --arg id AWS-SW-01 '.cases[] | select(.id == $id) | .config * .uberjar | del(.Metadata, .Metrics)' "$cases" > "$here/sim-to-sitewise.json"
echo "wrote $here/sim-to-sitewise.json"
