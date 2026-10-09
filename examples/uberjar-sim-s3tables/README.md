# Uberjar: Simulator to Amazon S3 Tables

Writes simulated reads as rows into the stack's Iceberg table `$SFC_E2E_S3T_TABLE_A` (namespace `$SFC_E2E_S3T_NAMESPACE`, table bucket `$SFC_E2E_S3T_BUCKET`). Value filters pass only reads 75 to 80, so it writes six rows, about 15 seconds after the start.

The configuration is the e2e test case [`AWS-S3T-01`](../../ci/e2e/cases/aws/s3tables.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.
- The AWS CLI v2 (Windows: `winget install Amazon.AWSCLI`) and AWS credentials that may use the [S3 Tables target](../../docs/targets/aws-s3-tables.md).
- The AWS resources of the integration-test stack: deploy [`ci/cdk`](../../ci/README.md) with `--outputs-file outputs.json`. Its `E2eEnvironment` output holds every resource name the configuration needs.

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-sim-s3tables
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-sim-s3tables
.\create.ps1
```

This writes `sim-to-s3tables.json`: the case's configuration with its uberjar section, without the CI-only `Metrics` section and the CI run markers in `Metadata`. `Metadata.marker` stays: it fills the table's `label` column. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

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

`SFC_E2E_MARKER` becomes the `label` of each row; any value works.

**Linux / macOS**

```shell
export SFC_E2E_MARKER=example
sfcx -config sim-to-s3tables.json -info
```

**Windows (PowerShell)**

```powershell
$env:SFC_E2E_MARKER = "example"
sfcx -config sim-to-s3tables.json -info
```

The target logs `Written … buffered records for table …` when the rows are in the table. Stop SFC with `Ctrl-C`.

Docs used: [Simulator adapter](../../docs/adapters/simulator.md) · [S3 Tables target](../../docs/targets/aws-s3-tables.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
