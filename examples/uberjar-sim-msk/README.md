# Uberjar: Simulator to Amazon MSK

Writes the simulated counter values 0 to 9, one every 500 ms, to a topic of the stack's MSK cluster, over SASL/IAM on the cluster's public endpoint. A value filter ends the stream after these ten records.

The configuration is the e2e test case [`AWS-MSK-01`](../../ci/e2e/cases/aws/msk.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.
- The AWS CLI v2 (Windows: `winget install Amazon.AWSCLI`) and AWS credentials that may use the [MSK target](../../docs/targets/aws-msk.md).
- The AWS resources of the integration-test stack: deploy [`ci/cdk`](../../ci/README.md) with `--outputs-file outputs.json`. Its `E2eEnvironment` output holds every resource name the configuration needs.

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-sim-msk
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-sim-msk
.\create.ps1
```

This writes `sim-to-msk.json`: the case's configuration with its uberjar section, without the CI-only `Metadata` and `Metrics` sections. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

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

## 3. Create a topic

MSK does not create topics by default. The integration tests create one with the Kafka 3.9 CLI, with the [`aws-msk-iam-auth`](https://github.com/aws/aws-msk-iam-auth/releases) 2.3.8 `-all.jar` copied into its `libs` folder. Save this as `client.properties`:

```properties
security.protocol=SASL_SSL
sasl.mechanism=AWS_MSK_IAM
sasl.jaas.config=software.amazon.msk.auth.iam.IAMLoginModule required;
sasl.client.callback.handler.class=software.amazon.msk.auth.iam.IAMClientCallbackHandler
```

Then look up the cluster's public SASL/IAM bootstrap string and create the topic (`kafka-topics.sh` is in Kafka's `bin` folder, `kafka-topics.bat` in `bin\windows`):

**Linux / macOS**

```shell
export SFC_E2E_KAFKA_BOOTSTRAP=$(aws kafka get-bootstrap-brokers --region "$SFC_E2E_REGION" --cluster-arn "$(aws kafka list-clusters-v2 --region "$SFC_E2E_REGION" --cluster-name-filter "$SFC_E2E_MSK_CLUSTER_NAME" --query 'ClusterInfoList[0].ClusterArn' --output text)" --query BootstrapBrokerStringPublicSaslIam --output text)
export SFC_E2E_KAFKA_TOPIC=sfc-example
kafka-topics.sh --bootstrap-server "$SFC_E2E_KAFKA_BOOTSTRAP" --command-config client.properties --create --topic "$SFC_E2E_KAFKA_TOPIC" --partitions 1
```

**Windows (PowerShell)**

```powershell
$arn = aws kafka list-clusters-v2 --region $env:SFC_E2E_REGION --cluster-name-filter $env:SFC_E2E_MSK_CLUSTER_NAME --query 'ClusterInfoList[0].ClusterArn' --output text
$env:SFC_E2E_KAFKA_BOOTSTRAP = aws kafka get-bootstrap-brokers --region $env:SFC_E2E_REGION --cluster-arn $arn --query BootstrapBrokerStringPublicSaslIam --output text
$env:SFC_E2E_KAFKA_TOPIC = "sfc-example"
kafka-topics.bat --bootstrap-server $env:SFC_E2E_KAFKA_BOOTSTRAP --command-config client.properties --create --topic $env:SFC_E2E_KAFKA_TOPIC --partitions 1
```

## 4. Run SFC

The same command in PowerShell:

```shell
sfcx -config sim-to-msk.json -info
```

Stop it with `Ctrl-C`.

Docs used: [Simulator adapter](../../docs/adapters/simulator.md) · [MSK target](../../docs/targets/aws-msk.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
