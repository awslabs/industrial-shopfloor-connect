# BaseSourceConfiguration

[SFC Configuration](./sfc-configuration.md) > [Sources](./sfc-configuration.md#sources)

The BaseSourceConfiguration serves as a foundation that defines common properties used by protocol adapter sources in the SFC  framework. It provides essential attributes like name, description, and protocol adapter identification that all source configurations share. Protocol-specific adapters inherit from this class and extend it with their own specialized configuration properties to support their unique protocol requirements

All source properties, including these three, are documented on [SourceConfiguration](./source-configuration.md).

- [Schema](#schema)
- [Example](#example)

**Properties:**

- [Description](#description)
- [Name](#name)
- [ProtocolAdapter](#protocoladapter)

---

### Description

The Description property provides a human-readable text description of the source. It allows users to document the purpose, functionality, or any relevant details about the configured source.

Type: String

---

### Name

The Name property defines the identifier for the source in the output data. It is required; set it to the key used in the SFC top-level configuration's [Sources](./sfc-configuration.md#sources) property if you don't need a different name in the output.

Type: String

---

### ProtocolAdapter

The ProtocolAdapter property specifies a reference to the protocol adapter that will be used for this source. This reference corresponds to an adapter defined in the SFC top-level configuration's [ProtocolAdapters](./sfc-configuration.md#protocoladapters)  property. It establishes the connection between the source and the specific protocol adapter that will handle the communication. It is required.

Type: String

---

[^top](#basesourceconfiguration)

## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "BaseSourceConfiguration",
  "type": "object",
  "properties": {
    "Description": {
      "type": "string",
      "description": "Description of the source"
    },
    "Name": {
      "type": "string",
      "minLength": 1,
      "description": "Name of the source"
    },
    "ProtocolAdapter": {
      "type": "string",
      "description": "Protocol adapter identifier for the source"
    }
  },
  "required": ["Name", "ProtocolAdapter"]
}
```



## Example

```json
{
  "Description": "Production line sensor data source",
  "Name": "ProductionLineSensor1",
  "ProtocolAdapter": "OPCUA-SENSOR-ADAPTER"
}
```



[^top](#basesourceconfiguration)
