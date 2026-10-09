#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Writes modbus-to-file.json: the uberjar configuration of the e2e case ADP-MODBUS-PILOT (ci/e2e/cases/adapters/modbus.json),
# without the CI-only Metadata and Metrics sections. Needs jq.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cases="$here/../../ci/e2e/cases/adapters/modbus.json"
jq --arg id ADP-MODBUS-PILOT '.cases[] | select(.id == $id) | .config * .uberjar | del(.Metadata, .Metrics)' "$cases" > "$here/modbus-to-file.json"
echo "wrote $here/modbus-to-file.json"
