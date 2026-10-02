#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Runs the SFC integration suite in CodeBuild against the CURRENT WORKING TREE, uncommitted changes
# included. Used both from a developer machine and from GitHub Actions.
#
#   ci/start-build.sh                              # everything, all three modes
#   ci/start-build.sh --tiers core                 # no AWS resources touched
#   ci/start-build.sh --modes uberjar --no-wait
#
# The working tree is zipped and uploaded to S3, then the build is started with
# --source-location-override. No git command is ever run against your checkout.
set -euo pipefail

PROJECT="${SFC_IT_PROJECT:-sfc-integration-test}"
BUCKET="${SFC_IT_BUCKET:-}"
TIERS="${SFC_IT_TIERS:-core,aws}"
MODES="${SFC_IT_MODES:-inprocess,ipc,uberjar}"
WAIT=1

# A correctly-excluded tree is around 25 MB; the ceiling is a deliberate tripwire for a new junk
# directory silently joining every upload rather than an AWS limit.
MAX_ZIP_BYTES=$((75 * 1024 * 1024))

usage() {
  cat <<EOF
Usage: ci/start-build.sh [options]

  --project <name>   CodeBuild project            (env: SFC_IT_PROJECT, default $PROJECT)
  --bucket <name>    artifacts bucket             (env: SFC_IT_BUCKET, required)
  --tiers <list>     core,aws                     (env: SFC_IT_TIERS, default $TIERS)
  --modes <list>     inprocess,ipc,uberjar        (env: SFC_IT_MODES, default $MODES)
  --no-wait          start the build and exit
  -h, --help         this message

The bucket and project names are stack outputs:
  aws cloudformation describe-stacks --stack-name SfcIntegrationTest \\
    --query 'Stacks[0].Outputs' --output table
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --bucket)  BUCKET="$2"; shift 2 ;;
    --tiers)   TIERS="$2"; shift 2 ;;
    --modes)   MODES="$2"; shift 2 ;;
    --no-wait) WAIT=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$BUCKET" ] || { echo "--bucket (or SFC_IT_BUCKET) is required" >&2; exit 2; }
command -v aws >/dev/null || { echo "the aws CLI is required" >&2; exit 2; }
command -v zip >/dev/null || { echo "zip is required" >&2; exit 2; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ------------------------------------------------------------------------------------ package
#
# .git IS included, deliberately. settings.gradle.kts derives the release version from
# `git describe --tags`; without a repository the build falls back to 0.0.0-dev, which works but means
# the artifact under test is not versioned like the real one. Shipping .git keeps them identical.
#
# Every exclude is doubled. zip matches -x patterns against the stored path from the archive root, so
# 'node_modules/*' alone matches ONLY a node_modules at the top level - the ~360 MB of nested
# node_modules under examples/ would sail straight through.
echo "packaging the working tree ..."
( cd "$HERE" && zip -qr "$TMP/src.zip" . \
    -x '*/build/*' -x 'build/*' \
    -x '*/.gradle/*' -x '.gradle/*' \
    -x '*/.kotlin/*' -x '.kotlin/*' \
    -x '*/node_modules/*' -x 'node_modules/*' \
    -x '*/cdk.out/*' -x 'cdk.out/*' \
    -x '*/.idea/*' -x '.idea/*' \
    -x '*/tests/e2e/out/*' -x 'tests/e2e/out/*' \
    -x '*.DS_Store' )

SIZE=$(wc -c < "$TMP/src.zip" | tr -d ' ')
printf 'source archive: %s MB\n' "$((SIZE / 1024 / 1024))"
if [ "$SIZE" -gt "$MAX_ZIP_BYTES" ]; then
  echo "source archive is ${SIZE} bytes, above the ${MAX_ZIP_BYTES} ceiling." >&2
  echo "Something large is no longer being excluded - check for a new build or node_modules directory." >&2
  exit 1
fi

KEY="src/$(date -u +%Y%m%dT%H%M%SZ)-$$.zip"
echo "uploading s3://$BUCKET/$KEY ..."
aws s3 cp "$TMP/src.zip" "s3://$BUCKET/$KEY" --only-show-errors

# ------------------------------------------------------------------------------------ start
#
# Provenance is passed in rather than derived: the source is an S3 zip, so CodeBuild's
# CODEBUILD_RESOLVED_SOURCE_VERSION is not a commit. GitHub Actions supplies the real values; a local
# run reports "local" and marks the tree dirty, which is honest - it is exactly the point of this path.
COMMIT="${SFC_E2E_COMMIT:-local}"
REF="${SFC_E2E_REF:-local}"
DIRTY="${SFC_E2E_DIRTY:-1}"

BUILD_ID=$(aws codebuild start-build \
  --project-name "$PROJECT" \
  --source-type-override S3 \
  --source-location-override "$BUCKET/$KEY" \
  --environment-variables-override \
      "name=SFC_E2E_TIERS,value=$TIERS,type=PLAINTEXT" \
      "name=SFC_E2E_MODES,value=$MODES,type=PLAINTEXT" \
      "name=SFC_E2E_COMMIT,value=$COMMIT,type=PLAINTEXT" \
      "name=SFC_E2E_REF,value=$REF,type=PLAINTEXT" \
      "name=SFC_E2E_DIRTY,value=$DIRTY,type=PLAINTEXT" \
  --query 'build.id' --output text)

echo "build: $BUILD_ID"
echo "console: https://console.aws.amazon.com/codesuite/codebuild/projects/$PROJECT/build/${BUILD_ID//:/%3A}"

if [ "$WAIT" = 0 ]; then
  echo "$BUILD_ID"
  exit 0
fi

# Stop the build if this script is interrupted. Without it a cancelled CI job leaves the build running,
# and it then collides with the build the next push starts.
trap 'echo "stopping $BUILD_ID"; aws codebuild stop-build --id "$BUILD_ID" >/dev/null 2>&1 || true; rm -rf "$TMP"' INT TERM

echo "waiting ..."
while true; do
  read -r STATUS PHASE < <(aws codebuild batch-get-builds --ids "$BUILD_ID" \
    --query 'builds[0].[buildStatus,currentPhase]' --output text)
  [ "$STATUS" = "IN_PROGRESS" ] || break
  printf '  %s ... \r' "$PHASE"
  sleep 15
done

echo "status: $STATUS"
RUN="${BUILD_ID##*:}"
echo "evidence: s3://$BUCKET/evidence/$RUN/"
echo
echo "Fetch the report with:"
echo "  aws s3 cp s3://$BUCKET/evidence/$RUN/ . --recursive --exclude '*' --include '*REPORT.md'"

[ "$STATUS" = "SUCCEEDED" ]
