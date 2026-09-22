#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Runs the SFC simulator-to-S3-Tables pipeline, sourcing the modules from whichever is available:
#
#   1. SFC_MODULES_DIR, if you set it
#   2. build/distribution -- a build of this working copy wins, so local changes are what run
#   3. ./modules -- release bundles, downloaded here on first use
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Resolved against the script rather than the working directory, so this runs from anywhere.
CONFIG="$HERE/simulator-to-s3tables.json"

# The modules this example needs: the core, a stand-in for a machine, the Iceberg target, and the
# console target that "#DEBUGTarget" in the config enables.
SFC_REQUIRED_MODULES=(sfc-main simulator aws-s3-tables-target debug-target)

REPO="https://github.com/awslabs/industrial-shopfloor-connect"

# Give up rather than hang when there is no route to GitHub.
CURL_TIMEOUT=20
WGET_TIMEOUT=30

# ---------------------------------------------------------------------------------- prerequisites

# Reports everything that is missing in one go, rather than failing on each tool in turn.
require_tools() {
  local reason="$1" tool missing=()
  shift
  for tool in "$@"; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
  done
  if [ ${#missing[@]} -gt 0 ]; then
    echo "Missing prerequisite(s) for ${reason}: ${missing[*]}" >&2
    for tool in "${missing[@]}"; do
      case "$tool" in
        java) echo "  java  a Java 17+ runtime, e.g. 'brew install --cask temurin' or your distro's JDK" >&2 ;;
        curl) echo "  curl  used to resolve the latest release tag" >&2 ;;
        jq)   echo "  jq    used to read that tag out of the GitHub API response" >&2 ;;
        wget) echo "  wget  used to download the module bundles" >&2 ;;
        tar)  echo "  tar   used to unpack them" >&2 ;;
        *)    echo "  $tool" >&2 ;;
      esac
    done
    return 1
  fi
}

# sfc-main is a JVM process, so java is needed whichever source the modules come from.
require_tools "running SFC" java || exit 1
echo "Using $(java -version 2>&1 | head -1)"

# Region for the AWS-S3-TABLES target. The config file reads it as ${AWS_REGION}, and sfc-main aborts
# with "Placeholder ... could not be replaced" if it is unset. Deploy the cdk/ query app into the
# same region -- DuckDB derives the S3 Tables endpoint from the table bucket's region.
export AWS_REGION="${AWS_REGION:-us-west-2}"
echo "Using AWS_REGION=${AWS_REGION}"

# ----------------------------------------------------------------------------------------- modules

BUILD_DIST="$(cd "$HERE/../../.." && pwd)/build/distribution"
DOWNLOADED="$HERE/modules"

have_all_bundles() {
  local dir="$1" module
  for module in "${SFC_REQUIRED_MODULES[@]}"; do
    [ -d "$dir/$module" ] || [ -f "$dir/$module.tar.gz" ] || return 1
  done
}

# `gradlew build` leaves tar.gz bundles next to any it has already unpacked, so extract whatever is
# still archived. Skipped when the directory is already there, which keeps reruns quick.
extract_missing() {
  local dir="$1" module
  require_tools "unpacking modules" tar || exit 1
  for module in "${SFC_REQUIRED_MODULES[@]}"; do
    if [ ! -d "$dir/$module" ]; then
      echo "  extracting $module"
      tar -xf "$dir/$module.tar.gz" -C "$dir"
    fi
  done
}

# Fetch the precompiled bundles for the latest release. One URL per module rather than brace
# expansion, so a failure names the module that could not be downloaded.
download_modules() {
  local version module
  require_tools "downloading the release bundles" curl jq wget tar || {
    echo "  Alternatively build from source: ./gradlew build in the repository root, which" >&2
    echo "  run-inprocess.sh prefers over the downloads anyway." >&2
    exit 1
  }

  version="${VERSION:-}"
  if [ -z "$version" ]; then
    version="$(curl -fsSL --max-time "$CURL_TIMEOUT" \
      "https://api.github.com/repos/awslabs/industrial-shopfloor-connect/tags" |
      jq -r '.[0].name')" || true
  fi
  if [ -z "$version" ] || [ "$version" = "null" ]; then
    echo "Could not resolve the latest release tag from GitHub." >&2
    echo "  Check network access, or set VERSION=vX.Y.Z and retry." >&2
    exit 1
  fi

  echo "Downloading SFC modules for $version into $DOWNLOADED"
  mkdir -p "$DOWNLOADED"
  for module in "${SFC_REQUIRED_MODULES[@]}"; do
    [ -d "$DOWNLOADED/$module" ] && continue
    echo "  $module"
    if ! wget -q --show-progress --timeout="$WGET_TIMEOUT" --tries=2 \
      -O "$DOWNLOADED/$module.tar.gz" "$REPO/releases/download/$version/$module.tar.gz"; then
      rm -f "$DOWNLOADED/$module.tar.gz"
      echo "Could not download $module for $version." >&2
      exit 1
    fi
    tar -xf "$DOWNLOADED/$module.tar.gz" -C "$DOWNLOADED"
    rm "$DOWNLOADED/$module.tar.gz"
  done
}

if [ -n "${SFC_MODULES_DIR:-}" ]; then
  echo "Using SFC_MODULES_DIR from the environment: $SFC_MODULES_DIR"
elif have_all_bundles "$BUILD_DIST"; then
  echo "Using the local build: $BUILD_DIST"
  extract_missing "$BUILD_DIST"
  export SFC_MODULES_DIR="$BUILD_DIST"
else
  have_all_bundles "$DOWNLOADED" || download_modules
  echo "Using the downloaded release bundles: $DOWNLOADED"
  extract_missing "$DOWNLOADED"
  export SFC_MODULES_DIR="$DOWNLOADED"
fi

if [ ! -x "$SFC_MODULES_DIR/sfc-main/bin/sfc-main" ]; then
  echo "No sfc-main launcher at $SFC_MODULES_DIR/sfc-main/bin/sfc-main" >&2
  exit 1
fi

exec "$SFC_MODULES_DIR/sfc-main/bin/sfc-main" -config "$CONFIG"
