#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Runs either direction of this example straight out of the uberjar:
#
#   ./run-uberjar.sh server   -- sim-to-opcua.json:   SFC serves OPC UA on port 4841
#   ./run-uberjar.sh client   -- umati-to-debug.json: SFC reads the umati server on port 4840
#
# The point of this example is the uberjar invocation itself: a single `java -jar`, and configs with
# no JarFiles entries, because every adapter and target is already on the jar's own classpath.
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

REPO="https://github.com/awslabs/industrial-shopfloor-connect"
BUNDLE="sfc-uberjar.tar.gz"

# Give up rather than hang when there is no route to GitHub.
CURL_TIMEOUT=20
WGET_TIMEOUT=30

# ------------------------------------------------------------------------------------- which config

usage() {
  cat >&2 <<'EOF'
Usage: ./run-uberjar.sh <server|client> [extra sfc args...]

  server   sim-to-opcua.json    SFC exposes simulated signals as an OPC UA server on port 4841
  client   umati-to-debug.json  SFC reads the umati sample server on port 4840 to the debug target

Anything after the mode is passed through to SFC, e.g. `./run-uberjar.sh client -trace`.
EOF
}

MODE="${1:-}"
[ $# -gt 0 ] && shift
case "$MODE" in
  server) CONFIG="$HERE/sim-to-opcua.json" ;;
  client) CONFIG="$HERE/umati-to-debug.json" ;;
  ""|-h|--help) usage; exit 1 ;;
  *) echo "Unknown mode: $MODE" >&2; echo >&2; usage; exit 1 ;;
esac

# --------------------------------------------------------------------------------- prerequisites

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

require_tools "running SFC" java || exit 1
echo "Using $(java -version 2>&1 | head -1)"

# The client config connects to opc.tcp://localhost:4840, which is the umati sample server rather
# than anything SFC starts. Say so up front instead of letting it fail as a connection timeout.
if [ "$MODE" = "client" ] && ! (exec 3<>/dev/tcp/localhost/4840) 2>/dev/null; then
  echo "Nothing is listening on port 4840. Start the umati sample server first:" >&2
  echo "  docker run -d -p 4840:4840 ghcr.io/umati/sample-server:main" >&2
  exit 1
fi

# ------------------------------------------------------------------------------------- the bundle

BUILD_DIST="$(cd "$HERE/../.." && pwd)/build/distribution"
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
  SFC_UBERJAR_DIR="$BUILD_DIST"
else
  have_bundle "$DOWNLOADED" || download_bundle
  echo "Using the downloaded release bundle: $DOWNLOADED"
  extract_missing "$DOWNLOADED"
  SFC_UBERJAR_DIR="$DOWNLOADED"
fi
export SFC_UBERJAR_DIR

# ------------------------------------------------------------------------------------------- run

# The version is part of the filename, so resolve it rather than hardcoding it.
UBERJAR=$(find "$SFC_UBERJAR_DIR/sfc-uberjar/lib" -maxdepth 1 -name 'sfc-uberjar-*.jar' | head -1)
if [ -z "$UBERJAR" ]; then
  echo "No sfc-uberjar-<version>.jar under $SFC_UBERJAR_DIR/sfc-uberjar/lib" >&2
  exit 1
fi

# Default to -info, but only when the caller has not chosen a level themselves -- passing both
# would leave which one wins up to argument order.
LEVEL=(-info)
for arg in "$@"; do
  case "$arg" in
    -trace|-info|-warning|-error) LEVEL=() ; break ;;
  esac
done

# One jar, one config, no JarFiles -- that is the whole uberjar story.
echo "Running $(basename "$UBERJAR") with $(basename "$CONFIG")"
exec java -jar "$UBERJAR" -config "$CONFIG" "${LEVEL[@]}" "$@"
