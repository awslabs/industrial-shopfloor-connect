# Uberjar: OPC UA to files

Runs SFC's own OPC UA server (the OPC UA target) and polls 5 standard server nodes from it every 200 ms, writing the reads as JSON files. The node ids are standard namespace-0 nodes, so the adapter part works against any OPC UA server.

The configuration is the e2e test case [`ADP-OPCUA-POLL-STD-01`](../../ci/e2e/cases/adapters/opcua.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-opcua-file
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-opcua-file
.\create.ps1
```

This writes `opcua-to-file.json`: the case's configuration with its uberjar section, without the CI-only `Metadata` and `Metrics` sections. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

## 2. Run SFC

**Linux / macOS**

```shell
mkdir -p out
export SFC_E2E_SINK=out SFC_E2E_OPCUA_PORT=4840
sfcx -config opcua-to-file.json -info
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force out | Out-Null
$env:SFC_E2E_SINK = "out"; $env:SFC_E2E_OPCUA_PORT = "4840"
sfcx -config opcua-to-file.json -info
```

At start the adapter can log one `Connection refused` error: it tries to connect before the OPC UA target's server is up, and connects on its next attempt.

At start, the adapter can log one `Connection refused`: it connects before SFC's own OPC UA server listens, then reconnects.

SFC writes the reads as JSON files into `out/<year>/<month>/<day>/<hour>/<minute>/`. Stop it with `Ctrl-C`.

Docs used: [OPC UA adapter](../../docs/adapters/opcua.md) · [OPC UA target](../../docs/targets/opcua.md) · [File target](../../docs/targets/file.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
