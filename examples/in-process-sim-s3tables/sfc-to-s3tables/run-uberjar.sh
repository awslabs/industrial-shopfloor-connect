#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# The uberjar variant of run-inprocess.sh. Same pipeline, one artifact instead of four:
# sfc-uberjar.tar.gz already contains the core, every adapter and every target, so
# simulator-to-s3tables-uberjar.json names its components by FactoryClassName alone and needs no
# JarFiles paths.
#
# The bundle is sourced from whichever is available:
#
#   1. SFC_UBERJAR_DIR, if you set it (the directory that CONTAINS sfc-uberjar/)
#   2. build/distribution -- a build of this working copy wins, so local changes are what run
#   3. ./uberjar -- the release bundle, downloaded here on first use
#
# Running only ever needs java; curl, jq and wget are needed solely for that third case, so they are
# checked at the point of download rather than up front.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CONFIG="$HERE/simulator-to-s3tables-uberjar.json"

REPO="https://github.com/awslabs/industrial-shopfloor-connect"
BUNDLE="sfc-uberjar.tar.gz"

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
        wget) echo "  wget  used to download the uberjar bundle" >&2 ;;
        tar)  echo "  tar   used to unpack it" >&2 ;;
        *)    echo "  $tool" >&2 ;;
      esac
    done
    return 1
  fi
}

# SFC is a JVM process, so java is needed whichever source the bundle comes from.
require_tools "running SFC" java || exit 1
echo "Using $(java -version 2>&1 | head -1)"

# Region for the AWS-S3-TABLES target. The config file reads it as ${AWS_REGION}, and SFC aborts
# with "Placeholder ... could not be replaced" if it is unset. Deploy the cdk/ query app into the
# same region -- DuckDB derives the S3 Tables endpoint from the table bucket's region.
export AWS_REGION="${AWS_REGION:-us-west-2}"
echo "Using AWS_REGION=${AWS_REGION}"

# ------------------------------------------------------------------------------------- the bundle

BUILD_DIST="$(cd "$HERE/../../.." && pwd)/build/distribution"
DOWNLOADED="$HERE/uberjar"

# Present either already unpacked, or still as the tarball `gradlew build` produced.
have_bundle() {
  local dir="$1"
  [ -d "$dir/sfc-uberjar" ] || [ -f "$dir/$BUNDLE" ]
}

# Skipped when the directory is already there, which keeps reruns quick.
extract_missing() {
  local dir="$1"
  if [ ! -d "$dir/sfc-uberjar" ]; then
    require_tools "unpacking the uberjar bundle" tar || exit 1
    echo "  extracting sfc-uberjar"
    tar -xf "$dir/$BUNDLE" -C "$dir"
  fi
}

download_bundle() {
  local version
  require_tools "downloading the release bundle" curl jq wget tar || {
    echo "  Alternatively build from source: ./gradlew build in the repository root, which" >&2
    echo "  run-uberjar.sh prefers over the download anyway." >&2
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

  # The bundle is a few hundred MB, since it carries every adapter and target.
  echo "Downloading the SFC uberjar for $version into $DOWNLOADED"
  mkdir -p "$DOWNLOADED"
  if ! wget -q --show-progress --timeout="$WGET_TIMEOUT" --tries=2 \
    -O "$DOWNLOADED/$BUNDLE" "$REPO/releases/download/$version/$BUNDLE"; then
    rm -f "$DOWNLOADED/$BUNDLE"
    echo "Could not download $BUNDLE for $version." >&2
    exit 1
  fi
  tar -xf "$DOWNLOADED/$BUNDLE" -C "$DOWNLOADED"
  rm "$DOWNLOADED/$BUNDLE"
}

if [ -n "${SFC_UBERJAR_DIR:-}" ]; then
  echo "Using SFC_UBERJAR_DIR from the environment: $SFC_UBERJAR_DIR"
elif have_bundle "$BUILD_DIST"; then
  echo "Using the local build: $BUILD_DIST"
  extract_missing "$BUILD_DIST"
  export SFC_UBERJAR_DIR="$BUILD_DIST"
else
  have_bundle "$DOWNLOADED" || download_bundle
  echo "Using the downloaded release bundle: $DOWNLOADED"
  extract_missing "$DOWNLOADED"
  export SFC_UBERJAR_DIR="$DOWNLOADED"
fi

LAUNCHER="$SFC_UBERJAR_DIR/sfc-uberjar/bin/sfc-uberjar"
if [ ! -x "$LAUNCHER" ]; then
  echo "No sfc-uberjar launcher at $LAUNCHER" >&2
  exit 1
fi

exec "$LAUNCHER" -config "$CONFIG"
