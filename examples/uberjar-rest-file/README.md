# Uberjar: REST to files

Reads three sources from an HTTP server every 200 ms, picks values with JMESPath selectors, retries answers other than HTTP 200, and writes the reads as JSON files.

The configuration is the e2e test case [`ADP-REST-PILOT`](../../ci/e2e/cases/adapters/rest.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.
- An HTTP server on `127.0.0.1:8080` that answers the three paths of step 2 with JSON.

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-rest-file
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-rest-file
.\create.ps1
```

This writes `rest-to-file.json`: the case's configuration with its uberjar section, without the CI-only `Metadata` and `Metrics` sections. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

## 2. Provide the HTTP endpoints

Every read sends one GET to each of three paths on `http://127.0.0.1:${SFC_E2E_REST_PORT}` and picks values out of the JSON answers with JMESPath selectors. Serve them from any HTTP server on port 8080:

| Path | Selectors | Answer in the integration test |
|---|---|---|
| `/counter` | `value` | `{"value": n}`, `n` counting up from 0, one per request |
| `/plant` | `line.speed`, `line.running`, `line.sensors[?name=='t2'].temp \| [0]`, `tags` | the document below |
| `/flaky` | `ok` | HTTP 500 once, then `{"ok": true}`; the adapter retries (`MaxRetries` 3, `WaitBeforeRetry` 100 ms) |

The `/plant` document:

```json
{"line": {"id": "L1", "speed": 12.5, "running": true,
          "sensors": [{"name": "t1", "temp": 21.5}, {"name": "t2", "temp": 22.25}]},
 "tags": ["a", "b"]}
```

## 3. Run SFC

**Linux / macOS**

```shell
mkdir -p out
export SFC_E2E_SINK=out SFC_E2E_REST_PORT=8080
sfcx -config rest-to-file.json -info
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force out | Out-Null
$env:SFC_E2E_SINK = "out"; $env:SFC_E2E_REST_PORT = "8080"
sfcx -config rest-to-file.json -info
```

SFC writes the reads as JSON files into `out/<year>/<month>/<day>/<hour>/<minute>/`. Stop it with `Ctrl-C`.

Docs used: [REST adapter](../../docs/adapters/rest.md) · [File target](../../docs/targets/file.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
