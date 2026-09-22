#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# sfcup - install Shop Floor Connectivity from a single command.
#
#   curl -fsSL https://raw.githubusercontent.com/awslabs/industrial-shopfloor-connect/main/sfcup.sh | bash
#
# Installs the SFC uberjar - the core plus every protocol adapter and target in one jar - into
# ~/.sfc, and puts `sfc` on PATH. Re-run it (or the installed `sfcup`) to upgrade.
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

After installing, both \`sfc\` and \`sfc-uberjar\` are on PATH and take the usual SFC options:

  sfc -config example.json -info
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
    -h|--help)          usage; exit 0 ;;
    -V|--sfcup-version) echo "sfcup $SFCUP_VERSION"; exit 0 ;;
    *) echo "sfcup: unknown option '$1'" >&2; echo >&2; usage >&2; exit 2 ;;
  esac
done

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

# ------------------------------------------------------------------------------------------ install

VERSIONS_DIR="$SFC_HOME/versions"
BIN_DIR="$SFC_HOME/bin"
CURRENT="$SFC_HOME/current"

say ""
say "${C_B}sfcup${C_0} $SFCUP_VERSION — installing Shop Floor Connectivity"
say ""

check_java

SRC_TARBALL=""
if [ "$FROM_LOCAL" = 1 ]; then
  # Developer path: use the tarball this checkout just built, so local changes are what gets installed.
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  SRC_TARBALL="$here/build/distribution/$BUNDLE"
  [ -f "$SRC_TARBALL" ] || die "no local bundle at $SRC_TARBALL
  Build it first:  ./gradlew build"
  VERSION="local"
  step "installing from the local build"
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
trap cleanup EXIT INT TERM
rm -rf "$TMP"; mkdir -p "$TMP"

if [ "$FROM_LOCAL" = 1 ]; then
  cp "$SRC_TARBALL" "$TMP/$BUNDLE"
else
  if [ -n "$WANT_VERSION" ]; then
    base="$REPO/releases/download/$VERSION"
  else
    base="$REPO/releases/latest/download"
  fi

  say ""
  step "downloading $BUNDLE (a few hundred MB — it carries every adapter and target)"
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
      die "checksum mismatch for $BUNDLE — refusing to install.
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

# Both names, so new docs can say `sfc` while every existing reference to `sfc-uberjar` keeps working.
ln -sfn "../current/$LAUNCHER" "$BIN_DIR/sfc"
ln -sfn "../current/$LAUNCHER" "$BIN_DIR/sfc-uberjar"

# Keep a copy of this script so `sfcup` can upgrade the install later.
if [ -f "${BASH_SOURCE[0]}" ]; then
  cp "${BASH_SOURCE[0]}" "$BIN_DIR/sfcup" && chmod +x "$BIN_DIR/sfcup"
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
say "  ${C_DIM}commands${C_0}  sfc, sfc-uberjar          ${C_DIM}(same launcher, either name)${C_0}"
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
say "  ${C_B}sfc -config <your-config>.json -info${C_0}"
say ""
say "  ${C_DIM}Ready-made configurations: $REPO/tree/main/examples${C_0}"
say ""
