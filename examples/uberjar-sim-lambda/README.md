# Uberjar: Simulator to AWS Lambda

Invokes the stack's Lambda function `$SFC_E2E_LAMBDA_FUNCTION` with simulated reads every 200 ms, one invocation per read.

The configuration is the e2e test case [`AWS-LAM-01`](../../ci/e2e/cases/aws/lambda.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.
- The AWS CLI v2 (Windows: `winget install Amazon.AWSCLI`) and AWS credentials that may use the [Lambda target](../../docs/targets/aws-lambda.md).
- The AWS resources of the integration-test stack: deploy [`ci/cdk`](../../ci/README.md) with `--outputs-file outputs.json`. Its `E2eEnvironment` output holds every resource name the configuration needs.

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-sim-lambda
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-sim-lambda
.\create.ps1
```

This writes `sim-to-lambda.json`: the case's configuration with its uberjar section, without the CI-only `Metadata` and `Metrics` sections. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

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
sfcx -config sim-to-lambda.json -info
```

Stop it with `Ctrl-C`.

Docs used: [Simulator adapter](../../docs/adapters/simulator.md) · [Lambda target](../../docs/targets/aws-lambda.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
