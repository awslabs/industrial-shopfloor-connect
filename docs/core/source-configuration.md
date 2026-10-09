## SourceConfiguration

[SFC Configuration](./sfc-configuration.md) > [Sources](./sfc-configuration.md#sources) 

Defines core configuration properties for [SFC source adapters](../adapters/README.md). Includes settings for channel management, data transformation (composition/decomposition), timestamps, filtering, and metadata. Source adapters extend this base configuration with protocol-specific properties. Essential for configuring how data is collected and processed from input sources.

See it running: [OPC UA to AWS IoT Core using filters](../../examples/opcua-to-iot-using-filters/README.md).

- [Schema](#schema)
- [Examples](#examples)

**Properties:**

- [ChangeFilter](#changefilter)
- [ChannelTimestampAdjustment](#channeltimestampadjustment)
- [Channels](#channels)
- [Compose](#compose)
- [Decompose](#decompose)
- [Description](#description)
- [Metadata](#metadata)
- [Name](#name)
- [ProtocolAdapter](#protocoladapter)
- [SourceTimestampAdjustment](#sourcetimestampadjustment)
- [Spread](#spread)

---
### ChangeFilter
The ChangeFilter property specifies a reference to a [change filter](./change-filter-configuration.md) that should be applied to all channel values of the source. The value should be a string that matches the ID of a filter defined in the ChangeFilters section of the top-level SFC configuration. This filter determines when values should be processed based on how they change over time. The property is optional - if not specified, no change filtering will be applied to the source's channel values  (unless a channel-level filter is active).

**Type**: String

---
### ChannelTimestampAdjustment
Specifies a time adjustment in milliseconds that will be applied to timestamps of all values from the source. Use positive numbers to move timestamps forward in time, or negative numbers to move them backward. This allows for systematic correction of timing offsets in the data collection process.

**Type**: Long

To set the timestamp to a later value use a positive value, for an earlier value use a negative value.

> Not applied when the adapter runs as an IPC service; channel values then carry the source timestamp.

---

### Channels
Defines a mapping of channel identifiers to their configurations, representing the values read from a source. While each protocol implementation defines its specific channel attributes, the SFC core uses a common set of generic attributes for processing. The protocol implementation handles the specific details of reading and interpreting data from the source according to its configuration

Channel IDs cannot contain "/". A channel ID starting with # is ignored. Channel Names (or IDs where no Name is set) must be unique within a source.

**Type**: Map[String,[ChannelConfiguration](./channel-configuration.md)]

---
### Compose
Defines a mapping that combines multiple channel values into structured data. Each map entry specifies a structure name and a list of channel IDs to be merged. The resulting structure uses channel IDs (or their configured names) as field names, with the source timestamp. Original channel values are removed after composition. For example, combining "Input0" and "Output0" channels under an "IO" structure transforms individual boolean values into a single structured object with both values as fields. Compose only groups values into a structure; it does not calculate anything. To calculate values such as averages over time, use [Aggregation](./aggregation-configuration.md).

**Type**: Map[String, List[String]]

Examples: 

```json

   "Compose" : {
        "IO" : ["Input0", "Output0"]
  }
```

This will result in the Input0 and Output0 channel values being replaced by a new value named "IO" with both of these fields as fields of that structure.
```json
{
   "Input0" : true,
   "Output0" : false
}

```


```json
{
   "IO" : {
      "Input0" : true,
       "Output0" : false
   }
}
```




---
### Decompose
The Decompose property controls whether structured values from the channels in the source should be broken down into individual elements. When set to true:

- A structured value will be split into separate values for each sub-element
- Each decomposed value is named `<channel ID>.<field>` (the channel's Name is not used)
- The original structured value is removed after decomposition
- For lists of structures (when Spread is true), each structure is decomposed with names following the pattern `<channel ID>.<index>.<field>`

This property can be set at both [channel](./channel-configuration.md#decompose) and source level, with the channel-level setting taking precedence over the source-level setting. The default value is false.

This feature is particularly useful when working with complex data structures that need to be broken down into simpler individual values for processing or analysis

If the value is a list of structures and the value of the [Spread](#spread) setting is true then each structure in the list is decomposed. 

**Type**: Boolean

Default is false

---
### Description
Provides a free-form text field where users can add descriptive information about the source to document its purpose or characteristics.

**Type**: String

---
### Metadata

The optional [Metadata](../README.md#metadata) element can be used to add additional data to the output at the source level. If metadata is specified, which is a map of string indexed values, it is added under the metadata node of the source in the output. The name of that node can be configured through the "Metadata" entry of the [ElementNames](./sfc-configuration.md#elementnames) configuration element.

**Type**: Map[String, String]

---
### Name
Name of the source in the output data, used as the key in output value maps. Set it to the source key if you don't need a different name. This allows meaningful naming of data sources (like "AC-Unit-1" or "Plant-1/Cooling-Pump") to improve readability and identification in the output data.

**Type**: String

Required

---
### ProtocolAdapter
Specifies which protocol adapter should be used for this source by referencing its identifier. The referenced protocol adapter must be defined in the [ProtocolAdapters](./sfc-configuration.md#protocoladapters)  section of the configuration. This setting establishes the connection between the source and the specific protocol implementation used to communicate with the data source.

**Type**: String

Required

---
### SourceTimestampAdjustment
Time in ms to adjust the value of the source timestamp value.

**Type**: Long

To set the timestamp to a later value use a positive value, for an earlier value use a negative value.

---
### Spread
If true, list values of all channels of this source are spread into individual values. A channel's own [Spread](./channel-configuration.md#spread) setting overrides this.

**Type**: Boolean

Default is false

Each structure in the list becomes a value named `<channel ID>.<index>`. After splitting the list value into individual values, it is removed from the dataset.

> Currently only lists of structures are spread. A list of primitive values (numbers, strings) is dropped from the output, so do not spread such channels; set their own Spread to false when the source sets it.



[^top](#sourceconfiguration)



## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "ChangeFilter": {
      "type": "string",
      "description": "Reference to a changefilter defined in ChangeFilters section at top level config"
    },
    "ChannelTimestampAdjustment": {
      "type": "integer",
      "description": "Adjustment value for timestamps in milliseconds"
    },
    "Channels": {
      "type": "object",
      "additionalProperties": {
        "$ref": "#/definitions/ChannelConfiguration"
      },
      "minProperties": 1,
      "description": "Map of channel configurations, keyed by channel ID"
    },
    "Compose": {
      "type": "object",
      "patternProperties": {
        "^.*$": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "minItems": 1
        }
      },
      "description": "Map of composed values"
    },
    "Decompose": {
      "type": "boolean",
      "default": false,
      "description": "Enable/disable data decomposition"
    },
    "Description": {
      "type": "string",
      "description": "Description of the source"
    },
    "Metadata": {
      "type": "object",
      "additionalProperties": {
        "type": "string"
      },
      "description": "Key-value pairs of metadata"
    },
    "Name": {
      "type": "string",
      "minLength": 1,
      "description": "Name of the source in the output"
    },
    "ProtocolAdapter": {
      "type": "string",
      "description": "ID of an entry in ProtocolAdapters"
    },
    "SourceTimestampAdjustment": {
      "type": "integer",
      "description": "Adjustment value for source timestamps in milliseconds"
    },
    "Spread": {
      "type": "boolean",
      "default": false,
      "description": "Enable/disable spreading of list values into individual values"
    }
  },
  "required": ["Name", "ProtocolAdapter", "Channels"]
}

```



## Examples

**<u>Note: In an SFC configuration sources will also be for a source type which extends the SourceConfiguration with their specific properties.</u>** The channels below are shown without these protocol-specific properties (for example `NodeId` for OPC UA); see the [adapter](../adapters/README.md) pages. `ProtocolAdapter` is the ID of an entry in the [ProtocolAdapters](./sfc-configuration.md#protocoladapters) section.



Minimal configuration:

```json
{
  "Name": "Boiler3",
  "ProtocolAdapter": "PlcAdapter",
  "Channels": {
    "Temperature": {},
    "Pressure": {}
  }
}
```



Basic configuration with metadata:

```json
{
  "Name": "Boiler3",
  "ProtocolAdapter": "PlcAdapter",
  "Channels": {
    "Temperature": {},
    "Pressure": {}
  },
  "Metadata": {
    "location": "Building1",
    "equipment": "Boiler3"
  }
}
```



Configuration with composition:

```json
{
  "Channels": {
    "Flow1": {},
    "Flow2": {}
  },
  "Compose": {
    "Flows": ["Flow1", "Flow2"],
    "ProcessMetrics": ["Flow1", "Flow2"]
  },
  "Name": "FlowMeter",
  "ProtocolAdapter": "PlcAdapter",
  "Description": "Flow measurement station"
}
```



Configuration with timestamp adjustment of -200 milliseconds

```json
{
  "Name": "LevelSensor",
  "ProtocolAdapter": "PlcAdapter",
  "Channels": {
    "Level": {}
  },
  "ChannelTimestampAdjustment": -200,
  "SourceTimestampAdjustment": 1000,
  "Spread": true
}
```



1. Full configuration:

```json
{
  "Name": "ProcessUnit1",
  "Description": "Main process unit monitoring",
  "ProtocolAdapter": "PlcAdapter",
  "Channels": {
    "Temperature1": {},
    "Temperature2": {},
    "Pressure": {}
  },
  "Compose": {
    "Temperatures": ["Temperature1", "Temperature2"],
    "ProcessConditions": ["Temperature1", "Temperature2", "Pressure"]
  },
  "ChangeFilter": "DeadbandFilter",
  "ChannelTimestampAdjustment": -100,
  "SourceTimestampAdjustment": 500,
  "Spread": true,
  "Decompose": false,
  "Metadata": {
    "area": "ProcessArea1",
    "criticality": "high",
    "maintainer": "Team1"
  }
}
```



Configuration with decomposition for all channels:

```json
{
  "Name": "BatchProcess",
  "ProtocolAdapter": "PlcAdapter",
  "Channels": {
    "BatchData": {}
  },
  "Decompose": true,
  "ChangeFilter": "JsonFilter",
  "Description": "Batch process data collection"
}
```

