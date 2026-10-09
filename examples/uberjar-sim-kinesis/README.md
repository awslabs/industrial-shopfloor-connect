# Uberjar: Simulator to Amazon Kinesis

Writes simulated reads every 200 ms to the stack's Kinesis data stream `$SFC_E2E_KINESIS_STREAM`, one record per read.

The configuration is the e2e test case [`AWS-KIN-01`](../../ci/e2e/cases/aws/kinesis.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.
- The AWS CLI v2 (Windows: `winget install Amazon.AWSCLI`) and AWS credentials that may use the [Kinesis target](../../docs/targets/aws-kinesis.md).
- The AWS resources of the integration-test stack: deploy [`ci/cdk`](../../ci/README.md) with `--outputs-file outputs.json`. Its `E2eEnvironment` output holds every resource name the configuration needs.

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-sim-kinesis
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-sim-kinesis
.\create.ps1
```

This writes `sim-to-kinesis.json`: the case's configuration with its uberjar section, without the CI-only `Metadata` and `Metrics` sections. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

## 2. Load the stack's resource names

From this folder, after the stack was deployed:

**Linux / macOS**

```shell
eval "$(jq -r '.[].E2eEnvironment | fromjson | to_entries[] | "export \(.key)=\(.value | @sh)"' ../../ci/cdk/outputs.json)"
```

**Windows (PowerShell)**

```powershell
((Get-Content -Raw ..\..\ci\cdk\outputs.json | ConvertFrom-Json).PSObject.Properties.Value.E2eEnvironment | ConvertFrom-Json).PSObject.Properties | ForEach-Object { Set-Item "env:$($_.Name)" $_.Value }
```

This sets every `SFC_E2E_*` value of the stack, among them `SFC_E2E_REGION`.

## 3. Run SFC

The same command in PowerShell:

```shell
sfcx -config sim-to-kinesis.json -info
```

Stop it with `Ctrl-C`.

Docs used: [Simulator adapter](../../docs/adapters/simulator.md) · [Kinesis target](../../docs/targets/aws-kinesis.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
