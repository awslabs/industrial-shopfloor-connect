#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Runs the SFC integration suite in CodeBuild against the CURRENT WORKING TREE, uncommitted changes
# included. Used from a developer machine and from GitHub Actions.
#
#   ci/start-build.sh                         # push profile, all tiers, all three modes, then wait
#   ci/start-build.sh --profile full
#   ci/start-build.sh --tiers core --modes uberjar
#   ci/start-build.sh --no-wait               # print the build id and exit
#
# The tree is zipped and uploaded to S3, then the build starts with --source-location-override. No git
# command is ever run against your checkout.
#
# The test build runs on the suite's image (ci/cdk/image/Dockerfile), tagged in ECR with the hash of the
# Dockerfile and the two files it copies. When ECR has no image with the current tag, the image is built
# first, in AWS, by the image project - on the first run and after any change to those files.
set -euo pipefail

PROJECT="${SFC_IT_PROJECT:-sfc-integration-test}"
IMAGE_PROJECT="${SFC_IT_IMAGE_PROJECT:-sfc-integration-test-image}"
IMAGE_REPO="${SFC_IT_IMAGE_REPO:-sfc-it-ci-image}"
BUCKET="${SFC_IT_BUCKET:-}"
PROFILE="${SFC_IT_PROFILE:-push}"
TIERS="${SFC_IT_TIERS:-}"
MODES="${SFC_IT_MODES:-}"
WAIT=1

# A correctly excluded tree is about 35 MB. The ceiling is a tripwire for a new junk directory silently
# joining every upload, not an AWS limit.
MAX_ZIP_BYTES=$((75 * 1024 * 1024))

usage() {
  cat <<EOF
Usage: ci/start-build.sh [options]

  --project <name>   CodeBuild project             (env SFC_IT_PROJECT, default $PROJECT)
  --bucket <name>    artifacts bucket              (env SFC_IT_BUCKET, required: the ArtifactsBucket output)
  --profile <p>      push | full                   (env SFC_IT_PROFILE, default $PROFILE)
  --tiers <list>     core,local-infra,aws          (env SFC_IT_TIERS, default: all)
  --modes <list>     inprocess,ipc,uberjar         (env SFC_IT_MODES, default: all)
  --no-wait          start the build and exit
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --bucket)  BUCKET="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --tiers)   TIERS="$2"; shift 2 ;;
    --modes)   MODES="$2"; shift 2 ;;
    --no-wait) WAIT=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$BUCKET" ] || { echo "--bucket (or SFC_IT_BUCKET) is required - it is the ArtifactsBucket stack output" >&2; exit 2; }
for tool in aws zip python3; do command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 2; }; done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ------------------------------------------------------------------------------------------ package
# .git IS included: settings.gradle.kts derives the version from `git describe --tags`, and shipping
# .git keeps the build's version identical to a local one. Every exclude is doubled because zip matches
# -x patterns against the path from the archive root: 'node_modules/*' alone matches only a top-level
# node_modules, and the nested ones under examples/ are about 4.8 GB.
echo "packaging the working tree ..."
( cd "$HERE" && zip -qr "$TMP/src.zip" . \
    -x '*/build/*' -x 'build/*' -x '*/.gradle/*' -x '.gradle/*' -x '*/.kotlin/*' -x '.kotlin/*' \
    -x '*/node_modules/*' -x 'node_modules/*' -x '*/cdk.out/*' -x 'cdk.out/*' -x '*/.idea/*' -x '.idea/*' \
    -x 'ci/e2e/out/*' -x 'e2e-out/*' -x '*/__pycache__/*' -x '*.pyc' -x '*.DS_Store' )

SIZE=$(wc -c < "$TMP/src.zip" | tr -d ' ')
printf 'source archive: %s MB\n' "$((SIZE / 1024 / 1024))"
if [ "$SIZE" -gt "$MAX_ZIP_BYTES" ]; then
  echo "source archive is $SIZE bytes, above the $MAX_ZIP_BYTES ceiling - check for a new build or node_modules directory" >&2
  exit 1
fi

KEY="src/$(date -u +%Y%m%dT%H%M%SZ)-$$.zip"
aws s3 cp "$TMP/src.zip" "s3://$BUCKET/$KEY" --only-show-errors

# -------------------------------------------------------------------------------------------- image
IMAGE_TAG=$(python3 - "$HERE" <<'PY'
import hashlib, sys
from pathlib import Path
root = Path(sys.argv[1])
h = hashlib.sha256()
for rel in ("ci/cdk/image/Dockerfile", "ci/e2e/requirements.txt", "ci/e2e/lib/install_kafka.py"):
    h.update(rel.encode() + b"\0" + (root / rel).read_bytes())
print(h.hexdigest()[:16])
PY
)
REPO_URI=$(aws ecr describe-repositories --repository-names "$IMAGE_REPO" --query 'repositories[0].repositoryUri' --output text)
if aws ecr describe-images --repository-name "$IMAGE_REPO" --image-ids imageTag="$IMAGE_TAG" >/dev/null 2>&1; then
  echo "build image: $REPO_URI:$IMAGE_TAG"
else
  echo "build image $IMAGE_TAG is not in ECR yet - building it in AWS first (about 10-15 minutes) ..."
  IMAGE_BUILD_ID=$(aws codebuild start-build --project-name "$IMAGE_PROJECT" \
    --source-type-override S3 --source-location-override "$BUCKET/$KEY" \
    --environment-variables-override "[{\"name\": \"IMAGE_TAG\", \"value\": \"$IMAGE_TAG\", \"type\": \"PLAINTEXT\"}]" \
    --query 'build.id' --output text)
  echo "image build: $IMAGE_BUILD_ID"
  "$HERE/ci/wait-build.sh" "$IMAGE_BUILD_ID"
fi

# -------------------------------------------------------------------------------------------- start
# Environment overrides as JSON. The CLI's shorthand syntax splits a value at commas, so
# "value=inprocess,ipc,uberjar" became a list and the call was rejected.
OVERRIDES=$(python3 - "$PROFILE" "$TIERS" "$MODES" "${SFC_E2E_COMMIT:-local}" "${SFC_E2E_REF:-local}" "${SFC_E2E_DIRTY:-1}" <<'PY'
import json, sys
profile, tiers, modes, commit, ref, dirty = sys.argv[1:7]
pairs = {"SFC_E2E_PROFILE": profile, "SFC_E2E_COMMIT": commit, "SFC_E2E_REF": ref, "SFC_E2E_DIRTY": dirty}
if tiers:
    pairs["SFC_E2E_TIERS"] = tiers
if modes:
    pairs["SFC_E2E_MODES"] = modes
print(json.dumps([{"name": k, "value": v, "type": "PLAINTEXT"} for k, v in pairs.items()]))
PY
)

BUILD_ID=$(aws codebuild start-build --project-name "$PROJECT" \
  --source-type-override S3 --source-location-override "$BUCKET/$KEY" \
  --environment-variables-override "$OVERRIDES" \
  --image-override "$REPO_URI:$IMAGE_TAG" --image-pull-credentials-type-override SERVICE_ROLE \
  --query 'build.id' --output text)

echo "build: $BUILD_ID"
# Written immediately, so a later failure or cancellation still knows which build to stop and fetch.
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "build_id=$BUILD_ID" >> "$GITHUB_OUTPUT"
fi
echo "evidence: s3://$BUCKET/evidence/${BUILD_ID##*:}/"

if [ "$WAIT" = 1 ]; then
  exec "$HERE/ci/wait-build.sh" "$BUILD_ID"
fi
