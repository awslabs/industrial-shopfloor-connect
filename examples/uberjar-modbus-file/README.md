# Uberjar: Modbus TCP to files

Reads 69 coils, discrete inputs and registers of a simulated Modbus TCP device every 200 ms, decodes 32-bit values with named transformations, and writes the reads as JSON files.

The configuration is the e2e test case [`ADP-MODBUS-PILOT`](../../ci/e2e/cases/adapters/modbus.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.
- [Rust](https://rustup.rs) to build the PLC simulator [`omni-plc-sim`](../../ci/omni-plc-sim/README.md).

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-modbus-file
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-modbus-file
.\create.ps1
```

This writes `modbus-to-file.json`: the case's configuration with its uberjar section, without the CI-only `Metadata` and `Metrics` sections. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

## 2. Start the simulated PLC

In a second shell, from the repository root (the first build takes a few minutes):

**Linux / macOS**

```shell
cd ci/omni-plc-sim
cargo build --release
target/release/omni-plc-sim --serve modbus=127.0.0.1:10502 --profile modbus=generic
```

**Windows (PowerShell)**

```powershell
cd ci\omni-plc-sim
cargo build --release
.\target\release\omni-plc-sim.exe --serve modbus=127.0.0.1:10502 --profile modbus=generic
```

## 3. Run SFC

Back in the first shell, in this folder:

**Linux / macOS**

```shell
mkdir -p out
export SFC_E2E_SINK=out SFC_E2E_PLC_PORT=10502
sfcx -config modbus-to-file.json -info
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force out | Out-Null
$env:SFC_E2E_SINK = "out"; $env:SFC_E2E_PLC_PORT = "10502"
sfcx -config modbus-to-file.json -info
```

SFC writes the reads as JSON files into `out/<year>/<month>/<day>/<hour>/<minute>/`. Stop it with `Ctrl-C`.

Docs used: [Modbus TCP adapter](../../docs/adapters/modbus.md) · [File target](../../docs/targets/file.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
