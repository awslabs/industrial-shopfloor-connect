# AWS SNS Target

[SFC Configuration](../core/sfc-configuration.md) > [Targets](../core/sfc-configuration.md#targets) >  [Target](../core/target-configuration.md) 

The SFC target adapter for [Amazon Simple Notification Service](https://aws.amazon.com/sns/) (SNS) enables publishing collected data as messages to SNS topics.

## Deploy this target

`TargetType` is `AWS-SNS` in every deployment mode. In the uberjar and in-process modes the `TargetTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configuration-in-each-mode). All types and classes: [Target types and classes](../sfc-running-targets.md#target-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"TargetTypes": {
  "AWS-SNS": { "FactoryClassName": "com.amazonaws.sfc.awssns.AwsSnsTargetWriter" }
}
```

**In-process** - module bundle `aws-sns-target` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"TargetTypes": {
  "AWS-SNS": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/aws-sns-target/lib"],
    "FactoryClassName": "com.amazonaws.sfc.awssns.AwsSnsTargetWriter"
  }
}
```

**IPC** - no `TargetTypes`; the target runs as its own service:

```json
"Targets": {
  "SnsTarget": {
    "TargetType": "AWS-SNS",
    "TargetServer": "SnsTargetServer"
  }
},
"TargetServers": {
  "SnsTargetServer": { "Address": "localhost", "Port": 50001 }
}
```

Start the service before SFC, on the port of its `TargetServers` entry:

**Linux / macOS**

```shell
aws-sns-target/bin/aws-sns-target -port 50001
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\aws-sns-target\lib\*" com.amazonaws.sfc.awssns.AwsSnsTargetService -port 50001
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.awssns.AwsSnsTargetService -port 50001` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.awssns.AwsSnsTargetService -port 50001`).

**Examples:** uberjar: [uberjar-sim-sns](../../examples/uberjar-sim-sns/README.md) · all: [examples catalog](../examples/README.md)

## AwsSnsTargetConfiguration

A configuration class that defines how industrial data should be published to Amazon SNS topics. It specifies the target SNS topic ARN, message format, and data transformation settings. 

AwsSnsTargetConfiguration extends the type  [TargetConfiguration](../core/target-configuration.md) with specific configuration data for sending data to an SNS topic. The Targets configuration element can contain entries of this type, the TargetType of these entries must be set to **"AWS-SNS"**


Requires IAM permission `sns:Publish` on the topic.

- [Schema](#awssnstargetconfiguration-schema)
- [Examples](#awssnstargetconfiguration-examples)

**Properties:**

- [BatchSize](#batchsize)
- [Compression](#compression)
- [CredentialProviderClient](#credentialproviderclient)
- [Endpoint](#endpoint)
- [Formatter](#formatter)
- [Interval](#interval)
- [MessageGroupId](#messagegroupid)
- [Region](#region)
- [SerialAsMessageDeduplicationId](#serialasmessagededuplicationid)
- [Subject](#subject)
- [Template](#template)
- [TopicArn](#topicarn)

---
### BatchSize
Number of output messages to combine in a single PublishBatch API call. The data will be written to the SNS topic before reaching the specified batch size if the maximum payload size (256 KB) would be exceeded.

**Type**: Integer

Default is 10, maximum is 10

---
### Compression
Specifies the compression algorithm used for message payloads.  Consider the overhead of base64 encoding when choosing compression, as it may offset compression benefits for smaller payloads.

A compressed message is the JSON object `{"compression": "GZIP", "payload": "<base64>"}` (`"ZIP"` for Zip compression); consumers decode the base64 `payload` and decompress it.

**Type**: String

Possible values:

- "None" (Default)
- "GZip"
- "Zip"

---
### CredentialProviderClient



The CredentialProviderClient property specifies which AWS credential provider client to use for authentication. It references a client defined in the SFC's top-level configuration under [AwsIotCredentialProviderClients](../core/sfc-configuration.md#awsiotcredentialproviderclients) section. This client uses X.509 certificates to obtain temporary AWS credentials through the  [AWS IoT credentials provider](../sfc-aws-service-credentials.md).

If no CredentialProviderClient is configured the [AWS Java SDK credential provider chain is used](https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/credentials.html#credentials-chain)

**Type:** String

---

### Endpoint

The EndPoint property specifies the VPC endpoint URL used to access AWS services privately through AWS PrivateLink without requiring an internet gateway or NAT device. When not specified, the service's default public endpoint for the configured region will be used.

https://docs.aws.amazon.com/vpc/latest/privatelink/aws-services-privatelink-support.html

**Type:** String

---

### Formatter

Configuration allows for custom formatting of data written by a target. A [custom formatter](../sfc-extending.md#custom-formatters), implemented as a JVM class, converts a sequence of target data messages into a specific format and returns the formatted data as an array of bytes.

Formatter and [Template](#template) are mutually exclusive; setting both is a configuration error.

**Type:** [InProcessConfiguration](../core/in-process-configuration.md)

---

### Interval
Time in milliseconds without new data after which a partial batch is published to SNS, even if the [batch size](#batchsize) hasn't been reached. The timer restarts with every record, so while records keep arriving more often than this interval, it does not trigger a publish.

**Type**: Integer

Optional, if not set only [BatchSize](#batchsize) is used

---
### MessageGroupId
A tag that identifies a specific message group for FIFO (first-in-first-out) topics only. Messages within the same message group are processed in strict order, while messages in different groups may be processed in parallel. 

**Type**: String

Optional

---
### Region
The AWS Region code where the SNS topic is located (for example, us-east-1, eu-west-1). This must match the region where your SNS topic is created. 

**Type**: String

---
### SerialAsMessageDeduplicationId
Controls how message deduplication is handled for FIFO topics. When true, the record serial is sent as the MessageDeduplicationId. When false, no deduplication ID is sent, so a FIFO topic must have ContentBasedDeduplication enabled. FIFO topics also require [MessageGroupId](#messagegroupid).

**Type**: Boolean

Default is false

---
### Subject
Optional subject for the SNS messages. 

**Type**: String

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
### TopicArn
The Amazon Resource Name (ARN) that uniquely identifies the SNS topic where messages will be published. Must be a valid SNS topic ARN in the format "arn:aws:sns:region:account-id:topic-name".

**Type**: String

### AwsSnsTargetConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AwsSnsTargetConfiguration",
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
          "description": "Size of the batch for SNS messages"
        },
        "Compression": {
          "type": "string",
          "description": "Compression type for messages",
          "enum": ["None", "Zip", "GZip"],
          "default": "None"
        },
        "CredentialProviderClient": {
          "type": "string",
          "description": "The credential provider client name"
        },
        "Interval": {
          "type": "integer",
          "description": "Interval in milliseconds between publishes"
        },
        "MessageGroupId": {
          "type": "string",
          "description": "Message group ID for FIFO topics"
        },
        "Region": {
          "type": "string",
          "description": "AWS region for SNS"
        },
        "SerialAsMessageDeduplicationId": {
          "type": "boolean",
          "description": "Use message serial number as deduplication ID"
        },
        "Subject": {
          "type": "string",
          "description": "Subject of the SNS message"
        },
        "TopicArn": {
          "type": "string",
          "description": "ARN of the SNS topic"
        }
      },
      "required": ["TopicArn"]
    }
  ]
}
   
```

### AwsSnsTargetConfiguration Examples

Configuration using CredentialProviderClient.

```json
{
  "TargetType" : "AWS-SNS",    
  "TopicArn": "arn:aws:sns:us-east-1:123456789012:MyTopic",
  "Region": "us-east-1",
  "Subject": "Device Telemetry",
  "Compression": "None",
  "CredentialProviderClient": "aws-credentials-provider"
}
```

Configuration using  default AWS SDK credential provider chain.

```json
{
  "TargetType" : "AWS-SNS",  
  "TopicArn": "arn:aws:sns:us-east-1:123456789012:MyTopic",
  "Region": "us-east-1",
  "Subject": "Device Telemetry",
  "Compression": "None"
}
```



[^top](#aws-sns-target)

