# AWS MSK Target

[SFC Configuration](../core/sfc-configuration.md) > [Targets](../core/sfc-configuration.md#targets) >  [Target](../core/target-configuration.md) 

The AWS [MSK](https://aws.amazon.com/msk/) (Amazon Managed Streaming for Apache Kafka) target adapter for Shop Floor Connectivity enables data streaming from industrial devices directly to Amazon MSK clusters. This adapter transforms collected device data into the required format and publishes it to specified Kafka topics in your MSK cluster. The adapter supports configurable batching, compression,data transformations using Apache Velocity templates and handles the authentication and connection management to your MSK clusters.

## Deploy this target

`TargetType` is `AWS-MSK` in every deployment mode. In the uberjar and in-process modes the `TargetTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configuration-in-each-mode). All types and classes: [Target types and classes](../sfc-running-targets.md#target-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"TargetTypes": {
  "AWS-MSK": { "FactoryClassName": "com.amazonaws.sfc.awsmsk.AwsMskTargetWriter" }
}
```

**In-process** - module bundle `aws-msk-target` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"TargetTypes": {
  "AWS-MSK": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/aws-msk-target/lib"],
    "FactoryClassName": "com.amazonaws.sfc.awsmsk.AwsMskTargetWriter"
  }
}
```

> **Known limitation:** the in-process form does not deliver data today. `sfc-main` loads the target's IAM authentication classes from its own libraries instead of from the target's `JarFiles`. There they cannot find the Kafka client classes, so the first record fails with `NoClassDefFoundError`. Use the uberjar or IPC form for this target.

**IPC** - no `TargetTypes`; the target runs as its own service:

```json
"Targets": {
  "MskTarget": {
    "TargetType": "AWS-MSK",
    "TargetServer": "MskTargetServer"
  }
},
"TargetServers": {
  "MskTargetServer": { "Address": "localhost", "Port": 50001 }
}
```

Start the service before SFC, on the port of its `TargetServers` entry:

**Linux / macOS**

```shell
aws-msk-target/bin/aws-msk-target -port 50001
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\aws-msk-target\lib\*" com.amazonaws.sfc.awsmsk.AwsMskTargetService -port 50001
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.awsmsk.AwsMskTargetService -port 50001` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.awsmsk.AwsMskTargetService -port 50001`).

**Examples:** uberjar: [uberjar-sim-msk](../../examples/uberjar-sim-msk/README.md) · in-process: [in-process-opcua-msk](../../examples/in-process-opcua-msk/README.md) (affected by the in-process limitation above) · IPC: [ipc-opcua-msk](../../examples/ipc-opcua-msk/README.md) · all: [examples catalog](../examples/README.md)

## AwsMskTargetConfiguration

AwsMskTargetConfiguration extends the type  [TargetConfiguration](../core/target-configuration.md) with specific configuration data for connecting to and sending to an AWS MSK topic. The Targets configuration element can contain entries of this type, the TargetType of these entries must be set to **"AWS-MSK"**

Required IAM permissions are `kafka-cluster:Connect`, `kafka-cluster:DescribeTopic` and `kafka-cluster:WriteData`. Add `kafka-cluster:WriteDataIdempotently` when [Acknowledgements](#acknowledgements) is `all`, and `kafka-cluster:CreateTopic` only if the cluster creates the topic automatically.

- [Schema](#awsmsktargetconfiguration-schema)
- [Examples](#awsmsktargetconfiguration-examples)

**Properties:**
- [Acknowledgements](#acknowledgements)
- [BatchSize](#batchsize)
- [BootstrapBrokers](#bootstrapbrokers)
- [Compression](#compression)
- [CredentialProviderClient](#credentialproviderclient)
- [Endpoint](#endpoint)
- [Formatter](#formatter)
- [Headers](#headers)
- [Interval](#interval)
- [Key](#key)
- [Partition](#partition)
- [ProviderProperties](#providerproperties)
- [Serialization](#serialization)
- [Template](#template)
- [TopicName](#topicname)

---
### Acknowledgements
Acknowledgements (acks) controls the durability and reliability of message delivery to the Kafka cluster.

**Type** : String

- "none" = 0: No acknowledgement required - fastest but may lose data
- "leader" = 1 (default): Leader acknowledgement only - balanced between durability and performance
- "all" = -1: All replicas must acknowledge - highest durability but slower performance



---
### BatchSize
Batch size (batch.size)

Maximum size in bytes of a per-partition batch (Kafka `batch.size`); it is not a number of records. If not set, the Kafka default (16384 bytes) applies. Larger batch sizes can improve throughput and reduce network overhead, but increase latency and memory usage.

**Type**: Integer

---
### BootstrapBrokers
Addresses with port number for bootstrap brokers for AWS MSK cluster. (bootstrap.servers)

**Type**: List[String]

To get the broker addresses for a cluster use the AWS CLI command (the same in PowerShell):

```shell
aws kafka get-bootstrap-brokers --cluster-arn ClusterArn --query BootstrapBrokerStringPublicSaslIam --output text
```

This prints the comma-separated IAM broker addresses for public access (port 9198); add each address to the list. For access from within AWS, for example from the cluster's VPC, query `BootstrapBrokerStringSaslIam` (port 9098) instead. The target connects with IAM authentication over TLS (`SASL_SSL`, `AWS_MSK_IAM`), so other broker addresses, such as the plaintext ones on port 9092, do not work.

See also 
[Getting the bootstrap brokers for an Amazon MSK cluster](https://docs.aws.amazon.com/msk/latest/developerguide/msk-get-bootstrap-brokers.html)

---
### Compression
Compression type (compression.type)

Specifies the compression algorithm used for data sent to the MSK cluster. Compression reduces network bandwidth usage and storage at the cost of some CPU overhead.

Possible values:

- "none" (default): No compression
- "snappy" : Fast compression/decompression with good compression ratio
- "lz4" : Very fast compression/decompression
- "gzip" : High compression ratio but more CPU intensive
- "zstd" : High compression ratio with good performance

**Type**: String



---
### CredentialProviderClient

The CredentialProviderClient property specifies which AWS credential provider client to use for authentication. It references a client defined in the SFC's top-level configuration under [AwsIotCredentialProviderClients](../core/sfc-configuration.md#awsiotcredentialproviderclients) section. This client uses X.509 certificates to obtain temporary AWS credentials through the  [AWS IoT credentials provider](../sfc-aws-service-credentials.md).

If no CredentialProviderClient is configured the [AWS Java SDK credential provider chain is used](https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/credentials.html#credentials-chain)

When a CredentialProviderClient is configured, this target passes the credentials to the MSK IAM authentication module as JVM system properties (`aws.accessKeyId`, `aws.secretAccessKey`, `aws.sessionToken`). These properties apply to the whole process, and the AWS SDK default credential provider chain checks Java system properties first, so other AWS targets in the same process that have no CredentialProviderClient can end up using these credentials; run this target as an IPC service if they need a different identity.

**Type:** String

---

### Endpoint

Not used by this target; the Kafka producer finds the cluster through the [BootstrapBrokers](#bootstrapbrokers).

**Type:** String

---

### Formatter

Configuration allows for custom formatting of data written by a target. A [custom formatter](../sfc-extending.md#custom-formatters), implemented as a JVM class, converts a sequence of target data messages into a specific format and returns the formatted data as an array of bytes.

Formatter and [Template](#template) are mutually exclusive; setting both is a configuration error.

**Type:** [InProcessConfiguration](../core/in-process-configuration.md)

---

### Headers

Map of headers set for written records.

Allows setting custom key-value pairs as Kafka message headers. These headers are metadata that will be attached to each record written to the MSK cluster. Headers can be used for message filtering, routing, or carrying additional metadata alongside the message payload.

Every record also gets a header named after the Serial entry of [ElementNames](../core/sfc-configuration.md#elementnames) (default `serial`) that holds the record serial.

**Type**: Map[String,String]

Default = empty map

---
### Interval
Interval in milliseconds in which adapter will flush the producer even when the batch size is not reached.

Controls how long the producer will wait to accumulate messages before sending them to MSK, even if the [batch size](#batchsize) has not been reached. This ensures messages are sent within a reasonable timeframe during periods of low message volume. A lower interval reduces latency but may decrease throughput.

Set this property (for example `1000`). Without it, every successfully written record logs an error from the send callback, although the data is delivered.

**Type**: Integer

---
### Key
Optional key used for the written records.

Specifies the key that will be attached to all messages written to MSK. The key is used by Kafka for message partitioning and maintaining message order within partitions. When not specified, messages will be distributed across partitions in a round-robin manner.

**Type**: String

---
### Partition
Optional partition key

Specifies the target partition number in the Kafka topic where messages will be written. When specified, all messages will be sent to this specific partition. If not specified, Kafka will distribute messages across available partitions based on the message key (if provided) or using its default partitioning strategy.

**Type**: Integer

---
### ProviderProperties
Map of provider properties used to create the Kafka producer

Additional configuration properties for the Kafka producer client. These properties will be passed directly to the underlying Kafka producer instance.

**Type**: Map[String,String]

Default is an empty map

A description af producer options can be found in the Kafka documentation

The following properties are set by the adapter

- bootstrap.servers from `BootstrapBrokers`
- client.id = "sfc-msk-target-" + hostname
- security.protocol = "SASL_SSL"
- acks from `Acknowledgements`
- compression.type from `Compression`
- key.serializer = "org.apache.kafka.common.serialization.StringSerializer"
- value.serializer = "org.apache.kafka.common.serialization.ByteArraySerializer"
- sasl.client.callback.handler.class = "software.amazon.msk.auth.iam.IAMClientCallbackHandler"
- sasl.jaas.config =  "software.amazon.msk.auth.iam.IAMLoginModule required;"
- sasl.mechanism = "AWS_MSK_IAM"
- batch.size from `BatchSize` (only when set)

Any additional valid Kafka producer properties can be specified in this map to customize the producer behavior. Entries in ProviderProperties are applied last and override the values above.



---
### Serialization
Serialization (value.serializer)

Specifies the format used to serialize message values before sending them to MSK.

Supported values:

- "json" (default): Messages are serialized as JSON format
- "protobuf": Messages are serialized using Protocol Buffers format. When using this option, the message structure must conform to the protobuf schema defined in the [TargetAdapterService schema](../../core/sfc-ipc/src/main/proto/TargetAdapterService.proto) 

If a Template is specified to transform the data for this target then this setting is not used and the transformation output is written as a string to the topic.

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
### TopicName
Specifies the name of the Kafka topic in the MSK cluster where messages will be written. The topic must exist in the MSK cluster before messages can be written to it. Topic names must be between 1 and 255 characters in length and can contain alphanumeric characters, dots (.), underscores (_), and hyphens (-).

**Type**: String

### AwsMskTargetConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AwsMskTargetConfiguration",
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
        "Acknowledgements": {
          "type": "string",
          "description": "Acknowledgement level for messages",
          "enum": ["none", "leader", "all"],
          "default": "leader"
        },
        "BatchSize": {
          "type": "integer",
          "description": "Maximum batch size in bytes per partition (Kafka batch.size)"
        },
        "BootstrapBrokers": {
          "type": "array",
          "description": "List of bootstrap broker addresses",
          "items": {
            "type": "string"
          },
          "minItems": 1
        },
        "Compression": {
          "type": "string",
          "description": "Compression type for messages",
          "enum": ["none", "snappy", "lz4", "gzip", "zstd"],
          "default": "none"
        },
        "CredentialProviderClient": {
          "type": "string",
          "description": "The credential provider client name"
        },
        "Headers": {
          "type": "object",
          "description": "Message headers"
        },
        "Interval": {
          "type": "integer",
          "description": "Interval in milliseconds between batch publishes"
        },
        "Key": {
          "type": "string",
          "description": "Message key"
        },
        "Partition": {
          "type": "integer",
          "description": "Partition number"
        },
        "ProviderProperties": {
          "type": "object",
          "description": "Provider specific properties",
          "additionalProperties": {
            "type": "string"
          }
        },
        "Serialization": {
          "type": "string",
          "description": "Message serialization format",
          "enum": ["json", "protobuf"],
          "default" : "json"
        },
        "TopicName": {
          "type": "string",
          "description": "Name of the MSK topic"
        }
      },
      "required": ["TopicName", "BootstrapBrokers"]
    }
  ]
}

```

### AwsMskTargetConfiguration Examples



```json
{
  "TargetType" : "AWS-MSK",    
  "TopicName": "data-topic",
  "BootstrapBrokers": ["<broker-1-host>:9098", "<broker-2-host>:9098"],
  "Compression": "gzip",
  "Acknowledgements": "all",
  "Serialization": "json",
  "Interval": 1000,
  "CredentialProviderClient": "aws-credentials-provider"
}

```

[^top](#aws-msk-target)

