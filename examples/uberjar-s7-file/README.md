# Uberjar: Siemens S7 to files

Reads 53 tags of a simulated Siemens S7-1500 (data blocks, merker, inputs and outputs) every 200 ms and writes the reads as JSON files.

The configuration is the e2e test case [`ADP-S7-PILOT`](../../ci/e2e/cases/adapters/s7.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.
- [Rust](https://rustup.rs) to build the PLC simulator [`omni-plc-sim`](../../ci/omni-plc-sim/README.md).

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-s7-file
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-s7-file
.\create.ps1
```

This writes `s7-to-file.json`: the case's configuration with its uberjar section, without the CI-only `Metadata` and `Metrics` sections. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

## 2. Start the simulated PLC

In a second shell, from the repository root (the first build takes a few minutes):

**Linux / macOS**

```shell
cd ci/omni-plc-sim
cargo build --release
target/release/omni-plc-sim --serve s7=127.0.0.1:10102 --profile s7=s7-1500
```

**Windows (PowerShell)**

```powershell
cd ci\omni-plc-sim
cargo build --release
.\target\release\omni-plc-sim.exe --serve s7=127.0.0.1:10102 --profile s7=s7-1500
```

## 3. Run SFC

Back in the first shell, in this folder:

**Linux / macOS**

```shell
mkdir -p out
export SFC_E2E_SINK=out SFC_E2E_PLC_PORT=10102
export TZ=UTC
sfcx -config s7-to-file.json -info
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force out | Out-Null
$env:SFC_E2E_SINK = "out"; $env:SFC_E2E_PLC_PORT = "10102"
$env:JAVA_TOOL_OPTIONS = "-Duser.timezone=UTC"
sfcx -config s7-to-file.json -info
```

Like the integration tests, the run uses UTC (`TZ=UTC`; on Windows the JVM option `-Duser.timezone=UTC`): the case relies on it for its `DATE` channel.

SFC writes the reads as JSON files into `out/<year>/<month>/<day>/<hour>/<minute>/`. Stop it with `Ctrl-C`.

Docs used: [S7 adapter](../../docs/adapters/s7.md) · [File target](../../docs/targets/file.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
