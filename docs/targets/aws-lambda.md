# AWS Lambda Target

[SFC Configuration](../core/sfc-configuration.md) > [Targets](../core/sfc-configuration.md#targets) >  [Target](../core/target-configuration.md) 

The AWS [Lambda](https://aws.amazon.com/lambda/) target adapter for Shop Floor Connectivity  enables direct integration with AWS Lambda functions from industrial data sources. This adapter receives collected data from the SFC Core component and invokes specified Lambda functions, allowing for serverless processing of industrial device data. The adapter supports batching, compression and data transformations using Apache Velocity templates to format the payload before invoking the Lambda functions.

## Deploy this target

`TargetType` is `AWS-LAMBDA` in every deployment mode. In the uberjar and in-process modes the `TargetTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode). All types and classes: [Target types and classes](../sfc-running-targets.md#target-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"TargetTypes": {
  "AWS-LAMBDA": { "FactoryClassName": "com.amazonaws.sfc.awslambda.AwsLambdaTargetWriter" }
}
```

**In-process** - module bundle `aws-lambda-target` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"TargetTypes": {
  "AWS-LAMBDA": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/aws-lambda-target/lib"],
    "FactoryClassName": "com.amazonaws.sfc.awslambda.AwsLambdaTargetWriter"
  }
}
```

**IPC** - no `TargetTypes`; the target runs as its own service:

```json
"Targets": {
  "LambdaTarget": {
    "TargetType": "AWS-LAMBDA",
    "TargetServer": "LambdaServer"
  }
},
"TargetServers": {
  "LambdaServer": { "Address": "localhost", "Port": 50001 }
}
```

Start the service before SFC, on the port of its `TargetServers` entry:

**Linux / macOS**

```shell
aws-lambda-target/bin/aws-lambda-target -port 50001
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\aws-lambda-target\lib\*" com.amazonaws.sfc.awslambda.AwsLambdaTargetService -port 50001
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.awslambda.AwsLambdaTargetService -port 50001` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.awslambda.AwsLambdaTargetService -port 50001`).

**Examples:** none yet - start from [Quickstart step 2](../../README.md#2-first-data--no-hardware-no-cloud) and swap in this component. All: [examples catalog](../examples/README.md)

## AwsLambdaTargetConfiguration

AwsLambdaTargetConfiguration extends the type  [TargetConfiguration](../core/target-configuration.md) with specific configuration data for calling an AWS lambda function. The Targets configuration element can contain entries of this type, the TargetType of these entries must be set to **"AWS-LAMBDA"**


Requires IAM permission `lambda:InvokeFunction` for the lambda function that is called.

The function is invoked asynchronously (InvocationType `Event`): a write counts as successful when Lambda accepts the event, not when the function has processed it. SFC puts at most 256 KB of uncompressed record data into one invocation; a single record that is larger is dropped with an error.

- [Schema](#awslambdatargetconfiguration-schema)
- [Examples](#awslambdatargetconfiguration-examples)

**Properties:**

- [BatchSize](#batchsize)
- [Compression](#compression)
- [CredentialProviderClient](#credentialproviderclient)
- [Endpoint](#endpoint)
- [Formatter](#formatter)
- [FunctionName](#functionname)
- [Interval](#interval)
- [Qualifier](#qualifier)
- [Template](#template)
- [Region](#region)

---
### BatchSize
This configuration property allows control over message batching when invoking Lambda functions. When BatchSize is set greater than 1, multiple messages are combined into a single array before invoking the Lambda function, which can improve efficiency by reducing the number of function invocations. The batching process will trigger an invocation either when the batch size is reached or when adding another message would exceed Lambda's payload size limits.

**Type**: Integer

Default is 10

---
### Compression
This configuration property controls payload compression for Lambda function invocations. When compression is enabled, the payload is compressed using the specified algorithm, encoded in base64, and wrapped in a JSON structure containing both the compression type and the encoded payload. It's important to note that while compression can reduce data transfer size for large payloads, the base64 encoding adds approximately 33% overhead to the compressed data size, so compression should be used selectively based on payload characteristics.

As this payload needs to be valid JSON.
The data is wrapped in structure with the following fields:

- "compression" : Used compression, "GZIP" or "ZIP"
- "payload": Compressed data as a base64 encoded string.
When using compression for the lambda payload verify if actual compression out weights the overhead of the base64 encoded of the compressed data.

**Type**: String

**Values:** 

- "None"  (Default)

- "GZip"
- "Zip"

Use the values exactly as listed; an unrecognised value (for example "gzip") silently means no compression.

---

### CredentialProviderClient

The CredentialProviderClient property specifies which AWS credential provider client to use for authentication. It references a client defined in the SFC's top-level configuration under [AwsIotCredentialProviderClients](../core/sfc-configuration.md#awsiotcredentialproviderclients) section. This client uses X.509 certificates to obtain temporary AWS credentials through the  [AWS IoT credentials provider](../sfc-aws-service-credentials.md).

If no CredentialProviderClient is configured the [AWS Java SDK credential provider chain is used](https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/credentials.html#credentials-chain)

**Type:** String



---

### Endpoint

The Endpoint property specifies the VPC endpoint URL used to access AWS services privately through AWS PrivateLink without requiring an internet gateway or NAT device. When not specified, the service's default public endpoint for the configured region will be used.

https://docs.aws.amazon.com/vpc/latest/privatelink/aws-services-privatelink-support.html

**Type:** String

---

### Formatter

Configuration allows for custom formatting of data written by a target. A [custom formatter](../sfc-extending.md#custom-formatters), implemented as a JVM class, converts a sequence of target data messages into a specific format and returns the formatted data as an array of bytes.

Formatter and [Template](#template) are mutually exclusive; setting both is a configuration error.

The AWS Lambda target does not apply a formatter; a configured Formatter is not used.

**Type:** [InProcessConfiguration](../core/in-process-configuration.md)

---
### FunctionName
Name of the Lambda function, or its full or partial ARN.

SFC does not validate the name at startup; an invalid name shows up as `Error invoking function` lines in the log when data is sent.

**Type**: String

---
### Interval
Time in milliseconds without new data after which a partially filled buffer is sent to the function even if the [BatchSize](#batchsize) hasn't been reached. The timer restarts with every record.

**Type** : Integer

Optional, if not set only [BatchSize](#batchsize) is used. Must be greater than 10.

---
### Qualifier
Version or alias of the Lambda function to invoke

**Type** : String

Optional. If not set, the function is invoked without a qualifier.

---
### Template

Specifies the file path to an [Apache velocity](https://velocity.apache.org/)  template used for  [transforming the output data](../sfc-target-templates.md) target output data. This optional setting enables custom formatting of data before it is sent to the target. Available context variables include:

- $schedule
- $sources
- $metadata
- $serial
- $timestamp
- names specified in ElementNames configuration
- $tab (for inserting tab characters)

Pathname to file containing an [Apache velocity](https://velocity.apache.org/) template that can be applied to [transform the output data](../sfc-target-templates.md) of the target.

The following [Velocity tools](https://velocity.apache.org/tools/3.1/tools-summary.html) can be used in the transformation template:

- $date
- $collection
- $context
- $math
- $number

Additional epoch timestamp values can be added to the data used for the transformation by setting the [TemplateEpochTimestamp](../core/target-configuration.md#templateepochtimestamp) property to true,

For targets where the data does not require specific output format, the data is serialized as [JSON data](../sfc-data-format.md#sfc-output-data-schemas).

Template and a custom [formatter](#formatter) are mutually exclusive; setting both for a target is a configuration error.

**Type**: String

---

### Region

AWS Region for Lambda service

**Type** : String

### AwsLambdaTargetConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AwsLambdaTargetConfiguration",
  "type": "object",
  "allOf": [
    {
      "$ref": "#/definitions/TargetConfiguration"
    },
    {
      "$ref": "#/definitions/AwsServiceConfig"
    },
    {
      "type": "object",
      "properties": {
        "BatchSize": {
          "type": "integer",
          "description": "Size of the batch for Lambda invocations"
        },
        "Compression": {
          "type": "string",
          "description": "Compression type for payload",
          "enum": ["None", "Zip", "GZip"],
          "default": "None"
        },
        "CredentialProviderClient": {
          "type": "string",
          "description": "The credential provider client name"
        },
        "FunctionName": {
          "type": "string",
          "description": "Name or ARN of the Lambda function"
        },
        "Interval": {
          "type": "integer",
          "description": "Time in milliseconds without new data after which a partial batch is sent"
        },
        "Qualifier": {
          "type": "string",
          "description": "Version or alias of the Lambda function"
        },
        "Region": {
          "type": "string",
          "description": "AWS region for Lambda"
        }
      },
      "required": ["FunctionName"]
    }
  ]
}

```

### AwsLambdaTargetConfiguration Examples



Configuration using CredentialProviderClient,

```json
{
  "TargetType" : "AWS-LAMBDA",  
  "FunctionName": "process-data-function",
  "Region": "us-east-1",
  "BatchSize": 50,
  "Interval": 1000,
  "CredentialProviderClient": "aws-credentials-provider"
}

```

Configuration using default AWS SDK credential provider chain.

```json
{
  "TargetType" : "AWS-LAMBDA",    
  "FunctionName": "process-data-function",
  "Region": "us-east-1",
  "BatchSize": 50,
  "Interval": 1000
}

```



[^top](#aws-lambda-target)

