#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# sfcup - install Shop Floor Connectivity from a single command.
#
#   curl -fsSL https://raw.githubusercontent.com/awslabs/industrial-shopfloor-connect/main/sfcup.sh | bash
#
# Installs the SFC uberjar - the core plus every protocol adapter and target in one jar - into
# ~/.sfc, and puts `sfcx` on PATH. Re-run it (or the installed `sfcup`) to upgrade.
#
# Two AWS modes publish the same sfc-uberjar.tar.gz to an AWS account instead of installing it:
# --aws-ecr builds the sfcx container image and pushes it to Amazon ECR, --aws-greengrass creates an
# AWS IoT Greengrass v2 component. Both need the AWS CLI v2; --aws-ecr also docker, podman or finch.
#
# Dependencies: java 17+, tar, and either curl or wget. No jq: the latest release is resolved from
# GitHub's own redirect rather than the JSON API, which also avoids the API's unauthenticated
# rate limit.
set -euo pipefail

SFCUP_VERSION="1.0.0"

REPO_SLUG="awslabs/industrial-shopfloor-connect"
REPO="https://github.com/$REPO_SLUG"
BUNDLE="sfc-uberjar.tar.gz"

# The directory inside the tarball, and the launcher inside that.
BUNDLE_DIR="sfc-uberjar"
LAUNCHER="bin/sfc-uberjar"

# Minimum JVM. The uberjar is compiled to bytecode 17, so anything older dies with
# UnsupportedClassVersionError rather than a useful message.
MIN_JAVA=17

# Marker used to keep the shell rc edits idempotent, and to find them again on uninstall.
RC_BEGIN="# >>> sfc >>>"
RC_END="# <<< sfc <<<"

# Give up rather than hang when there is no route to GitHub.
NET_TIMEOUT=30

# ------------------------------------------------------------------------------------- arguments

SFC_HOME="${SFC_HOME:-$HOME/.sfc}"
WANT_VERSION="${SFC_VERSION:-}"
MODIFY_PATH=1
KEEP_OLD=0
FORCE=0
FROM_LOCAL=0
DO_UNINSTALL=0

# AWS modes (empty: install).
AWS_MODE=""
AWS_OPT_REGION=""
ECR_REPO="sfcx"
IMAGE_TAG=""
PLATFORM=""
GG_BUCKET=""
GG_COMPONENT="com.amazonaws.sfc.Sfcx"
GG_COMPONENT_VERSION=""
DRY_RUN=0

usage() {
  cat <<EOF
sfcup $SFCUP_VERSION - install Shop Floor Connectivity

Usage: sfcup.sh [options]

  --version <tag>     install a specific release, e.g. v1.11.0    (env: SFC_VERSION)
  --dir <path>        install root, default ~/.sfc                (env: SFC_HOME)
  --local             install from build/distribution/$BUNDLE in a source checkout
  --keep-old          keep the previous version instead of removing it
  --no-modify-path    do not touch shell startup files
  --force             reinstall even if this version is already current
  --uninstall         remove the installation and the shell startup entry
  -h, --help          show this message
  -V, --sfcup-version print the version of this installer

After installing, \`sfcx\` is on PATH and takes the usual SFC options:

  sfcx -config example.json -info

AWS modes - publish the same $BUNDLE to your AWS account; nothing is installed locally:

  --aws-ecr                   build the sfcx container image and push it to Amazon ECR
                              (needs the AWS CLI v2 and docker, podman or finch)
    --repo <name>             ECR repository, default sfcx (created if missing)
    --tag <tag>               image tag, default the SFC version
    --platform <platform>     build for another platform, e.g. linux/amd64
  --aws-greengrass            create an AWS IoT Greengrass v2 component (needs the AWS CLI v2);
                              its default configuration runs the simulator to the debug target
    --bucket <name>           S3 bucket for the jar, default sfcx-greengrass-<account>-<region>
                              (created if missing)
    --component <name>        component name, default com.amazonaws.sfc.Sfcx
    --component-version <v>   x.y.z, default the release version
  --region <region>           AWS region, default AWS_REGION, AWS_DEFAULT_REGION or aws configure
  --dry-run                   show the generated Dockerfile or recipe; build and create nothing

  --version and --local choose the bundle for the AWS modes too.
EOF
}

# Checked before use so a missing argument reports cleanly instead of via bash's ${x:?} message.
need_arg() { [ -n "${2:-}" ] || { echo "sfcup: $1 needs an argument" >&2; exit 2; }; }

while [ $# -gt 0 ]; do
  case "$1" in
    --version)          need_arg "$1" "${2:-}"; WANT_VERSION="$2"; shift 2 ;;
    --version=*)        WANT_VERSION="${1#*=}"; shift ;;
    --dir)              need_arg "$1" "${2:-}"; SFC_HOME="$2"; shift 2 ;;
    --dir=*)            SFC_HOME="${1#*=}"; shift ;;
    --local)            FROM_LOCAL=1; shift ;;
    --keep-old)         KEEP_OLD=1; shift ;;
    --no-modify-path)   MODIFY_PATH=0; shift ;;
    --force)            FORCE=1; shift ;;
    --uninstall)        DO_UNINSTALL=1; shift ;;
    --aws-ecr)          AWS_MODE=${AWS_MODE:+both}; AWS_MODE=${AWS_MODE:-ecr}; shift ;;
    --aws-greengrass)   AWS_MODE=${AWS_MODE:+both}; AWS_MODE=${AWS_MODE:-greengrass}; shift ;;
    --region)           need_arg "$1" "${2:-}"; AWS_OPT_REGION="$2"; shift 2 ;;
    --region=*)         AWS_OPT_REGION="${1#*=}"; shift ;;
    --repo)             need_arg "$1" "${2:-}"; ECR_REPO="$2"; shift 2 ;;
    --repo=*)           ECR_REPO="${1#*=}"; shift ;;
    --tag)              need_arg "$1" "${2:-}"; IMAGE_TAG="$2"; shift 2 ;;
    --tag=*)            IMAGE_TAG="${1#*=}"; shift ;;
    --platform)         need_arg "$1" "${2:-}"; PLATFORM="$2"; shift 2 ;;
    --platform=*)       PLATFORM="${1#*=}"; shift ;;
    --bucket)           need_arg "$1" "${2:-}"; GG_BUCKET="$2"; shift 2 ;;
    --bucket=*)         GG_BUCKET="${1#*=}"; shift ;;
    --component)        need_arg "$1" "${2:-}"; GG_COMPONENT="$2"; shift 2 ;;
    --component=*)      GG_COMPONENT="${1#*=}"; shift ;;
    --component-version)   need_arg "$1" "${2:-}"; GG_COMPONENT_VERSION="$2"; shift 2 ;;
    --component-version=*) GG_COMPONENT_VERSION="${1#*=}"; shift ;;
    --dry-run)          DRY_RUN=1; shift ;;
    -h|--help)          usage; exit 0 ;;
    -V|--sfcup-version) echo "sfcup $SFCUP_VERSION"; exit 0 ;;
    *) echo "sfcup: unknown option '$1'" >&2; echo >&2; usage >&2; exit 2 ;;
  esac
done
[ "$AWS_MODE" != both ] || { echo "sfcup: choose one of --aws-ecr and --aws-greengrass" >&2; exit 2; }
if [ -n "$AWS_MODE" ] && [ "$DO_UNINSTALL" = 1 ]; then
  echo "sfcup: --uninstall cannot be combined with an AWS mode" >&2; exit 2
fi
if [ "$DRY_RUN" = 1 ] && [ -z "$AWS_MODE" ]; then
  echo "sfcup: --dry-run needs --aws-ecr or --aws-greengrass" >&2; exit 2
fi

# ------------------------------------------------------------------------------------- reporting

# Colour only when stdout is a terminal, so piped output and logs stay clean.
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_DIM=$'\033[2m'; C_B=$'\033[1m'; C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_0=$'\033[0m'
else
  C_DIM=""; C_B=""; C_OK=""; C_WARN=""; C_ERR=""; C_0=""
fi

say()  { printf '%s\n' "$*"; }
step() { printf '%s\n' "${C_DIM}·${C_0} $*"; }
ok()   { printf '%s\n' "${C_OK}✓${C_0} $*"; }
warn() { printf '%s\n' "${C_WARN}!${C_0} $*" >&2; }
die()  { printf '%s\n' "${C_ERR}✗${C_0} $*" >&2; exit 1; }

# ----------------------------------------------------------------------------------- prerequisites

have() { command -v "$1" >/dev/null 2>&1; }

# curl and wget are interchangeable here; require one, and remember which.
DOWNLOADER=""
pick_downloader() {
  if have curl; then DOWNLOADER=curl
  elif have wget; then DOWNLOADER=wget
  else
    die "need curl or wget to download the release.
  Install either, or use --local against a source checkout."
  fi
}

# Fetch a URL to a file. Both branches fail loudly on an HTTP error rather than writing an error page.
fetch() {
  local url="$1" out="$2"
  case "$DOWNLOADER" in
    curl) curl -fSL --progress-bar --connect-timeout 10 --max-time "$((NET_TIMEOUT * 30))" -o "$out" "$url" ;;
    wget) wget -q --show-progress --timeout="$NET_TIMEOUT" --tries=2 -O "$out" "$url" ;;
  esac
}

# Same, but quietly to stdout - used for the small checksum file.
fetch_stdout() {
  local url="$1"
  case "$DOWNLOADER" in
    curl) curl -fsSL --max-time "$NET_TIMEOUT" "$url" ;;
    wget) wget -qO- --timeout="$NET_TIMEOUT" --tries=2 "$url" ;;
  esac
}

# Parse the major version out of `java -version`, handling both "21.0.11" and the old "1.8.0_402".
java_major() {
  local v
  v=$(java -version 2>&1 | head -1) || return 1
  v=${v#*\"}; v=${v%%\"*}
  local maj=${v%%.*}
  if [ "$maj" = "1" ]; then
    local rest=${v#1.}
    maj=${rest%%.*}
  fi
  printf '%s' "$maj"
}

check_java() {
  if ! have java; then
    # Not fatal: someone may be provisioning a machine and install a JVM afterwards.
    warn "java not found on PATH. SFC needs a Java $MIN_JAVA+ runtime to run.
  e.g. 'brew install --cask temurin' on macOS, or your distribution's JDK package."
    return 0
  fi
  local maj
  maj=$(java_major) || { warn "could not determine the Java version; continuing"; return 0; }
  case "$maj" in
    ''|*[!0-9]*) warn "could not parse the Java version ('$maj'); continuing" ;;
    *) if [ "$maj" -lt "$MIN_JAVA" ]; then
         die "Java $maj found, but SFC needs $MIN_JAVA or newer.
  The uberjar is compiled to bytecode $MIN_JAVA; an older JVM fails with UnsupportedClassVersionError."
       fi
       step "java $maj" ;;
  esac
}

# ------------------------------------------------------------------------------------- uninstall

uninstall() {
  [ -d "$SFC_HOME" ] || die "nothing installed at $SFC_HOME"

  # Strip the managed block from any startup file that has it, leaving everything else untouched.
  local rc removed=0
  for rc in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.zshrc" "$HOME/.zshenv"; do
    [ -f "$rc" ] || continue
    grep -qF "$RC_BEGIN" "$rc" || continue
    # sed -i is not portable (GNU vs BSD differ on the backup suffix), so rewrite via a temp file.
    local tmp="$rc.sfcup.$$"
    awk -v b="$RC_BEGIN" -v e="$RC_END" '
      $0 == b { skip = 1; next }
      $0 == e { skip = 0; next }
      !skip   { print }
    ' "$rc" > "$tmp" && mv -f "$tmp" "$rc"
    step "removed the sfc block from ${rc/#$HOME/~}"
    removed=1
  done
  [ "$removed" = 1 ] || step "no shell startup entry found"

  rm -rf "$SFC_HOME"
  ok "removed ${SFC_HOME/#$HOME/~}"
  say ""
  say "Open a new shell, or run:  ${C_B}hash -r${C_0}"
}

if [ "$DO_UNINSTALL" = 1 ]; then
  uninstall
  exit 0
fi

# --------------------------------------------------------------------------------- resolve version

# GitHub redirects /releases/latest/download/<asset> to the concrete tag, so the tag can be read
# straight out of the Location header. No JSON, no jq, and no API rate limit.
resolve_latest() {
  local url="$REPO/releases/latest/download/$BUNDLE" location=""
  case "$DOWNLOADER" in
    curl) location=$(curl -sI --max-time "$NET_TIMEOUT" "$url" \
                     | tr -d '\r' | awk 'tolower($1) == "location:" { print $2; exit }') ;;
    wget) location=$(wget -qS --max-redirect=0 --timeout="$NET_TIMEOUT" -O /dev/null "$url" 2>&1 \
                     | tr -d '\r' | awk 'tolower($1) == "location:" { print $2; exit }') ;;
  esac
  [ -n "$location" ] || return 1
  # .../releases/download/v1.11.0/sfc-uberjar.tar.gz  ->  v1.11.0
  local tail=${location##*/releases/download/}
  printf '%s' "${tail%%/*}"
}

# ------------------------------------------------------------------------------------- the bundle

# Fetch $BUNDLE into $TMP - copied with --local, else downloaded and checked against the published
# sha512 - and unpack it there. The install and both AWS modes use this one verified bundle.
fetch_bundle() {
  if [ "$FROM_LOCAL" = 1 ]; then
    cp "$SRC_TARBALL" "$TMP/$BUNDLE"
  else
    local base expected actual
    if [ -n "$WANT_VERSION" ]; then
      base="$REPO/releases/download/$VERSION"
    else
      base="$REPO/releases/latest/download"
    fi

    say ""
    step "downloading $BUNDLE"
    fetch "$base/$BUNDLE" "$TMP/$BUNDLE" \
      || die "could not download $BUNDLE for $VERSION.
  Check that the release exists: $REPO/releases"

    # Verify against the checksum the release workflow publishes next to each tarball. Treated as
    # best-effort: a missing checksum tool is a warning, a mismatching checksum is fatal.
    if fetch_stdout "$base/$BUNDLE.sha512sum" > "$TMP/$BUNDLE.sha512sum" 2>/dev/null \
       && [ -s "$TMP/$BUNDLE.sha512sum" ]; then
      expected=$(awk '{ print $1; exit }' "$TMP/$BUNDLE.sha512sum")
      actual=""
      if   have sha512sum; then actual=$(sha512sum    "$TMP/$BUNDLE" | awk '{print $1}')
      elif have shasum;    then actual=$(shasum -a 512 "$TMP/$BUNDLE" | awk '{print $1}')
      elif have openssl;   then actual=$(openssl dgst -sha512 "$TMP/$BUNDLE" | awk '{print $NF}')
      fi
      if [ -z "$actual" ]; then
        # macOS has no sha512sum; shasum and openssl are the usual stand-ins. None of the three is
        # guaranteed, so skip rather than block the install.
        warn "no sha512 tool found (sha512sum, shasum or openssl) — skipping checksum verification"
      elif [ "$actual" != "$expected" ]; then
        die "checksum mismatch for $BUNDLE — refusing to use it.
  expected $expected
  actual   $actual"
      else
        step "sha512 verified"
      fi
    else
      warn "no published checksum for $VERSION — skipping verification"
    fi
  fi

  step "unpacking"
  have tar || die "need tar to unpack the bundle"
  tar -xf "$TMP/$BUNDLE" -C "$TMP"
  [ -x "$TMP/$BUNDLE_DIR/$LAUNCHER" ] || die "unexpected bundle layout: no $BUNDLE_DIR/$LAUNCHER inside $BUNDLE"
}

# The uberjar inside the unpacked bundle; its name carries the version, so it is resolved, not assumed.
bundle_jar() {
  local jar
  jar=$(find "$TMP/$BUNDLE_DIR/lib" -maxdepth 1 -name 'sfc-uberjar-*.jar' 2>/dev/null | head -1)
  [ -n "$jar" ] || die "no sfc-uberjar-<version>.jar inside $BUNDLE"
  printf '%s' "$jar"
}

# ------------------------------------------------------------------------------------- AWS modes

# Every IPC service in the uberjar, as "<name> <main class>": the name is the module's directory, the
# class that module's application mainClass (adapters/*/build.gradle.kts, targets/*/build.gradle.kts).
IPC_SERVICES="ads com.amazonaws.sfc.ads.AdsProtocolService
j1939 com.amazonaws.sfc.j1939.J1939ProtocolService
modbus-tcp com.amazonaws.sfc.modbus.tcp.ModbusTcpProtocolService
mqtt com.amazonaws.sfc.mqtt.MqttProtocolService
nats com.amazonaws.sfc.nats.NatsProtocolService
opcua com.amazonaws.sfc.opcua.OpcuaProtocolService
pccc com.amazonaws.sfc.pccc.PcccProtocolService
rest com.amazonaws.sfc.rest.RestProtocolService
s7 com.amazonaws.sfc.s7.S7ProtocolService
simulator com.amazonaws.sfc.simulator.SimulatorService
slmp com.amazonaws.sfc.slmp.SlmpProtocolService
snmp com.amazonaws.sfc.snmp.SnmpProtocolService
sql com.amazonaws.sfc.sql.SqlProtocolService
aws-iot-core-target com.amazonaws.sfc.awsiotcore.AwsIotCoreTargetService
aws-kinesis-firehose-target com.amazonaws.sfc.awsfirehose.AwsKinesisFirehoseTargetService
aws-kinesis-target com.amazonaws.sfc.awskinesis.AwsKinesisTargetService
aws-lambda-target com.amazonaws.sfc.awslambda.AwsLambdaTargetService
aws-msk-target com.amazonaws.sfc.awsmsk.AwsMskTargetService
aws-s3-tables-target com.amazonaws.sfc.awss3tables.AwsS3TablesTargetService
aws-s3-target com.amazonaws.sfc.awss3.AwsS3TargetService
aws-sitewise-target com.amazonaws.sfc.awssitewise.AwsSitewiseTargetService
aws-sitewiseedge-target com.amazonaws.sfc.awssitewiseedge.SiteWiseEdgeTargetService
aws-sns-target com.amazonaws.sfc.awssns.AwsSnsTargetService
aws-sqs-target com.amazonaws.sfc.awssqs.AwsSqsTargetService
debug-target com.amazonaws.sfc.debugtarget.DebugTargetService
file-target com.amazonaws.sfc.filetarget.FileTargetService
mqtt-target com.amazonaws.sfc.mqtt.MqttTargetService
nats-target com.amazonaws.sfc.natstarget.NatsTargetService
opcua-target com.amazonaws.sfc.opcuatarget.OpcuaTargetService
opcua-writer-target com.amazonaws.sfc.opcuawritetarget.OpcuaWriterTargetService
router-target com.amazonaws.sfc.router.AwsRouterTargetService
store-forward-target com.amazonaws.sfc.storeforward.AwsStoreForwardTargetService"

# The Greengrass component's default configuration: the simulator to the debug target, the same
# configuration as the first example in README.md (uberjar style: FactoryClassName only).
DEFAULT_CONFIG='{
  "AWSVersion": "2022-04-02",
  "Name": "Simulator to console",
  "Version": 1,
  "LogLevel": "Info",
  "Schedules": [
    {
      "Name": "SimSchedule",
      "Interval": 1000,
      "Active": true,
      "TimestampLevel": "Both",
      "Sources": { "Simulator": ["*"] },
      "Targets": ["DebugTarget"]
    }
  ],
  "Sources": {
    "Simulator": {
      "Name": "Sim",
      "ProtocolAdapter": "SimulatorAdapter",
      "Channels": {
        "sinus":    { "Simulation": { "SimulationType": "Sinus",    "DataType": "Double", "Min": 0, "Max": 100  } },
        "triangle": { "Simulation": { "SimulationType": "Triangle", "DataType": "Double", "Min": 0, "Max": 100  } },
        "sawtooth": { "Simulation": { "SimulationType": "Sawtooth", "DataType": "Double", "Min": 0, "Max": 100  } },
        "square":   { "Simulation": { "SimulationType": "Square",   "DataType": "Double", "Min": 0, "Max": 100  } },
        "random":   { "Simulation": { "SimulationType": "Random",   "DataType": "Byte",   "Min": 0, "Max": 100  } },
        "counter":  { "Simulation": { "SimulationType": "Counter",  "DataType": "Int",    "Min": 0, "Max": 1000 } }
      }
    }
  },
  "Targets": {
    "DebugTarget": { "Active": true, "TargetType": "DEBUG-TARGET" }
  },
  "TargetTypes": {
    "DEBUG-TARGET": { "FactoryClassName": "com.amazonaws.sfc.debugtarget.DebugTargetWriter" }
  },
  "ProtocolAdapters": {
    "SimulatorAdapter": { "AdapterType": "SIMULATOR" }
  },
  "AdapterTypes": {
    "SIMULATOR": { "FactoryClassName": "com.amazonaws.sfc.simulator.SimulatorAdapter" }
  }
}'

# Values end up in generated files and AWS names, so each is checked against what AWS accepts.
valid() { printf '%s' "$2" | grep -Eq "$3" || die "invalid $1: '$2'"; }

aws_region() {
  local r="${AWS_OPT_REGION:-${AWS_REGION:-${AWS_DEFAULT_REGION:-}}}"
  if [ -z "$r" ] && have aws; then r=$(aws configure get region 2>/dev/null || true); fi
  printf '%s' "$r"
}

# Region and account for a real run: both are needed for every AWS name below.
aws_context() {
  have aws || die "need the AWS CLI v2 (aws) on PATH"
  REGION=$(aws_region)
  [ -n "$REGION" ] || die "no AWS region: pass --region, or set AWS_REGION"
  ACCOUNT=$(aws sts get-caller-identity --query Account --output text) \
    || die "the AWS CLI has no usable credentials (aws sts get-caller-identity failed)"
  step "AWS account $ACCOUNT, region $REGION"
}

# The image's build context: the jar from the bundle, the Dockerfile and three small scripts, plus a
# usage text. The scripts are POSIX sh, so the image needs nothing beyond the Corretto base.
write_image_context() {
  local dir="$1" jar="$2" name cls
  mkdir -p "$dir"
  mv "$jar" "$dir/sfc-uberjar.jar"

  sed "s|@@VERSION@@|$VERSION|g; s|@@SFCUP@@|$SFCUP_VERSION|g" > "$dir/Dockerfile" <<'EOF'
# Generated by sfcup @@SFCUP@@ from sfc-uberjar.tar.gz (SFC @@VERSION@@).
FROM public.ecr.aws/amazoncorretto/amazoncorretto:21
LABEL org.opencontainers.image.title="sfcx" \
      org.opencontainers.image.version="@@VERSION@@" \
      org.opencontainers.image.source="https://github.com/awslabs/industrial-shopfloor-connect"
COPY sfc-uberjar.jar USAGE.txt /opt/sfc/
COPY entrypoint sfcx ipc /usr/local/bin/
RUN chmod 0755 /usr/local/bin/entrypoint /usr/local/bin/sfcx /usr/local/bin/ipc
WORKDIR /opt/sfc
ENTRYPOINT ["/usr/local/bin/entrypoint"]
EOF

  cat > "$dir/sfcx" <<'EOF'
#!/bin/sh
# Generated by sfcup: sfc-main from the uberjar.
exec java ${JAVA_OPTS:-} -cp /opt/sfc/sfc-uberjar.jar com.amazonaws.sfc.MainController "$@"
EOF

  cat > "$dir/entrypoint" <<'EOF'
#!/bin/sh
# Generated by sfcup. Without a known first word the arguments go to sfc-main; see: docker run IMAGE help
case "${1:-}" in
  help|-h|--help) exec cat /opt/sfc/USAGE.txt ;;
  ipc)            shift; exec /usr/local/bin/ipc "$@" ;;
  sh|bash)        exec "$@" ;;
  "")             [ -n "${SFC_CONFIG:-}" ] && exec /usr/local/bin/sfcx
                  exec cat /opt/sfc/USAGE.txt ;;
  *)              exec /usr/local/bin/sfcx "$@" ;;
esac
EOF

  {
    cat <<'EOF'
#!/bin/sh
# Generated by sfcup. Runs one SFC IPC service from the uberjar:  ipc <service> -port <port> [options]
case "${1:-list}" in
  list|-h|--help)
    echo "IPC services in this image - run one with: ipc <service> -port <port>"
EOF
    while read -r name cls; do printf '    echo "  %-28s %s"\n' "$name" "$cls"; done <<< "$IPC_SERVICES"
    printf '    exit 0 ;;\n'
    while read -r name cls; do printf '  %s) cls=%s ;;\n' "$name" "$cls"; done <<< "$IPC_SERVICES"
    cat <<'EOF'
  *) echo "ipc: unknown service '$1' - run: ipc list" >&2; exit 2 ;;
esac
shift
exec java ${JAVA_OPTS:-} -cp /opt/sfc/sfc-uberjar.jar "$cls" "$@"
EOF
  } > "$dir/ipc"

  {
    sed "s|@@VERSION@@|$VERSION|g" <<'EOF'
sfcx @@VERSION@@ - Shop Floor Connectivity in one image, built by sfcup from sfc-uberjar.tar.gz

/opt/sfc/sfc-uberjar.jar holds sfc-main plus every protocol adapter and target. In this jar a
component is named by its FactoryClassName alone: AdapterTypes and TargetTypes need no JarFiles.

SFC-MAIN (the default)
  docker run --rm -v "$PWD:/cfg" IMAGE -config /cfg/sfc-config.json -info
  docker run --rm -e SFC_CONFIG="$(cat sfc-config.json)" IMAGE
      without -config, sfc-main reads its configuration from the SFC_CONFIG variable
  log level:  -info | -warning | -error | -trace        plain output:  -nocolor

IPC SERVICES (one protocol adapter or target per container)
  docker run --rm IMAGE ipc list
  docker run --rm -p 50000:50000 IMAGE ipc opcua -port 50000
  options:  -port <port> or -envport <variable holding the port>, -connection <type>,
            -cert <file> -key <file> -ca <file>; adapters also -adapter <id>, targets -target <id>
  sfc-main reaches a service through AdapterServers / TargetServers (Address and Port) and
  ProtocolAdapters.<id>.AdapterServer / Targets.<id>.TargetServer in its configuration.

OTHER
  docker run --rm IMAGE help          this text
  docker run --rm -it IMAGE sh        a shell in the image
  -e JAVA_OPTS="-Xmx512m"             JVM options for sfc-main and every IPC service

EOF
    printf 'IPC SERVICES IN THIS IMAGE\n'
    while read -r name cls; do printf '  %-28s %s\n' "$name" "$cls"; done <<< "$IPC_SERVICES"
  } > "$dir/USAGE.txt"
}

aws_ecr() {
  local tag="${IMAGE_TAG:-$VERSION}" ctx="$TMP/image" builder="" registry image b
  valid "--repo" "$ECR_REPO" '^[a-z0-9]+([._/-][a-z0-9]+)*$'
  valid "--tag" "$tag" '^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$'
  write_image_context "$ctx" "$(bundle_jar)"

  if [ "$DRY_RUN" = 1 ]; then
    say ""; say "${C_B}Dockerfile${C_0}  (build context $ctx: Dockerfile, sfc-uberjar.jar, entrypoint, sfcx, ipc, USAGE.txt)"
    cat "$ctx/Dockerfile"
    say ""; say "${C_B}USAGE.txt${C_0}"
    cat "$ctx/USAGE.txt"
    say ""; ok "dry run: nothing was built or pushed"
    return 0
  fi

  for b in ${SFCUP_BUILDER:-} docker podman finch; do
    if have "$b"; then builder="$b"; break; fi
  done
  [ -n "$builder" ] || die "need docker, podman or finch to build the image (or set SFCUP_BUILDER)"
  aws_context
  registry="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
  image="$registry/$ECR_REPO:$tag"

  if aws ecr describe-repositories --region "$REGION" --repository-names "$ECR_REPO" >/dev/null 2>&1; then
    step "ECR repository $ECR_REPO exists"
  else
    aws ecr create-repository --region "$REGION" --repository-name "$ECR_REPO" \
        --image-scanning-configuration scanOnPush=true >/dev/null \
      || die "could not create the ECR repository $ECR_REPO"
    step "created the ECR repository $ECR_REPO"
  fi
  aws ecr get-login-password --region "$REGION" \
    | "$builder" login --username AWS --password-stdin "$registry" >/dev/null \
    || die "$builder could not log in to $registry"
  step "building $image with $builder"
  "$builder" build ${PLATFORM:+--platform "$PLATFORM"} -t "$image" "$ctx" || die "the image build failed"
  step "pushing"
  "$builder" push "$image" || die "the push to $registry failed"

  say ""
  ok "pushed $image"
  say ""
  say "  ${C_DIM}usage${C_0}     $builder run --rm $image help"
  say "  ${C_DIM}sfc-main${C_0}  $builder run --rm -v \"\$PWD:/cfg\" $image -config /cfg/sfc-config.json"
  say "  ${C_DIM}ipc${C_0}       $builder run --rm -p 50000:50000 $image ipc opcua -port 50000"
  say ""
}

# The component recipe. The SFC configuration travels as component configuration (SfcConfig), reaches
# the run script as the SFC_CONFIG_JSON environment variable - Greengrass replaces a recipe variable
# that points at an object with that object serialized as JSON - and is written to disk from the
# variable, every time the component starts, right before java. It never passes through a command
# line, so no shell (sh, cmd.exe, PowerShell) parses or re-quotes it. Install only checks the JVM.
write_recipe() {
  local out="$1" component="$2" cversion="$3" uri="$4"
  {
    printf '{\n  "RecipeFormatVersion": "2020-01-25",\n'
    printf '  "ComponentName": "%s",\n  "ComponentVersion": "%s",\n' "$component" "$cversion"
    printf '  "ComponentDescription": "Shop Floor Connectivity (SFC) %s from sfc-uberjar.tar.gz: sfc-main with every protocol adapter and target. Default configuration: the simulator to the debug target, which writes to the component log.",\n' "$VERSION"
    printf '  "ComponentPublisher": "sfcup %s",\n' "$SFCUP_VERSION"
    printf '  "ComponentConfiguration": { "DefaultConfiguration": { "SfcConfig": %s } },\n' "$DEFAULT_CONFIG"
    sed "s|@@URI@@|$uri|g" <<'EOF'
  "Manifests": [
    {
      "Platform": { "os": "linux" },
      "Lifecycle": {
        "Install": "m=$(java -XshowSettings:properties -version 2>&1 | grep java.specification.version | head -n 1 | sed 's/.*= *//'); m=${m%%.*}; [ ${m:-0} -ge 17 ] || { echo 'SFC needs Java 17 or newer on the PATH of the Greengrass user' >&2; exit 1; }",
        "Run": {
          "Setenv": { "SFC_CONFIG_JSON": "{configuration:/SfcConfig}" },
          "Script": "printf '%s' \"$SFC_CONFIG_JSON\" > {work:path}/sfc-config.json && exec java -cp {artifacts:path}/sfc-uberjar.jar com.amazonaws.sfc.MainController -config {work:path}/sfc-config.json -nocolor"
        }
      },
      "Artifacts": [ { "URI": "@@URI@@" } ]
    },
    {
      "Platform": { "os": "windows" },
      "Lifecycle": {
        "Install": "powershell -NoProfile -NonInteractive -Command \"$s = (java -XshowSettings:properties -version 2>&1 | Out-String); $m = [regex]::Match($s, 'java\\.specification\\.version = (\\d+)'); if (-not $m.Success -or [int]$m.Groups[1].Value -lt 17) { [Console]::Error.WriteLine('SFC needs Java 17 or newer on the PATH of the Greengrass user'); exit 1 }\"",
        "Run": {
          "Setenv": { "SFC_CONFIG_JSON": "{configuration:/SfcConfig}" },
          "Script": "powershell -NoProfile -NonInteractive -Command \"[IO.File]::WriteAllText('{work:path}\\sfc-config.json', $env:SFC_CONFIG_JSON)\" && java -cp \"{artifacts:path}\\sfc-uberjar.jar\" com.amazonaws.sfc.MainController -config \"{work:path}\\sfc-config.json\" -nocolor"
        }
      },
      "Artifacts": [ { "URI": "@@URI@@" } ]
    }
  ]
}
EOF
  } > "$out"
}

aws_greengrass() {
  local cversion="$GG_COMPONENT_VERSION" recipe="$TMP/recipe.json" jar bucket key uri arn
  if [ -z "$cversion" ]; then
    # A release tag vX.Y.Z gives X.Y.Z. Anything else (--local) gets a fresh version, because a component
    # version can be created only once: 0.<days since 1970>.<second of the day>, each part under
    # Greengrass's maximum of 999999.
    cversion="${VERSION#v}"
    if ! printf '%s' "$cversion" | grep -Eq '^[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}$'; then
      local now; now=$(date +%s)
      cversion="0.$((now / 86400)).$((now % 86400))"
    fi
  fi
  valid "--component-version" "$cversion" '^[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}$'
  valid "--component" "$GG_COMPONENT" '^[A-Za-z0-9][A-Za-z0-9._-]*$'
  jar=$(bundle_jar)

  if [ "$DRY_RUN" = 1 ]; then
    bucket="${GG_BUCKET:-sfcx-greengrass-ACCOUNT-REGION}"
  else
    aws_context
    bucket="${GG_BUCKET:-sfcx-greengrass-$ACCOUNT-$REGION}"
  fi
  valid "--bucket" "$bucket" '^[A-Za-z0-9][A-Za-z0-9.-]{1,61}[A-Za-z0-9]$'
  key="sfcx/$GG_COMPONENT/$cversion/sfc-uberjar.jar"
  uri="s3://$bucket/$key"
  write_recipe "$recipe" "$GG_COMPONENT" "$cversion" "$uri"

  if [ "$DRY_RUN" = 1 ]; then
    say ""; say "${C_B}recipe${C_0}  (the jar would go to $uri)"
    cat "$recipe"
    say ""; ok "dry run: nothing was uploaded or created"
    return 0
  fi

  if aws s3api head-bucket --bucket "$bucket" >/dev/null 2>&1; then
    step "bucket $bucket exists"
  else
    aws s3 mb "s3://$bucket" --region "$REGION" >/dev/null \
      || die "could not create the bucket $bucket - pass another name with --bucket"
    step "created the bucket $bucket"
  fi
  # The jar of an existing version must not be replaced: Greengrass checks it against the recorded digest.
  if aws greengrassv2 describe-component --region "$REGION" \
       --arn "arn:aws:greengrass:$REGION:$ACCOUNT:components:$GG_COMPONENT:versions:$cversion" >/dev/null 2>&1; then
    die "$GG_COMPONENT $cversion exists already - pass another --component-version"
  fi
  step "uploading the jar to $uri"
  aws s3 cp "$jar" "$uri" --region "$REGION" --only-show-errors || die "could not upload the jar to $uri"
  step "creating the component $GG_COMPONENT $cversion"
  arn=$(aws greengrassv2 create-component-version --region "$REGION" \
          --inline-recipe "fileb://$recipe" --query arn --output text) \
    || die "could not create the component version (it may exist already: pass --component-version)"

  say ""
  ok "created $GG_COMPONENT $cversion"
  say "  ${C_DIM}arn${C_0}      $arn"
  say "  ${C_DIM}status${C_0}   aws greengrassv2 describe-component --region $REGION --arn $arn --query status"
  say ""
  say "Deploy it to a core device (Java 17+ on the PATH of the Greengrass user), e.g.:"
  say ""
  say "  ${C_B}aws greengrassv2 create-deployment --region $REGION \\"
  say "    --target-arn arn:aws:iot:$REGION:$ACCOUNT:thing/<core-device> \\"
  say "    --components '{\"$GG_COMPONENT\":{\"componentVersion\":\"$cversion\"}}'${C_0}"
  say ""
  say "  The core device's token exchange role needs s3:GetObject on arn:aws:s3:::$bucket/*."
  say "  A deployment to a thing replaces that thing's previous deployment - add the component to"
  say "  your existing deployment instead if the device runs other components."
  say "  Another SFC configuration: deploy with a configuration update that resets /SfcConfig and"
  say "  merges {\"SfcConfig\": {...}}; it is written to sfc-config.json each time the component starts."
  say "  SFC's output is in the component log."
  say ""
}

# ------------------------------------------------------------------------------------------ install

VERSIONS_DIR="$SFC_HOME/versions"
BIN_DIR="$SFC_HOME/bin"
CURRENT="$SFC_HOME/current"

say ""
case "$AWS_MODE" in
  ecr)        say "${C_B}sfcup${C_0} $SFCUP_VERSION — building the sfcx image for Amazon ECR" ;;
  greengrass) say "${C_B}sfcup${C_0} $SFCUP_VERSION — creating an AWS IoT Greengrass component" ;;
  *)          say "${C_B}sfcup${C_0} $SFCUP_VERSION — installing Shop Floor Connectivity" ;;
esac
say ""

# The AWS modes run nothing locally, so a local JVM does not matter for them.
[ -n "$AWS_MODE" ] || check_java

SRC_TARBALL=""
if [ "$FROM_LOCAL" = 1 ]; then
  # Developer path: use the tarball this checkout just built, so local changes are what gets installed.
  # BASH_SOURCE is empty when the script is piped into bash, and set -u would abort on it.
  [ -n "${BASH_SOURCE[0]:-}" ] || die "--local needs the script run from a checkout:  ./sfcup.sh --local"
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  SRC_TARBALL="$here/build/distribution/$BUNDLE"
  [ -f "$SRC_TARBALL" ] || die "no local bundle at $SRC_TARBALL
  Build it first:  ./gradlew build"
  VERSION="local"
  step "using the local build"
else
  pick_downloader
  if [ -z "$WANT_VERSION" ]; then
    step "resolving the latest release"
    VERSION=$(resolve_latest) || die "could not reach GitHub to resolve the latest release.
  Check network access, or pass --version vX.Y.Z."
    [ -n "$VERSION" ] || die "could not determine the latest release tag.
  Pass --version vX.Y.Z to install a specific one."
  else
    VERSION="$WANT_VERSION"
  fi
  step "version $VERSION"
fi

# AWS modes: the same bundle, unpacked into a scratch dir and published; nothing is installed.
if [ -n "$AWS_MODE" ]; then
  SFC_HOME_CREATED=0
  [ -d "$SFC_HOME" ] || { mkdir -p "$SFC_HOME"; SFC_HOME_CREATED=1; }
  TMP="$SFC_HOME/.tmp.$$"
  aws_cleanup() {
    rm -rf "$TMP"
    if [ "$SFC_HOME_CREATED" = 1 ]; then rmdir "$SFC_HOME" 2>/dev/null || true; fi
  }
  trap aws_cleanup EXIT
  trap 'exit 130' INT TERM
  rm -rf "$TMP"; mkdir -p "$TMP"
  fetch_bundle
  case "$AWS_MODE" in
    ecr)        aws_ecr ;;
    greengrass) aws_greengrass ;;
  esac
  exit 0
fi

TARGET="$VERSIONS_DIR/$VERSION"

# Nothing to do if this version is already the active one.
if [ "$FORCE" = 0 ] && [ "$VERSION" != "local" ] && [ -d "$TARGET" ] \
   && [ -L "$CURRENT" ] && [ "$(readlink "$CURRENT")" = "versions/$VERSION" ]; then
  ok "already at $VERSION in ${SFC_HOME/#$HOME/~} — nothing to do"
  say "  Reinstall anyway with ${C_B}--force${C_0}."
  exit 0
fi

mkdir -p "$VERSIONS_DIR" "$BIN_DIR"

# Everything lands in a scratch dir first, so an interrupted run never leaves a half-installed tree.
TMP="$SFC_HOME/.tmp.$$"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT
trap 'exit 130' INT TERM
rm -rf "$TMP"; mkdir -p "$TMP"

fetch_bundle

# Record which versions existed before, so the old one can be pruned only after a successful swap.
OLD_VERSIONS=""
if [ -d "$VERSIONS_DIR" ]; then
  OLD_VERSIONS=$(find "$VERSIONS_DIR" -maxdepth 1 -mindepth 1 -type d ! -name "$VERSION" 2>/dev/null || true)
fi

rm -rf "$TARGET"
mv "$TMP/$BUNDLE_DIR" "$TARGET"

# Flip `current` atomically: build the new symlink beside it, then rename over the old one.
ln -sfn "versions/$VERSION" "$CURRENT.new"
mv -f "$CURRENT.new" "$CURRENT"

# One command name on every OS: `sfcx`. (Plain `sfc` is taken on Windows by the System File Checker.)
ln -sfn "../current/$LAUNCHER" "$BIN_DIR/sfcx"
# Earlier installs linked `sfc` and `sfc-uberjar`; drop them so only one name stays in use.
rm -f "$BIN_DIR/sfc" "$BIN_DIR/sfc-uberjar"

# Keep a copy of this script so `sfcup` can upgrade the install later. Under `curl ... | bash` there is
# no script file (BASH_SOURCE is empty, and set -u would abort on it), so fetch the published copy.
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  # An upgrade run from the installed copy must not copy the file onto itself.
  [ "${BASH_SOURCE[0]}" -ef "$BIN_DIR/sfcup" ] || { cp "${BASH_SOURCE[0]}" "$BIN_DIR/sfcup" && chmod +x "$BIN_DIR/sfcup"; }
elif fetch_stdout "https://raw.githubusercontent.com/$REPO_SLUG/main/sfcup.sh" > "$BIN_DIR/sfcup.new" 2>/dev/null \
     && [ -s "$BIN_DIR/sfcup.new" ]; then
  mv -f "$BIN_DIR/sfcup.new" "$BIN_DIR/sfcup" && chmod +x "$BIN_DIR/sfcup"
else
  rm -f "$BIN_DIR/sfcup.new"
  warn "could not save sfcup for later upgrades; re-run the install command to upgrade"
fi

# --------------------------------------------------------------------------------------- PATH

# Sourced by the shell startup files. The guard makes repeated sourcing harmless, which matters
# because .profile and .bashrc can both be read in one session.
cat > "$SFC_HOME/env" <<EOF
# Added by sfcup. Sourced from your shell startup file; safe to source more than once.
case ":\${PATH}:" in
    *:"$BIN_DIR":*) ;;
    *) export PATH="$BIN_DIR:\$PATH" ;;
esac
EOF

PATH_WIRED=0
if [ "$MODIFY_PATH" = 1 ]; then
  rcs=""
  # zsh, the macOS default, reads neither .profile nor .bashrc, and a fresh account may have no .zshrc yet.
  case "${SHELL:-}" in
    */zsh) [ -f "$HOME/.zshrc" ] || touch "$HOME/.zshrc" ;;
  esac
  for rc in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshrc"; do
    [ -f "$rc" ] && rcs="$rcs $rc"
  done
  # If the user has none of them, create .profile rather than silently doing nothing.
  [ -n "$rcs" ] || { touch "$HOME/.profile"; rcs=" $HOME/.profile"; }

  for rc in $rcs; do
    if grep -qF "$RC_BEGIN" "$rc"; then
      step "already wired in ${rc/#$HOME/~}"
    else
      printf '\n%s\n. "%s/env"\n%s\n' "$RC_BEGIN" "$SFC_HOME" "$RC_END" >> "$rc"
      step "added to ${rc/#$HOME/~}"
    fi
    PATH_WIRED=1
  done
fi

# Prune the previous version only now that the new one is live and reachable.
if [ "$KEEP_OLD" = 0 ] && [ -n "$OLD_VERSIONS" ]; then
  while IFS= read -r old; do
    [ -n "$old" ] || continue
    rm -rf "$old"
    step "removed the previous version $(basename "$old")"
  done <<< "$OLD_VERSIONS"
fi

# ------------------------------------------------------------------------------------------ done

JAR=$(find "$TARGET/lib" -maxdepth 1 -name 'sfc-uberjar-*.jar' 2>/dev/null | head -1)

say ""
ok "SFC $VERSION installed in ${SFC_HOME/#$HOME/~}"
say ""
say "  ${C_DIM}command${C_0}   sfcx"
say "  ${C_DIM}jar${C_0}       ${JAR/#$HOME/~}"
say "  ${C_DIM}update${C_0}    sfcup"
say ""

if [ "$PATH_WIRED" = 1 ]; then
  say "Start a new shell, or activate it now with:"
  say ""
  say "  ${C_B}. \"$SFC_HOME/env\"${C_0}"
else
  say "To put it on PATH, add this to your shell startup file:"
  say ""
  say "  ${C_B}. \"$SFC_HOME/env\"${C_0}"
fi

say ""
say "Then try it — this needs no hardware and no cloud account:"
say ""
say "  ${C_B}sfcx -config <your-config>.json -info${C_0}"
say ""
say "  ${C_DIM}Ready-made configurations: $REPO/blob/main/docs/examples/README.md${C_0}"
say ""
