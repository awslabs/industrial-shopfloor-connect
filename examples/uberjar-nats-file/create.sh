#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Writes nats-to-file.json: the uberjar configuration of the e2e case ADP-NATS-PILOT (ci/e2e/cases/adapters/nats.json),
# without the CI-only Metadata and Metrics sections. Needs jq.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cases="$here/../../ci/e2e/cases/adapters/nats.json"
jq --arg id ADP-NATS-PILOT '.cases[] | select(.id == $id) | .config * .uberjar | del(.Metadata, .Metrics)' "$cases" > "$here/nats-to-file.json"
echo "wrote $here/nats-to-file.json"
