# MQTT Protocol Configuration

[SFC Configuration](../core/sfc-configuration.md) > [Sources](../core/sfc-configuration.md#sources) >  [Source](../core/source-configuration.md) 

The MQTT source protocol adapter enables SFC to collect data from MQTT brokers by subscribing to specified topics. It subscribes with MQTT 3.1.1 (Eclipse Paho) at QoS 1, over plain TCP or TLS, with optional username/password authentication, wildcard topics and topic name mapping. The adapter can process both structured and unstructured MQTT messages, converting them into the standardized SFC channel format for further processing and storage.

This adapter is particularly useful in IoT scenarios where devices and sensors publish their data to MQTT topics, allowing SFC to integrate seamlessly with existing MQTT-based infrastructure. The client ID is generated (`MqttAdapter-<adapter>-<UUID>`). The adapter only reads; to publish to a broker, use the [MQTT target](../targets/mqtt.md).

## Deploy this adapter

`AdapterType` is `MQTT` in every deployment mode. In the uberjar and in-process modes the `AdapterTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode). All types and classes: [Protocol adapter types and classes](../sfc-running-adapters.md#protocol-adapter-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"AdapterTypes": {
  "MQTT": { "FactoryClassName": "com.amazonaws.sfc.mqtt.MqttAdapter" }
}
```

**In-process** - module bundle `mqtt` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"AdapterTypes": {
  "MQTT": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/mqtt/lib"],
    "FactoryClassName": "com.amazonaws.sfc.mqtt.MqttAdapter"
  }
}
```

**IPC** - no `AdapterTypes`; the adapter runs as its own service:

```json
"ProtocolAdapters": {
  "MqttAdapter": {
    "AdapterType": "MQTT",
    "AdapterServer": "MqttServer"
  }
},
"AdapterServers": {
  "MqttServer": { "Address": "localhost", "Port": 50000 }
}
```

Start the service before SFC, on the port of its `AdapterServers` entry:

**Linux / macOS**

```shell
mqtt/bin/mqtt -port 50000
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\mqtt\lib\*" com.amazonaws.sfc.mqtt.MqttProtocolService -port 50000
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.mqtt.MqttProtocolService -port 50000` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.mqtt.MqttProtocolService -port 50000`).

**Examples:** uberjar: [greengrass-uberjar](../../examples/greengrass-uberjar/README.md) · in-process: [in-process-iot-core-opcua-write](../../examples/in-process-iot-core-opcua-write/README.md) · all: [examples catalog](../examples/README.md)

## Known limitations

- With `ReadMode` `KeepLast` (the default), the uberjar and in-process modes currently deliver an internal object (`_value`, `timestamp`, `valueCount`) instead of the value. Set `"ReadMode": "KeepAll"`.
- In the `Sources` of a schedule, list MQTT sources with `["*"]`. A schedule that names MQTT channels receives no values from them.
- Give each channel of a source its own topics. When two channels of a source subscribe to the same topic, only the last one receives messages.
- `ChangeFilter` and `ValueFilter` of MQTT channels are not applied.
- After a short broker disconnect the client reconnects without its subscriptions, and the source receives nothing until SFC is restarted.
- In the uberjar, one adapter instance serves all MQTT sources with the settings of the MQTT adapter it was first created for, so the `ReadMode`, `MaxRetainSize`, `MaxRetainPeriod` and `ReceivedDataChannel*` settings of other MQTT adapters are ignored.
- In IPC mode the channel `Name` is ignored; values are named after the topic.
- For `ssl://` endpoints the adapter trusts the certificate that the broker presents, so the broker is not authenticated.
- Payloads are decoded with the JVM's default character set. On Java 17 that is often not UTF-8 (on Windows, or on Linux with the C locale), so non-ASCII text arrives garbled; Java 18 and newer default to UTF-8.

**Configuration:**

- [MqttSourceConfiguration](#mqttsourceconfiguration)
- [MqttChannelConfiguration](#mqttchannelconfiguration)
- [MqttAdapterConfiguration](#mqttadapterconfiguration)
- [MqttBrokerConfiguration](#mqttbrokerconfiguration)
- [TopicNameMappingConfiguration](#topicnamemappingconfiguration-type)

---

## MqttSourceConfiguration

The MQTT source configuration specifies which MQTT channels to read and maps them to SFC channels for data collection. This configuration extends the base SourceConfiguration type and defines the relationship between the MQTT adapter (configured in the Broker class) and the specific channels to be monitored. It focuses on channel mapping and data collection settings rather than the broker connection details, which are handled separately in the Broker configuration.

The configuration allows you to define which MQTT topics to subscribe to and how to process their messages into SFC channels, while relying on the broker configuration for the actual MQTT connection and protocol-specific settings.

This type extends the [SourceConfiguration](../core/source-configuration.md) type. 

- [Schema](#mqttsourceconfiguration-schema)
- [Examples](#mqttsourceconfiguration-examples)

**Properties:**
- [AdapterBroker](#adapterbroker)
- [Channels](#channels)

---
### AdapterBroker
The broker identifier that specifies which MQTT server to read from. This identifier must match a broker configuration defined in the Brokers section of the MQTT adapter configuration referenced by the ProtocolAdapter attribute. This reference establishes the link between the source configuration and the actual broker connection details, allowing the adapter to use the correct broker settings for data collection.

**Type**: String

Must be an identifier of a broker in the Brokers section of the MQTT adapter used by the source.

---
### Channels
The channels configuration defines how to read values from MQTT topics on the source broker. It is structured as a map where each key is a channel identifier and the corresponding value contains the configuration for that specific channel. The channel identifier serves as a unique reference within the configuration.

To temporarily disable a channel without removing its configuration, you can prefix the channel identifier with a "#" character, effectively commenting it out. This provides a convenient way to maintain channel configurations while selectively enabling or disabling data collection from specific topics.

The element is a map indexed by the channel identifier, allowing for organized and easily maintainable configuration of multiple MQTT topic subscriptions

**Type**: Map[String,[MqttChannelConfiguration](#mqttchannelconfiguration)]

At least 1 channel must be configured.

[^top](#mqtt-protocol-configuration)

### MqttSourceConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "definitions": {
    "MqttSourceConfiguration": {
      "type": "object",
      "description": "Configuration for MQTT source adapter",
      "allOf": [
        {
          "$ref": "#/definitions/BaseSourceConfiguration"
        },
        {
          "type": "object",
          "properties": {
            "AdapterBroker": {
              "type": "string",
              "description": "Reference to the broker configuration to be used by this adapter"
            },
            "Channels": {
              "type": "object",
              "description": "Map of MQTT channel configurations",
              "additionalProperties": {
                "$ref": "#/definitions/MqttChannelConfiguration"
              },
              "minProperties": 1
            }
          },
          "required": [
            "AdapterBroker",
            "Channels"
          ]
        }
      ]
    }
  }
}

```

### MqttSourceConfiguration Examples

```json
{
  "Name": "MqttSource1",
  "ProtocolAdapter" : "mqtt-adapter",
  "AdapterBroker": "mqtt-broker-1",
  "Channels": {
    "temperature_sensor": {
      "Topics": ["sensors/temperature"]
    }
  }
}
```

## MqttChannelConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [Sources](../core/sfc-configuration.md#sources) > [Source](../core/source-configuration.md)  > [Channels](../core/source-configuration.md#channels) > [Channel](../core/channel-configuration.md)

The MQTT channel configuration defines how to read data from a specific MQTT topic and convert it into an SFC channel value. It specifies the topic to subscribe to, how to extract and interpret the message payload, and how to transform the data into the appropriate format for SFC processing. This configuration allows for flexible mapping between MQTT messages and SFC channel values, supporting different message formats and data types.

The configuration includes settings for topic subscription, message processing rules, and value extraction methods to ensure proper data collection from MQTT topics into the SFC system.

The MqttChannelConfiguration type extends the [ChannelConfiguration](../core/channel-configuration.md) class with channel properties for the MQTT protocol adapter.

**How values are named:** a value gets the channel's `Name` if it is set, otherwise the name made by its [TopicNameMappingConfiguration](#topicnamemappingconfiguration) (a topic that no mapping matches is dropped unless [IncludeUnmappedTopics](#includeunmappedtopics) is true), otherwise the topic it was received on (for example `sensors/temperature/room1`), not the channel identifier. Do not combine `Name` with `+` or `#` wildcards, because every matching topic would get the same name. In IPC mode the `Name` is currently ignored.

- [Schema](#mqttchannelconfiguration-schema)
- [Examples](#mqttchannelconfiguration-examples)

**Properties:**
- [Json](#json)
- [Selector](#selector)
- [TopicNameMappingConfiguration](#topicnamemappingconfiguration)
- [Topics](#topics)

---
### Json
Set to true if the messages received from MQTT topics contain data in JSON format. When enabled, this indicates that the incoming MQTT message payloads should be parsed as JSON data, allowing the adapter to properly extract and process structured JSON content from the messages. This setting helps the adapter determine the appropriate parsing method for the incoming messages.

**Type**: Boolean

Default is true

---
### Selector
Evaluate a JMESpath query against the value of a structured data type and returns the result. The selector can be used to restructure or select values from structured data types. This JMESpath expression allows you to extract specific fields or transform complex JSON data structures received in MQTT messages into the desired format. It provides a powerful way to navigate and filter JSON data, making it possible to precisely target the needed values within nested JSON structures

**Type**:  String

**Parameter**: JMESPath expression, see https://jmespath.org/

---
### TopicNameMappingConfiguration
Mapping from topic names to alternative names. As a channel can have multiple topics, that also can include wildcards, this mapping can be used to build consistent and expected value names. This configuration allows you to create a standardized naming scheme for values received from different MQTT topics, even when using wildcard subscriptions. 

**Type**: [TopicNameMappingConfiguration](#topicnamemappingconfiguration-type)

---
### Topics
A string array containing the topics to subscribe to. The topic names may contain single-level (+) and multi-level (#) wildcards. These wildcards enable flexible topic subscription patterns:

- The plus sign (+) is a single-level wildcard that matches exactly one level in the topic hierarchy. For example, "sensor/+/temperature" would match "sensor/room1/temperature" and "sensor/room2/temperature", but not "sensor/building1/room1/temperature".
- The hash symbol (#) is a multi-level wildcard that matches any number of levels in the topic hierarchy. It must be the last character in the topic filter. For example, "sensor/#" would match "sensor/temperature", "sensor/room1/temperature", and "sensor/building1/room1/temperature".

This wildcard functionality allows you to subscribe to multiple related topics with a single subscription pattern, making it easier to collect data from groups of similar topics or hierarchical topic structures.

**Type**: String[]

There must be at least one topic in the list of topics.

[^top](#mqtt-protocol-configuration)

### MqttChannelConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "description": "Configuration for MQTT channel",
  "allOf": [
    {
      "$ref": "#/definitions/ChannelConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "Json": {
          "type": "boolean",
          "description": "Indicates if the payload is in JSON format"
        },
        "Selector": {
          "type": "string",
          "description": "Selector for filtering messages"
        },
        "TopicNameMappingConfiguration": {
          "$ref": "#/definitions/TopicNameMappingConfiguration",
          "description": "Configuration for mapping topic names"
        },
        "Topics": {
          "type": "array",
          "description": "List of MQTT topics to subscribe to",
          "items": {
            "type": "string"
          },
          "minItems": 1
        }
      },
      "required": [
        "Topics"
      ]
    }
  ]
}
```

### MqttChannelConfiguration Examples

```json
{
  "Topics": [
    "sensors/temperature/room1"
  ]
}
```



```json
{
  "Topics": [
    "sensors/temperature/#"
  ],
  "TopicNameMappingConfiguration": {
    "Mappings": {
      "^sensors/temperature/(\\w+)$": "temperature-$1"
    }
  }
}
```



## TopicNameMappingConfiguration type

[MqttSource](#mqttsourceconfiguration) > [Channels](#channels) > [Channel](#mqttchannelconfiguration) > [TopicNameMappingConfiguration](#topicnamemappingconfiguration)



Mapping from topic names to alternative names. As a channel can have multiple topics, that also can include wildcards, this mapping can be used to build consistent and expected value names. This configuration enables you to transform potentially complex or varying MQTT topic names into standardized identifiers that are more suitable for processing .

For example, when using wildcard subscriptions that match multiple topics (like "sensor/+/temperature"), you can map the actual topic names to more consistent value names. This ensures that data from different topics follows a predictable naming pattern, making it easier to process and organize the collected data, regardless of the original topic structure. 

The mapping helps maintain consistency in data handling, especially when dealing with multiple data sources or dynamic topic patterns.

Example:

Channel subscription is:

```json
	"Topics" :[ "test/#"]
```



The mapping is:

```json
	"Mappings": {
		"test/(\\w+)": "test-$1"
	}
```

The mapping above matches updates for sub-levels of the test topic, it will use the name of the sub-level to create a name for the received data.

If an update is received for data in topic "test/a" then the name of the data value will be "test-a"

- [Schema](#topicnamemappingconfiguration-schema)
- [Examples](#topicnamemappingconfiguration-examples)

**Properties:**
- [IncludeUnmappedTopics](#includeunmappedtopics)
- [Mappings](#mappings)

  

  

---
### IncludeUnmappedTopics
If set to false, updates for values from topics that do not match any of the expressions in the mapping's element will be dropped. If set to true then the name of the value will be the name of the topic the update was received for. This setting controls how the system handles MQTT messages from topics that don't match any of the defined mapping patterns:

- When false: Messages from unmatched topics are ignored and not processed
- When true: Messages from unmatched topics are processed using the original topic name as the value name

This provides flexibility in handling unexpected or unmapped topics, allowing you to either filter out unwanted data or process all incoming messages regardless of whether they have a specific mapping defined

**Type**: Boolean

Default is false

---
### Mappings
Mapping table for mapping the topic names of received topic data updates to data value names. As a channel can subscribe to multiple topics, that can also include wildcards, updates from different topics can be received.

This element is a map that uses regular expression strings as indexes. The entries in the map are strings that will be used as replacement strings if the regular expression of the entry matches the name of the topic for an update.

The replacement string can include substitution parameters for capturing groups in the regular expression.

Only the part of the topic name that the expression matches is replaced, so anchor patterns with `^` and `$` to map the whole topic name.

For example, if you have a mapping:

```json
"Mappings": {
    "sensors/(\\w+)/(\\w+)": "device-$1-$2"
}
```

Then:

- A message from topic "sensors/room1/temperature" would be mapped to "device-room1-temperature"
- The (\w+) patterns capture the variable parts of the topic
- $1 and $2 in the replacement string refer to the captured groups in order

This allows for flexible and powerful topic name transformations, helping to standardize how data is identified within the system regardless of the original topic structure.

**Type**: Map[String,String]

At least one mapping must be configured.

[^top](#mqtt-protocol-configuration)


### TopicNameMappingConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "description": "Configuration for MQTT topic name mapping",
  "properties": {
    "IncludeUnmappedTopics": {
      "type": "boolean",
      "description": "Flag to include topics that don't match any mapping",
      "default": false
    },
    "Mappings": {
      "type": "object",
      "description": "Map of source topic patterns to target topic patterns",
      "additionalProperties": {
        "type": "string"
      },
      "minProperties": 1
    }
  },
  "required": [
    "Mappings"
  ]
}
```

### TopicNameMappingConfiguration Examples



Minimal configuration:

```json
{
  "Mappings": {
    "source/topic": "target/topic"
  }
}
```



Basic mapping with matching pattern for wildcards

```json
{
  "IncludeUnmappedTopics": false,
  "Mappings": {
    "^device/(\\w+)/temperature$": "sensors/temp/$1"
  }
}
```



Multiple mappings with unmapped topics included:

```json
{
  "IncludeUnmappedTopics": true,
  "Mappings": {
    "^device/(\\w+)/temperature$": "sensors/temp/$1",
    "^device/(\\w+)/humidity$": "sensors/humid/$1",
    "^factory/line-(\\w+)$": "production/line/$1"
  }
}
```



## MqttAdapterConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [ProtocolAdapters](../core/sfc-configuration.md#protocoladapters) > [Adapter](../core/protocol-adapter-configuration.md) 

The MqttAdapterConfiguration class defines the configuration settings for an MQTT adapter in the SFC system. It enables communication with MQTT brokers by specifying connection parameters, channel configurations, security settings, and message handling options. This configuration manages how the system interacts with MQTT brokers, including topic subscriptions and connection management

MqttAdapterConfiguration extends the [AdapterConfiguration](../core/protocol-adapter-configuration.md) with properties for the MQTT Protocol adapter.

- [Schema](#mqttadapterconfiguration-schema)
- [Examples](#mqttadapterconfiguration-examples)

**Properties:**
- [Brokers](#brokers)
- [MaxRetainPeriod](#maxretainperiod)
- [MaxRetainSize](#maxretainsize)
- [ReadMode](#readmode)
- [ReceivedDataChannelSize](#receiveddatachannelsize)
- [ReceivedDataChannelTimeout](#receiveddatachanneltimeout)

---
### Brokers
Brokers configured for this adapter. The mqtt source using the adapter must refer to one of these servers with the AdapterBroker attribute. This property defines a collection of MQTT broker configurations that can be used by the adapter.

Each broker configuration in this collection can be referenced by mqtt sources through the AdapterBroker attribute, allowing multiple sources to connect to different MQTT brokers through the same adapter. This provides flexibility in connecting to multiple MQTT endpoints while maintaining centralized configuration management.

For example, you might configure multiple brokers for different environments (development, production) or different purposes (data collection, monitoring) within the same adapter configuration.

**Type**: Map[String,[MqttBrokerConfiguration](#mqttbrokerconfiguration)]

---

### MaxRetainPeriod

When [ReadMode](#readmode) is `KeepAll`  this parameter can be used to restrict the period in milliseconds for which values are stored. This property helps manage memory usage by limiting how long retained MQTT messages are kept in the system.

For example:

- If MaxRetainPeriod is set to 3600000 (1 hour), any retained messages older than one hour will be discarded
- This prevents unbounded growth of stored messages while still maintaining a useful history
- The time period is measured in milliseconds from when the message was received

This setting is particularly useful when dealing with high-frequency MQTT messages or when system memory constraints need to be considered. The limit applies separately to each value name of each channel (see [How values are named](#mqttchannelconfiguration)).

**Type**: Integer

The default value is 3600000 (1 hour). If set to 0 there is no maximum period.

---

### MaxRetainSize

When [ReadMode](#readmode) is  `KeepAll` this parameter can be used to restrict the maximum number of stored values. This property helps control memory usage by limiting the total number of retained MQTT messages that can be stored at any given time.

For example:

- If MaxRetainSize is set to 1000, only the most recent 1000 messages will be kept
- When the limit is reached, the oldest messages are discarded to make room for new ones
- This creates a rolling buffer of the most recent messages

This setting is particularly useful for preventing memory issues in systems that handle high volumes of MQTT messages while still maintaining access to recent message history. The limit applies separately to each value name of each channel (see [How values are named](#mqttchannelconfiguration)).

**Type**: Integer

The default value is 10000.
If set to 0 there is no maximum number of values.

---

### ReadMode


- Read mode of the adapter. Set to KeepAll to collect all messages on subscribed topics during a read interval.
  Set to "KeepLast", which is the default, to keep only the last received message. 


**Type** : String


- KeepLast  to collect last values received in read interval each topic, discarding earlier messages (Default)

- KeepAll to collect values received in read interval up to the maximum specified by MaxRetainSize values or not older than specified by MaxRetainPeriod

In the uberjar and in-process modes `KeepLast` currently delivers an internal object instead of the value; use `KeepAll` (see [Known limitations](#known-limitations)).


---
### ReceivedDataChannelSize
The ReceivedDataChannelSize property defines the size of the channel buffer used for receiving MQTT messages. This setting determines how many messages can be queued in memory before processing.

Key points:

- Controls the buffer capacity for incoming MQTT messages
- Helps manage memory usage and message processing flow
- Larger values allow more messages to be queued but consume more memory

This setting is important for tuning the performance and reliability of the MQTT adapter based on your specific message volume and processing requirements

**Type**: Int

Default is 1000

---
### ReceivedDataChannelTimeout
Timeout in milliseconds to send data to internal buffer for received data for topic subscriptions. This property specifies how long the system will wait when attempting to add received MQTT messages to the internal processing buffer.

Key aspects:

- Defines the maximum time (in milliseconds) to wait when buffering received messages
- Helps prevent system blockage if the internal buffer becomes full
- If the timeout is reached, the system may drop messages to prevent blocking

This timeout setting is crucial for maintaining system responsiveness while handling high volumes of MQTT messages, preventing deadlocks that could occur if the buffer becomes full.

**Type**: Int

Default is 1000

[^top](#mqtt-protocol-configuration)

### MqttAdapterConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "description": "Configuration for MQTT adapter",
  "allOf": [
    {
      "$ref": "#/definitions/AdapterConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "Brokers": {
          "type": "object",
          "description": "Map of MQTT broker configurations",
          "additionalProperties": {
            "$ref": "#/definitions/MqttBrokerConfiguration"
          },
          "minProperties": 1
        },
        "MaxRetainPeriod" :{
          "type" : "integer",
          "description": "Max value retain period",
          "default" : 3600000
        },
        "MaxRetainSize" :{
          "type" : "integer",
          "description": "Max value retain size",
          "default" : 10000
        },
        "ReadMode": {
          "type": "string",
          "description": "Mode for reading MQTT messages",
          "enum": [
            "KeepLast",
            "KeepAll"
          ],
          "default": "KeepLast"
        },
        "ReceivedDataChannelSize": {
          "type": "integer",
          "description": "Size of the channel for received data",
          "default": 1000
        },
        "ReceivedDataChannelTimeout": {
          "type": "integer",
          "description": "Timeout for the received data channel in milliseconds",
          "default": 1000
        }
      },
      "required": [
        "Brokers"
      ]
    }
  ]
}
```

### MqttAdapterConfiguration Examples

Minimal configuration:

```json
{
  "AdapterType" : "MQTT",
  "Brokers": {
    "default-broker": {
      "EndPoint": "tcp://localhost:1883",
      "Port": 1883
    }
  }
}
```

Multiple brokers with KeepAll mode, keeping at most 100 values that are no older than 60 seconds:

```json
{
  "AdapterType" : "MQTT",
  "Brokers": {
    "primary-broker": {
      "EndPoint": "tcp://broker1.example.com:1883",
      "Port": 1883
    },
    "backup-broker": {
      "EndPoint": "tcp://broker2.example.com:1883",
      "Port": 1883
    }
  },
  "ReadMode": "KeepAll",
  "MaxRetainSize" : 100,
  "MaxRetainPeriod" : 60000,
  "ReceivedDataChannelSize": 5000,
  "ReceivedDataChannelTimeout": 10000
}
```





## MqttBrokerConfiguration

[MqttProtocolAdapter](#mqttadapterconfiguration) > [Brokers](#brokers) 

The MqttBrokerConfiguration class defines the connection and authentication settings for a specific MQTT broker. It contains the necessary parameters to establish and maintain a connection to an MQTT broker server. 

Key configuration elements include:

- Broker connection details (address, port)
- Authentication credentials
- Connection behavior settings
- Security configurations (TLS/SSL)
- Connection retry and timeout settings

This configuration allows you to specify all the necessary parameters for connecting to and communicating with a specific MQTT broker.

TLS is used when [EndPoint](#endpoint) starts with `ssl://`. For `ssl://` endpoints set [Certificate](#certificate), [PrivateKey](#privatekey) and [RootCA](#rootca). On Windows write these paths with forward slashes, for example `"C:/sfc/certs/client-cert.pem"`; a single backslash is a JSON escape.

- [Schema](#mqttbrokerconfiguration-schema)
- [Examples](#mqttbrokerconfiguration-examples)

**Properties:**
- [Certificate](#certificate)
- [ConnectTimeout](#connecttimeout)
- [EndPoint](#endpoint)
- [Password](#password)
- [Port](#port)
- [PrivateKey](#privatekey)
- [RootCA](#rootca)
- [SslServerCertificate](#sslservercertificate)
- [Username](#username)
- [VerifyHostname](#verifyhostname)
- [WaitAfterConnectError](#waitafterconnecterror)

---
### Certificate
Path to the client certificate file. This property specifies the file path to the client's X.509 certificate for SSL/TLS authentication with the MQTT broker.

Key aspects:

- Required for `ssl://` endpoints: the adapter loads the client certificate and private key for every TLS connection
- Should point to a valid X.509 certificate file in PEM format.
- Used in conjunction with the private key for client authentication

**Type**: String

---
### ConnectTimeout
Timeout for connecting to the broker in seconds.

**Type**: Int

Default is 10 seconds

Currently not applied: the adapter always uses 10 seconds.

---
### EndPoint
The URL of the MQTT broker:

- `tcp://host:port` for plain MQTT, for example `"tcp://127.0.0.1:1883"`. Without a port in the URL the client connects to port 1883.
- `ssl://host` for MQTT over TLS, for example `"ssl://mqtt.example.com"`. The client connects to port 8883; do not put a port in an `ssl://` URL.

Without a scheme, `tcp://` is added, or `ssl://` when [Certificate](#certificate), [PrivateKey](#privatekey) or [RootCA](#rootca) is set. A port in the URL also sets [Port](#port) when Port is not configured.

**Type** : String

---
### Password
password if broker is using username and password authentication

**Type** : String

**Username and password should not be included as clear text in the configuration.** It is strongly recommended to use placeholders and use the SFC integration with the AWS secrets manager.

Security considerations:

- Never store passwords in plain text

- Use [AWS Secrets Manager](../core/secrets-manager-configuration.md) to securely store credentials

- Use placeholders in configuration files



---
### Port
Port on MQTT broker

**Type** : Integer 

Required unless the [EndPoint](#endpoint) URL contains the port, which then sets it. The connection itself uses the port in the EndPoint URL, or 1883 (`tcp://`) / 8883 (`ssl://`) when the URL has none; for `ssl://` endpoints the adapter also reads the broker's certificate from this port.

Common port numbers are 1883 for plain MQTT and 8883 for MQTT over TLS, including AWS IoT Core endpoints.

---
### PrivateKey
Path to client private key file

**Type** : String

The private key works in conjunction with the client certificate to establish an authenticated TLS connection to the MQTT broker.

Key aspects of private key usage:

- Forms one half of the public/private key pair for client authentication
- Must correspond to the public key in the client certificate
- Used to prove the client's identity to the broker
- Required for `ssl://` endpoints
- Should be kept secure and protected from unauthorized access

---
### RootCA
Path to root certificate file. The CA certificates in this file are added to the certificates the adapter trusts for TLS connections with the broker.

**Type**: String

Set it for `ssl://` endpoints.

Usage scenarios:

1. Public CA certificates: When broker uses certificates from well-known authorities
2. Private CA certificates: When using self-signed or internal CA certificates
3. AWS IoT Core: When connecting to AWS IoT endpoints using their specific root CA

---
### SslServerCertificate
Path to a file with the broker's certificate.

**Type** : String

Currently not applied: the adapter reads the certificate from the broker instead and trusts it (see [Known limitations](#known-limitations)).

---
### Username
Username if broker is using username and password authentication

**Type** : String

Username and password should not be included as clear text in the configuration. It is strongly recommended to use placeholders and use the SFC integration with the AWS secrets manager.

---

### VerifyHostname

Flag to enable verification of hostname

**Type** : Boolean

The VerifyHostname setting controls whether the client should verify that the hostname in the broker's certificate matches the actual hostname being connected to.

Key aspects:

- Verifies the server's identity matches its certificate
- Applies to `ssl://` endpoints
- Should typically be enabled in production environments

Default is true

---
### WaitAfterConnectError
Period in seconds to wait before trying to connect after a connection failure

**Type** : Int

Default is 60 seconds

This setting controls the retry backoff period when connection attempts fail. It helps prevent excessive reconnection attempts that could overwhelm the broker or network resources.

[^top](#mqtt-protocol-configuration)

### MqttBrokerConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "description": "Configuration for MQTT broker connection",
  "properties": {
    "Certificate": {
      "type": "string",
      "description": "Client certificate file path"
    },
    "ConnectTimeout": {
      "type": "integer",
      "description": "Connection timeout in seconds",
      "default" : 10
    },
    "EndPoint": {
      "type": "string",
      "description": "MQTT broker endpoint address"
    },
    "Password": {
      "type": "string",
      "description": "Password for authentication"
    },
    "Port": {
      "type": "integer",
      "description": "MQTT broker port number"
    },
    "PrivateKey": {
      "type": "string",
      "description": "Client private key file path"
    },
    "RootCA": {
      "type": "string",
      "description": "Root CA certificate file path"
    },
    "SslServerCertificate": {
      "type": "string",
      "description": "SSL server certificate file path"
    },
    "Username": {
      "type": "string",
      "description": "Username for authentication"
    },
    "VerifyHostname":{
      "type" : "boolean",
      "default" : true
    },
    
    "WaitAfterConnectError": {
      "type": "integer",
      "description": "Wait time in seconds after connection error",
      "default": 60
    }
  },
  "required": [
    "EndPoint"
  ]
}
```

### MqttBrokerConfiguration Examples

Basic configuration with required fields only:

```json
{
  "EndPoint": "tcp://localhost:1883",
  "Port": 1883
}
```



SSL/TLS with certificate-based authentication:

```json
{
  "EndPoint": "ssl://mqtt.example.com",
  "Port": 8883,
  "Certificate": "/path/to/client-cert.pem",
  "PrivateKey": "/path/to/private-key.pem",
  "RootCA": "/path/to/root-ca.pem",
  "VerifyHostname": true
}
```



AWS IoT Core configuration:

```json
{
  "EndPoint": "ssl://xxxxxxxxxxxxxxx-ats.iot.region.amazonaws.com",
  "Port": 8883,
  "Certificate": "/certs/device-certificate.pem.crt",
  "PrivateKey": "/certs/private.pem.key",
  "RootCA": "/certs/AmazonRootCA1.pem",
  "ConnectTimeout": 15
}
```

**Runnable examples:** [in-process-iot-core-opcua-write](../../examples/in-process-iot-core-opcua-write/README.md) (TLS to AWS IoT Core) · [mqtt-config-provider](../../examples/mqtt-config-provider/README.md) (the same broker settings in a configuration provider)

