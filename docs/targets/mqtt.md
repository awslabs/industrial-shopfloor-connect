# MQTT Target

[SFC Configuration](../core/sfc-configuration.md) > [Targets](../core/sfc-configuration.md#targets) >  [Target](../core/target-configuration.md) 

The SFC MQTT target adapter enables publishing collected data to MQTT brokers using configurable topic patterns. Topics can be dynamically constructed using target data and  metadata from the source readings. The adapter supports various MQTT protocol configurations, authentication methods, and quality of service (QoS) levels for reliable message delivery. 

## Deploy this target

`TargetType` is `MQTT-TARGET` in every deployment mode. In the uberjar and in-process modes the `TargetTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode). All types and classes: [Target types and classes](../sfc-running-targets.md#target-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"TargetTypes": {
  "MQTT-TARGET": { "FactoryClassName": "com.amazonaws.sfc.mqtt.MqttTargetWriter" }
}
```

**In-process** - module bundle `mqtt-target` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"TargetTypes": {
  "MQTT-TARGET": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/mqtt-target/lib"],
    "FactoryClassName": "com.amazonaws.sfc.mqtt.MqttTargetWriter"
  }
}
```

**IPC** - no `TargetTypes`; the target runs as its own service:

```json
"Targets": {
  "MqttTarget": {
    "TargetType": "MQTT-TARGET",
    "TargetServer": "MqttTargetServer"
  }
},
"TargetServers": {
  "MqttTargetServer": { "Address": "localhost", "Port": 50001 }
}
```

Start the service before SFC, on the port of its `TargetServers` entry:

**Linux / macOS**

```shell
mqtt-target/bin/mqtt-target -port 50001
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\mqtt-target\lib\*" com.amazonaws.sfc.mqtt.MqttTargetService -port 50001
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.mqtt.MqttTargetService -port 50001` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.mqtt.MqttTargetService -port 50001`).

**Examples:** uberjar: [uberjar-mqtt-file](../../examples/uberjar-mqtt-file/README.md) · all: [examples catalog](../examples/README.md)

## MqttTargetConfiguration

MqttTargetConfiguration extends the type TargetConfiguration with specific configuration data for connecting to and sending to MQTT topics. The Targets configuration element can contain entries of this type; the TargetType of these entries must be set to **"MQTT-TARGET"**.

- [Schema](#mqtttargetconfiguration-schema)
- [Examples](#mqtttargetconfiguration-examples)

**Properties:**
- [AlternateTopicName](#alternatetopicname)
- [BatchCount](#batchcount)
- [BatchInterval](#batchinterval)
- [BatchSize](#batchsize)
- [Certificate](#certificate)
- [ClientId](#clientid)
- [Compression](#compression)
- [ConnectRetries](#connectretries)
- [ConnectTimeout](#connecttimeout)
- [EndPoint](#endpoint)
- [Formatter](#formatter)
- [MaxPayloadSize](#maxpayloadsize)
- [Password](#password)
- [Port](#port)
- [PrivateKey](#privatekey)
- [PublishTimeout](#publishtimeout)
- [Qos](#qos)
- [Retain](#retain)
- [RootCA](#rootca)
- [SslServerCertificate](#sslservercertificate)
- [Template](#template)
- [TopicName](#topicname)
- [Username](#username)
- [WaitAfterConnectError](#waitafterconnecterror)
- [WarnAlternateTopicName](#warnalternatetopicname)

---
### AlternateTopicName
An alternative topic name or template to use when the primary [TopicName](#topicname) contains unmapped placeholder variables that cannot be resolved. This serves as a fallback publishing destination when dynamic topic name construction fails.

**Type**: String

---
### BatchCount
The maximum number of messages to accumulate in the buffer before triggering a batch publish to the MQTT topic. When this count is reached, all buffered messages are sent as an array in a single MQTT message.

Batching is triggered when any configured threshold (BatchCount, [BatchSize](#batchsize), or [BatchInterval](#batchinterval)) is reached

**Type**: Int

---
### BatchInterval
The maximum time in milliseconds to hold messages in the buffer before publishing them as a batch to the MQTT topic, regardless of whether [BatchSize](#batchsize) or [BatchCount](#batchcount) limits have been reached.

Batching is triggered when any configured threshold ([BatchCount](#batchcount), [BatchSize](#batchsize), or BatchInterval) is reached

**Type**: Int

---
### BatchSize
The maximum total size in kilobytes of uncompressed message payloads to accumulate before triggering a batch publish to the MQTT topic. When this size threshold is reached, all buffered messages are sent as an array in a single MQTT message.

Batching is triggered when any configured threshold ([BatchCount](#batchcount), BatchSize, or [BatchInterval](#batchinterval)) is reached

**Type**: Int

---
### Certificate
The file system path to the client certificate file used for authentication with the MQTT broker.

Required for `ssl://` endpoints, see [EndPoint](#endpoint).

**Type**: String

---

### ClientId

The Client ID is a unique identifier that is used to connect to the MQTT broker. If no Client ID is specified, a unique client ID is generated by the target. Specify the Client ID to ensure that it is used when sending messages to your Broker. This property needs to be configured when integrating with a Broker on an AWS IoT Greengrass V2 Device. The `aws.greengrass.clientdevices.Auth` component expects the MQTT Client ID to match the AWS IoT Thing name.

**Type**: String

---
### Compression
The compression algorithm to apply to MQTT message payloads before publishing to the broker. Compressing messages can reduce bandwidth usage and transmission time.

**Type:** String

Possible values:

- "None" (Default)
- "Zip"
- "GZip"

---
### ConnectRetries
The maximum number of attempts to establish a connection with the MQTT broker when the initial connection fails.

**Type**: Int

Default is 10

---
### ConnectTimeout
The maximum time in seconds to wait for establishing a connection with the MQTT broker before timing out.

**Type**: Int

Default is 10 seconds. A configured value currently has no effect; the timeout is always 10 seconds.

---
### EndPoint
The address of the MQTT broker, including the protocol scheme: `tcp://` for an unencrypted connection, `ssl://` for TLS. There is no separate property that selects TLS. Without a scheme, `tcp://` is added, or `ssl://` when [RootCA](#rootca), [Certificate](#certificate) or [PrivateKey](#privatekey) is set.

**Type**: String

- `tcp://`: include the port, e.g. `"EndPoint": "tcp://broker.example.com:1883"`, and set the same port in [Port](#port).
- `ssl://`: give the host only, e.g. `"EndPoint": "ssl://broker.example.com"`, and set [Port](#port) to 8883. The target connects to port 8883 for `ssl://` endpoints, and a port in an `ssl://` EndPoint currently makes the connection fail, so TLS works only with brokers that listen on 8883. `ssl://` requires [RootCA](#rootca), [Certificate](#certificate) and [PrivateKey](#privatekey) (client certificate authentication).

For AWS IoT Core, use `ssl://` with the ATS endpoint of your account and Port 8883. To get the ATS endpoint for an account use the AWS CLI command (the same in PowerShell):

```shell
aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text
```
https://awscli.amazonaws.com/v2/documentation/api/latest/reference/iot/describe-endpoint.html

---

### Formatter

Configuration allows for custom formatting of data written by a target. A [custom formatter](../sfc-extending.md#custom-formatters), implemented as a JVM class, converts a sequence of target data messages into a specific format and returns the formatted data as an array of bytes.

Formatter and [Template](#template) are mutually exclusive; setting both is a configuration error.

**Type:** [InProcessConfiguration](../core/in-process-configuration.md)


---
### MaxPayloadSize
The maximum size in kilobytes allowed for a single MQTT message payload.

- When compression is enabled, the original uncompressed payload size may exceed this limit
- For batched messages without compression, reaching this size limit will trigger sending the batch
- Used as a threshold for batch publishing when batching is enabled

**Type**: Int


---
### Password
The password credential for authenticating with the MQTT broker when using username/password authentication.

[Username](#username) and password should not be included as clear text in the configuration. It is strongly recommended to use placeholders and use the SFC integration with the [AWS secrets manager](../core/secrets-manager-configuration.md).

**Type**: String

---
### Port
The TCP port number used to connect to the MQTT broker. When it is not set, a port in the [EndPoint](#endpoint) sets it; a configuration with neither Port nor a port in the EndPoint is rejected.

**Type**: Integer

Commonly port numbers are

- 1883 for `tcp://` endpoints
- 8883 for `ssl://` endpoints, including AWS IoT Core endpoints

With `tcp://` put the same port in the [EndPoint](#endpoint); with `ssl://` use 8883 and leave the port out of the EndPoint.

---
### PrivateKey
The file system path to the private key file used for client authentication with the MQTT broker.

Required for `ssl://` endpoints, see [EndPoint](#endpoint).

**Type**: String

---
### PublishTimeout
The maximum time in seconds to wait for a message to be published to the MQTT broker before timing out.

**Type**: Int

Default is 10 seconds. A configured value currently has no effect.

---
### Qos
The MQTT Quality of Service (QoS) level for message delivery. The key is spelled `Qos`; a `QoS` key is ignored and the level stays 0.

- 0: At most once (Fire and forget), the default.
- 1: At least once (Guaranteed delivery, but possible duplicates)
- 2: Exactly once (Guaranteed delivery exactly one time)

**Type**: Integer



---
### Retain
Controls whether messages should be retained by the MQTT broker. 

When set to true, the broker will store the last message published to each topic. New subscribers to these topics will immediately receive the most recent retained message, even if it was published before they subscribed.

**Type**: Boolean

Default is false

---
### RootCA
The file system path to the Root Certificate Authority (CA) certificate file used to validate the broker's identity.

Required for `ssl://` endpoints, see [EndPoint](#endpoint).

**Type**: String

---
### SslServerCertificate
The file system path to a server certificate file for `ssl://` endpoints. The file must exist.

The setting is currently not used to verify the broker: the target trusts the certificate that the broker presents.

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
The MQTT topic name or topic name template for publishing messages.

**Type**: String

A template can be used for the topicName to render the actual topic name using placeholders. In this template, 
besides placeholders for environment variables (${name}), the following placeholders are available:

- %schedule%
- %target%
- %source%
- %channel%

To utilize the metadata values at the source or channel level of the target data, the name of the metadata value can be utilized with a '%' prefix and postfix.

Value placeholders can be employed to incorporate additional topic levels or grouping values to a specific topic.

Template examples:

- plant1-**%source%** : Values from each source will be published to a topic for that source
- plant1-**%line%**   : Values from all sources will be grouped by the value of the %line% metadata and published to a topic for that value

In case a placeholder is not resolved, when a value for a used placeholder is part of the data,
then an alternative topic name can be configured by setting the name of that topic to the [AlternateTopicName](#alternatetopicname) setting.

Note that the use of placeholders to send data to specific topics will result in additional publish calls to the broker.



---
### Username
The username credential for authenticating with the MQTT broker when using username/password authentication

Username and [password](#password) should not be included as clear text in the configuration. It is strongly recommended to use placeholders and use the SFC integration with the [AWS secrets manager](../core/secrets-manager-configuration.md).

**Type**: String

---
### WaitAfterConnectError
The delay period in seconds before attempting to reconnect after a failed connection to the MQTT broker.

**Type**: Int

Default is 10 seconds

---
### WarnAlternateTopicName
Controls whether a warning message should be generated when data is published to the alternate topic name.

When enabled, logs a warning message if the system falls back to using the [AlternateTopicName](#alternatetopicname) due to unresolved placeholders in the main topic name

**Type**: Boolean

Default is true



### MqttTargetConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "MqttTargetConfiguration",
  "type": "object",
  "allOf": [
    {
      "$ref": "#/definitions/TargetConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "AlternateTopicName": {
          "type": "string",
          "description": "Alternate topic name when dynamic propery has unresolved placeholders"
        },
        "BatchCount": {
          "type": "integer",
          "description": "Number of messages to batch before publishing"
        },
        "BatchInterval": {
          "type": "integer",
          "description": "Interval in milliseconds between batch publishes"
        },
        "BatchSize": {
          "type": "integer",
          "description": "Maximum size of batched messages in KB"
        },
        "Certificate": {
          "type": "string",
          "description": "Client certificate for TLS authentication"
        },
        "ClientId":{
           "type": "string",
           "description": "Client id for MQTT broker connection "
        },
        "Compression": {
          "type": "string",
          "description": "Type of message compression",
          "enum": ["None", "Zip", "GZip"],
          "default": "None"
        },
        "ConnectRetries": {
          "type": "integer",
          "description": "Number of connection retry attempts"
        },
        "ConnectTimeout": {
          "type": "integer",
          "description": "Connection timeout in seconds"
        },
        "EndPoint": {
          "type": "string",
          "description": "MQTT broker endpoint, starting with tcp:// or ssl://"
        },
        "MaxPayloadSize": {
          "type": "integer",
          "description": "Maximum size of message payload in KB"
        },
        "Password": {
          "type": "string",
          "description": "Password for authentication"
        },
        "Port": {
          "type": "integer",
          "description": "Port number for MQTT connection"
        },
        "PrivateKey": {
          "type": "string",
          "description": "Private key for TLS authentication"
        },
        "PublishTimeout": {
          "type": "integer",
          "description": "Timeout for publish operations in seconds"
        },
        "Qos": {
          "type": "integer",
          "description": "Quality of Service level",
          "enum": [0, 1, 2],
          "default": 0
        },
        "Retain": {
          "type": "boolean",
          "description": "Whether messages should be retained by broker"
        },
        "RootCA": {
          "type": "string",
          "description": "Root CA certificate"
        },
        "SslServerCertificate": {
          "type": "string",
          "description": "SSL server certificate"
        },
        "TopicName": {
          "type": "string",
          "description": "Primary topic name"
        },
        "Username": {
          "type": "string",
          "description": "Username for authentication"
        },
        "WaitAfterConnectError": {
          "type": "integer",
          "description": "Wait time in seconds after a connection error"
        },
        "WarnAlternateTopicName": {
          "type": "boolean",
          "description": "Whether to warn when using alternate topic"
        }
      },
      "required": ["EndPoint", "TopicName"]
    }
  ]
}

```

### MqttTargetConfiguration Examples

To try the target, replace the `DebugTarget` of [Quickstart step 2](../../README.md#2-helloworld-simulator-example) with this entry (also in the schedule's `Targets`) and add the uberjar `TargetTypes` entry from [Deploy this target](#deploy-this-target). It publishes every record to the topic `sfc/demo` of a broker on the same host, for example Mosquitto on port 1883:

```json
"Targets": {
  "MqttTarget": {
    "TargetType": "MQTT-TARGET",
    "EndPoint": "tcp://127.0.0.1:1883",
    "Port": 1883,
    "TopicName": "sfc/demo",
    "Qos": 1
  }
}
```

MQTT Configuration using (secret) placeholders for username and password

```json
{
  "TargetType" : "MQTT-TARGET",
  "EndPoint": "tcp://mqtt.example.com:1883",
  "Port": 1883,
  "TopicName": "sensors/data",
  "Qos": 1,
  "Username": "${username}",
  "Password": "${password}",
  "ConnectTimeout": 30
}
```

Secure MQTT with TLS:

```json
{
  "TargetType" : "MQTT-TARGET",
  "EndPoint": "ssl://secure-mqtt.example.com",
  "Port": 8883,
  "TopicName": "production/metrics",
  "Certificate": "/path/to/client-cert.pem",
  "PrivateKey": "/path/to/private-key.pem",
  "RootCA": "/path/to/root-ca.pem",
  "Qos": 2,
  "Compression": "GZip",
  "BatchSize": 1024,
  "BatchInterval": 5000
}
```

On Windows write the certificate paths with forward slashes, e.g. `"Certificate": "C:/sfc/certs/client-cert.pem"`, `"PrivateKey": "C:/sfc/certs/private-key.pem"` and `"RootCA": "C:/sfc/certs/root-ca.pem"`.

Configuration  with dynamic topic names from target- and metadata values

```json
{
  "TargetType" : "MQTT-TARGET",
  "EndPoint": "tcp://mqtt.internal.com:1883",
  "Port": 1883,
  "TopicName": "data/%location%/%line%/%source%",
  "AlternateTopicName": "data/sensors",
  "WarnAlternateTopicName": true
}
```



[^top](#mqtt-target)

