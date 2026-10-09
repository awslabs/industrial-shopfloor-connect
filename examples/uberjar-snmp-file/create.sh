#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Writes snmp-to-file.json: the uberjar configuration of the e2e case ADP-SNMP-PILOT (ci/e2e/cases/adapters/snmp.json),
# without the CI-only Metadata and Metrics sections. Needs jq.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cases="$here/../../ci/e2e/cases/adapters/snmp.json"
jq --arg id ADP-SNMP-PILOT '.cases[] | select(.id == $id) | .config * .uberjar | del(.Metadata, .Metrics)' "$cases" > "$here/snmp-to-file.json"
jq -r --arg id ADP-SNMP-PILOT '.cases[] | select(.id == $id) | .files["snmpd.conf"]' "$cases" > "$here/snmpd.conf"
echo "wrote $here/snmp-to-file.json"
