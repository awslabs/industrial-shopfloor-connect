#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Writes opcua-to-file.json: the uberjar configuration of the e2e case ADP-OPCUA-POLL-STD-01 (ci/e2e/cases/adapters/opcua.json),
# without the CI-only Metadata and Metrics sections. Needs jq.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cases="$here/../../ci/e2e/cases/adapters/opcua.json"
jq --arg id ADP-OPCUA-POLL-STD-01 '.cases[] | select(.id == $id) | .config * .uberjar | del(.Metadata, .Metrics)' "$cases" > "$here/opcua-to-file.json"
echo "wrote $here/opcua-to-file.json"
