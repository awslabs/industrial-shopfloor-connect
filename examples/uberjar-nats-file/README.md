# Uberjar: NATS to files

Reads JSON messages from the NATS subjects `e2e.*` (`ReadMode` `KeepAll`, subject name mapping) and writes them as JSON files.

The configuration is the e2e test case [`ADP-NATS-PILOT`](../../ci/e2e/cases/adapters/nats.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.
- `nats-server` and the [`nats` CLI](https://github.com/nats-io/natscli).

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-nats-file
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-nats-file
.\create.ps1
```

This writes `nats-to-file.json`: the case's configuration with its uberjar section, without the CI-only `Metadata` and `Metrics` sections. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

## 2. Start NATS

In a second shell:

```shell
nats-server -a 127.0.0.1 -p 4222
```

## 3. Run SFC

Back in the first shell, in this folder:

**Linux / macOS**

```shell
mkdir -p out
export SFC_E2E_SINK=out SFC_E2E_NATS_PORT=4222
sfcx -config nats-to-file.json -info
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force out | Out-Null
$env:SFC_E2E_SINK = "out"; $env:SFC_E2E_NATS_PORT = "4222"
sfcx -config nats-to-file.json -info
```

## 4. Publish messages

In a third shell, publish 100 messages to `e2e.temp`:

**Linux / macOS**

```shell
nats pub e2e.temp '{"v": {{.Count}}, "unit": "C"}' --count=100
```

**Windows (PowerShell)**

```powershell
nats pub e2e.temp '{\"v\": {{.Count}}, \"unit\": \"C\"}' --count=100
```

Windows PowerShell 5.1 drops unescaped double quotes from the arguments of native programs, hence `\"`. In PowerShell 7.3 or newer, use the Linux / macOS line.

SFC writes the reads as JSON files into `out/<year>/<month>/<day>/<hour>/<minute>/`. Stop it with `Ctrl-C`.

Docs used: [NATS adapter](../../docs/adapters/nats.md) · [File target](../../docs/targets/file.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
