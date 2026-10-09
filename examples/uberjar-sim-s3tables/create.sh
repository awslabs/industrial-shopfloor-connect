#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Writes sim-to-s3tables.json: the uberjar configuration of the e2e case AWS-S3T-01 (ci/e2e/cases/aws/s3tables.json),
# without the CI-only Metrics section and the CI run markers in Metadata. Metadata.marker stays: it fills
# the table's label column. Needs jq.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cases="$here/../../ci/e2e/cases/aws/s3tables.json"
jq --arg id AWS-S3T-01 '.cases[] | select(.id == $id) | .config * .uberjar | del(.Metadata.runId, .Metadata.case, .Metadata.mode, .Metrics)' "$cases" > "$here/sim-to-s3tables.json"
echo "wrote $here/sim-to-s3tables.json"
