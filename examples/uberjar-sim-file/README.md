# Uberjar: Simulator to files

Generates a String range, an Int range, a list and a nested structure with the simulator adapter every 100 ms and writes them as JSON files. No hardware needed.

The configuration is the e2e test case [`CORE-SIM-COMPOSITES-01`](../../ci/e2e/cases/core/simulator.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-sim-file
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-sim-file
.\create.ps1
```

This writes `sim-to-file.json`: the case's configuration with its uberjar section, without the CI-only `Metadata` and `Metrics` sections. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

## 2. Run SFC

**Linux / macOS**

```shell
mkdir -p out
export SFC_E2E_SINK=out
sfcx -config sim-to-file.json -info
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force out | Out-Null
$env:SFC_E2E_SINK = "out"
sfcx -config sim-to-file.json -info
```

SFC writes the reads as JSON files into `out/<year>/<month>/<day>/<hour>/<minute>/`. Stop it with `Ctrl-C`.

Docs used: [Simulator adapter](../../docs/adapters/simulator.md) · [File target](../../docs/targets/file.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
