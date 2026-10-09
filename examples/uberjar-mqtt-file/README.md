# Uberjar: MQTT to files

Publishes a simulated counter to an MQTT broker with the MQTT target and reads it back with the MQTT adapter (`ReadMode` `KeepAll`), writing what it reads as JSON files.

The configuration is the e2e test case [`ADP-MQTT-RT-KEEPALL-01`](../../ci/e2e/cases/adapters/mqtt.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.
- An MQTT broker on `127.0.0.1:1883` that accepts anonymous clients, for example [Mosquitto](https://mosquitto.org/download/) 2, which does exactly that when started without a configuration file.

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-mqtt-file
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-mqtt-file
.\create.ps1
```

This writes `mqtt-to-file.json`: the case's configuration with its uberjar section, without the CI-only `Metadata` and `Metrics` sections. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

## 2. Start the broker

In a second shell:

```shell
mosquitto
```

## 3. Run SFC

Back in the first shell, in this folder:

**Linux / macOS**

```shell
mkdir -p out
export SFC_E2E_SINK=out SFC_E2E_BROKER_PORT=1883
sfcx -config mqtt-to-file.json -info
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force out | Out-Null
$env:SFC_E2E_SINK = "out"; $env:SFC_E2E_BROKER_PORT = "1883"
sfcx -config mqtt-to-file.json -info
```

SFC writes the reads as JSON files into `out/<year>/<month>/<day>/<hour>/<minute>/`. Stop it with `Ctrl-C`.

Docs used: [MQTT adapter](../../docs/adapters/mqtt.md) · [MQTT target](../../docs/targets/mqtt.md) · [File target](../../docs/targets/file.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
