#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Writes sql-to-file.json: the uberjar configuration of the e2e case ADP-SQL-PILOT (ci/e2e/cases/adapters/sql.json),
# without the CI-only Metadata and Metrics sections. Needs jq.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cases="$here/../../ci/e2e/cases/adapters/sql.json"
jq --arg id ADP-SQL-PILOT '.cases[] | select(.id == $id) | .config * .uberjar | del(.Metadata, .Metrics)' "$cases" > "$here/sql-to-file.json"
jq -r --arg id ADP-SQL-PILOT '.cases[] | select(.id == $id) | .files["seed.sql"]' "$cases" > "$here/seed.sql"
echo "wrote $here/sql-to-file.json"
