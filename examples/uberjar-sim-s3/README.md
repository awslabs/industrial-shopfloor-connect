# Uberjar: Simulator to Amazon S3

Writes simulated reads every 200 ms to the stack's bucket `$SFC_E2E_BUCKET`, one object per read under `$SFC_E2E_S3_PREFIX`.

The configuration is the e2e test case [`AWS-S3-01`](../../ci/e2e/cases/aws/s3.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.
- The AWS CLI v2 (Windows: `winget install Amazon.AWSCLI`) and AWS credentials that may use the [S3 target](../../docs/targets/aws-s3.md).
- The AWS resources of the integration-test stack: deploy [`ci/cdk`](../../ci/README.md) with `--outputs-file outputs.json`. Its `E2eEnvironment` output holds every resource name the configuration needs.

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-sim-s3
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-sim-s3
.\create.ps1
```

This writes `sim-to-s3.json`: the case's configuration with its uberjar section, without the CI-only `Metadata` and `Metrics` sections. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

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

`SFC_E2E_S3_PREFIX` is the key prefix of the objects; any value works.

**Linux / macOS**

```shell
export SFC_E2E_S3_PREFIX=s3-target/example
sfcx -config sim-to-s3.json -info
```

**Windows (PowerShell)**

```powershell
$env:SFC_E2E_S3_PREFIX = "s3-target/example"
sfcx -config sim-to-s3.json -info
```

Stop it with `Ctrl-C`.

Docs used: [Simulator adapter](../../docs/adapters/simulator.md) · [S3 target](../../docs/targets/aws-s3.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
