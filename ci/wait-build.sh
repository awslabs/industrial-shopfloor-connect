#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Waits for a CodeBuild build to finish and exits 0 only if it SUCCEEDED.
#
#   ci/wait-build.sh <build-id>
#
# Transient CLI errors are retried rather than ending the wait: one failed poll used to abort the whole
# job and lose the report. On INT/TERM the build is stopped, so an interrupted wait never leaves a build
# running that would collide with the next one.
set -uo pipefail

BUILD_ID="${1:?usage: wait-build.sh <build-id>}"
POLL=15
MAX_FAILURES=20

trap 'echo "stopping $BUILD_ID"; aws codebuild stop-build --id "$BUILD_ID" >/dev/null 2>&1; exit 130' INT TERM

failures=0
while true; do
  if out=$(aws codebuild batch-get-builds --ids "$BUILD_ID" --query 'builds[0].[buildStatus,currentPhase]' --output text 2>&1); then
    failures=0
    status=${out%%$'\t'*}
    phase=${out##*$'\t'}
    if [ "$status" != "IN_PROGRESS" ]; then
      break
    fi
    printf '  %s ...\n' "$phase"
  else
    failures=$((failures + 1))
    echo "  poll failed ($failures/$MAX_FAILURES): $out" >&2
    if [ "$failures" -ge "$MAX_FAILURES" ]; then
      echo "giving up polling after $MAX_FAILURES consecutive failures; the build keeps running" >&2
      exit 3
    fi
  fi
  sleep "$POLL" &
  wait $!   # interruptible, so the trap fires immediately instead of after the sleep
done

echo "status: $status"
[ "$status" = "SUCCEEDED" ]
