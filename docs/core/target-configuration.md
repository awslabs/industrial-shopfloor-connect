## TargetConfiguration

[SFC Configuration](./sfc-configuration.md) > [Targets](./sfc-configuration.md#targets) 

Defines core configuration settings for [SFC target adapters](./sfc-configuration.md#targets) that specify how data should be published or written to destinations. Target adapters extend this base configuration with protocol-specific properties to handle different output requirements and destinations.

How a target is configured in the uberjar, in-process and IPC modes: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode).

- [Schema](#schema)
- [Examples](#examples)

**Properties:**

- [Active](#active)
- [AsArrayWhenBuffered](#asarraywhenbuffered)
- [CredentialProviderClient](#credentialproviderclient)
- [Description](#description)
- [Formatter](#formatter)
- [Metrics](#metrics)
- [TargetServer](#targetserver)
- [TargetChannelSize](#targetchannelsize)
- [TargetChannelTimeout](#targetchanneltimeout)
- [TargetType](#targettype)
- [Template](#template)
- [TemplateEpochTimestamp](#templateepochtimestamp)
- [UnquoteNumericJsonValues](#unquotenumericjsonvalues)

---
### Active
Controls whether the target is actively processing and outputting data. When set to false, the target suspends its output operations. This allows for temporary disabling of specific targets without removing their configuration. Defaults to true if not specified

**Type**: Boolean

---
### AsArrayWhenBuffered
Controls JSON array formatting for buffered data output. When true (default), data is wrapped in array brackets with comma separators. Setting to false removes array notation, reducing output size by eliminating brackets and separators. Warning: keep true if output contains numeric-only key names to maintain valid JSON structure.

**Type**: Boolean

Default is true

---
### CredentialProviderClient

The CredentialProviderClient property specifies which AWS credential provider client to use for authentication. It references a client defined in the SFC's top-level configuration under [AwsIotCredentialProviderClients](../core/sfc-configuration.md#awsiotcredentialproviderclients) section. This client uses X.509 certificates to obtain temporary AWS credentials through the  [AWS IoT credentials provider](../sfc-aws-service-credentials.md).

If no CredentialProviderClient is configured the [AWS Java SDK credential provider chain is used](https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/credentials.html#credentials-chain)

**Type:** String

---
### Description

Provides a free-form text field where users can add descriptive information about the target to document its purpose or characteristics.

Type: String

---

### Formatter

Configuration allows for custom formatting of data written by a target. A [custom formatter](../sfc-extending.md#custom-formatters), implemented as a JVM class, converts a sequence of target data messages into a specific format and returns the formatted data as an array of bytes.

Formatter and [Template](#template) are mutually exclusive; setting both is a configuration error. A formatter is applied by the AWS IoT Core, AWS Kinesis Firehose, AWS Kinesis, AWS MSK, AWS S3, AWS SNS, AWS SQS, Debug, File, MQTT and NATS targets.

Example using the formatter from the [custom target formatter example](../../examples/custom-target-formatter/README.md), which is included in the uberjar, so `FactoryClassName` is enough. Outside the uberjar add [JarFiles](./in-process-configuration.md#jarfiles) with the location of the formatter's jar file.

```json
"Formatter": {
  "FactoryClassName": "com.amazonaws.sfc.formatter.CustomTargetFormatter"
}
```

**Type:** [InProcessConfiguration](./in-process-configuration.md)

---

### Metrics

Defines the configuration settings for collecting and reporting metrics from the target. This allows monitoring and measurement of the target adapter's performance and behavior using the specified metrics configuration parameters.

Type: [MetricsSourceConfiguration](./metrics-source-configuration.md)

---

### TargetServer

Specifies the identifier of a remote server running the target as an IPC service. When configured, the target operates as an external service rather than within the SFC core process, communicating via gRPC, and no [TargetTypes](./sfc-configuration.md#targettypes) entry is needed. The server must be defined in the [TargetServers](./sfc-configuration.md#targetservers) configuration section and implement the [TargetAdapterService](../sfc-extending.md#ipc-target-services) gRPC interface. [TargetType](#targettype) is still required. This enables distributed deployment of targets across different processes or machines.

**Type**: String

---
### TargetChannelSize

Defines the capacity of the internal channel buffer used by the target for processing and writing data items. This setting affects how many items can be queued for processing before backpressure is applied. The default value is 1000 items. Adjusting this value can help optimize performance and memory usage based on your specific use case and system resources

For more information see [SFC Tuning](../sfc-tuning.md).

**Type**: Int

Default is 1000

---
### TargetChannelTimeout
Specifies the maximum time (in milliseconds) that the system will wait when attempting to write to the target's internal channel if it is at capacity. After this timeout period expires, the write operation will fail. The default timeout is 10000 milliseconds (10 seconds). This setting helps prevent indefinite blocking when the target channel becomes full.

 For more information see [SFC Tuning](../sfc-tuning.md)

**Type**: Int

Default is 10000

---
### TargetType
Identifies the specific type of target adapter to be used through a unique code (like "AWS-SQS" or "AWS-KINESIS"). The value must be the type code of the target; the targets in this repository use AWS-IOT-CORE, AWS-FIREHOSE, AWS-KINESIS, AWS-LAMBDA, AWS-MSK, AWS-S3, AWS-S3-TABLES, AWS-SITEWISE, AWS-SITEWISEEDGE-TARGET, AWS-SNS, AWS-SQS, DEBUG-TARGET, FILE-TARGET, MQTT-TARGET, NATS-TARGET, OPCUA-TARGET, OPCUA-WRITER-TARGET, ROUTER and STORE-FORWARD. A target implementation only accepts targets of its own type. This property is required in every deployment mode. For targets running in the SFC core process (uberjar or in-process), the key of the target's entry in the [TargetTypes](./sfc-configuration.md#targettypes) configuration section is the same value; when [TargetServer](#targetserver) is set (IPC), no TargetTypes entry is needed. The type code helps the system instantiate the correct target implementation and validate its configuration parameters. All types and classes: [Target types and classes](../sfc-running-targets.md#target-types-and-classes).

**Type**: String

---
### Template
Specifies the file path to an [Apache velocity](https://velocity.apache.org/)  template used for  [transforming the output data](../sfc-target-templates.md) of the target. This optional setting enables custom formatting of data before it is sent to the target. Available context variables include:

- $schedule
- $sources
- $metadata
- $serial
- $timestamp
- names specified in ElementNames configuration
- $tab (for inserting tab characters)

The following [Velocity tools](https://velocity.apache.org/tools/3.1/tools-summary.html) can be used in the transformation template:

- $date
- $collection
- $context
- $math
- $number

Additional epoch timestamp values can be added to the data used for the transformation by setting the [TemplateEpochTimestamp](#templateepochtimestamp) property to true,

For targets where the data does not require specific output format, the data is serialized as [JSON data](../sfc-data-format.md#sfc-output-data-schemas).

Template and a custom [formatter](#formatter) are mutually exclusive; setting both for a target is a configuration error.

Example templates (CSV, XML, YAML): [transformation-templates](../../examples/transformation-templates/README.md).

**Type**: String

---

### TemplateEpochTimestamp

Controls whether the target data used for a [template](#template) transformation should have additional epoch seconds and epoch nanoseconds offset values for each timestamp in the data.

These values are added at the same level as the timestamp in the output data and have the name of the [timestamp](./sfc-configuration.md#elementnames) element, which defaults to `timestamp`, with an `_epoch_sec` and `_epoch_offset_nanosec` postfix. 

So with the default names for timestamp these fields will be named 
- `timestamp_epoch_sec` and 
- `timestamp_epoch_offset_nanosec`.

Type : Boolean

Default is false


---
### UnquoteNumericJsonValues
Controls whether numeric values in JSON output should have their surrounding double quotes removed. When set to true, numeric values will be output without quotes, potentially reducing the output size. Default is false. This setting can reduce the size of the output by stripping redundant double quotes. Important: Do not set this flag to true if any key names in the output consist of numbers only, as this could result in invalid JSON.

**Type**: Boolean 

Default is false

Example effect when true:

Before (UnquoteNumericJsonValues: false)
```json
{"temperature": "75.2", "humidity": "45"}
```

After (UnquoteNumericJsonValues: true)
```json
{"temperature": 75.2, "humidity": 45}
```



[^top](#targetconfiguration)



## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "title": "Target Configuration",
  "description": "Configuration for a target",
  "properties": {
    "Active": {
      "type": "boolean",
      "default": true,
      "description": "Flag indicating if the target is active"
    },
    "AsArrayWhenBuffered": {
      "type": "boolean",
      "default": true,
      "description": "Flag indicating if buffered data should be sent as an array"
    },
    "CredentialProviderClient": {
      "type": "string",
      "description": "Reference to a CredentialsClient defined in AwsIotCredentialProviderClients"
    },
    "Description": {
      "type": "string",
      "description": "Description of the target"
    },
    "Formatter": {
      "$ref": "#/definitions/InProcessConfiguration",
      "description": "Custom output formatter configuration"
    },
    "TargetServer": {
      "type": "string",
      "description": "Reference to a TargetServer defined in TargetServers, runs the target as an IPC service"
    },
    "TargetChannelSize": {
      "type": "integer",
      "default" : 1000,
      "description": "Size of the target channel"
    },
    "TargetChannelTimeout": {
      "type": "integer",
      "default": 10000,
      "description": "Timeout for the target channel in milliseconds"
    },
    "TargetType": {
      "type": "string",
      "description": "Type code of the target (e.g. AWS-SQS), in uberjar and in-process mode also the key of the TargetTypes entry"
    },
    "Template": {
      "type": "string",
      "description": "Template for target output formatting"
    },
    "TemplateEpochTimestamp": {
      "type": "boolean",
      "default": false,
      "description": "Flag indicating if epoch timestamp values are added to the data used by the template"
    },
    "UnquoteNumericJsonValues": {
      "type": "boolean",
      "default": false,
      "description": "Flag indicating if numeric JSON values should be unquoted"
    }, 
    "Metrics": {
      "$ref": "#/definitions/MetricsSourceConfiguration",
      "description": "Configuration for metrics collection"
    }
  },
  "required": ["TargetType"]
}

```



## Examples

**<u>Note: TargetConfigurations always are instances of extended types with specific additional properties for the implementation of that type of target adapter.</u>**

Basic configuration of a target running in the SFC core process (uberjar or in-process) with a local TargetType (not requiring AWS credentials)

```json
{
  "TargetType": "DEBUG-TARGET"
}
```



Basic configuration of a target running in the SFC core process with an AWS TargetType and a credential provider client:

```json
{
  "TargetType": "AWS-SQS",
  "CredentialProviderClient": "IotCredentialsClientName"
}
```



Configuration with TargetServer, target running as an IPC service (TargetType is still required, no TargetTypes entry is needed):

```json
{
  "TargetType": "AWS-S3",
  "TargetServer": "S3TargetServer",
  "CredentialProviderClient": "IotCredentialsClientName"
}
```

