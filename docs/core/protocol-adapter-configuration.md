## ProtocolAdapterConfiguration

[SFC Configuration](./sfc-configuration.md) > [ProtocolAdapters](./sfc-configuration.md#protocoladapters) 

Defines the base configuration structure for protocol adapters in SFC, specifying how adapters operate either in-process or as separate services. Includes essential settings for adapter type, server configuration, metrics collection, and custom descriptions. Serves as the foundation for protocol-specific adapter implementations: each adapter type extends it with its own properties (for example `OpcuaServers` for OPCUA), see [Protocol adapters](../adapters/README.md).

How an adapter is configured in the uberjar, in-process and IPC modes: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode).

- [Schema](#schema)
- [Examples](#examples)

**Properties:**

- [AdapterServer](#adapterserver)
- [AdapterType](#adaptertype)
- [Description](#description)
- [Metrics](#metrics)

---
### AdapterServer
Specifies the server reference for running the protocol adapter as a separate service. When set, it must match an entry in the [AdapterServers](./sfc-configuration.md#adapterservers)  section, enabling IPC-based communication between the SFC core and the adapter service; no [AdapterTypes](./sfc-configuration.md#adaptertypes) entry is needed then. If not set, the adapter runs within the SFC core process (uberjar or in-process mode). [AdapterType](#adaptertype) is required in both cases.

**Type**: String

---
### AdapterType
Defines the protocol adapter type. The value must be the type code of the adapter; the adapters in this repository use ADS, J1939, MODBUS-TCP, MQTT, NATS, OPCUA, PCCC, REST, S7, SIMULATOR, SLMP, SNMP and SQL. An adapter only serves the adapter entries that carry its own type code. This property is required in every deployment mode. When the adapter runs within the SFC core process (uberjar or in-process), the key of its entry in the [AdapterTypes](./sfc-configuration.md#adaptertypes) section is the same value; when [AdapterServer](#adapterserver) is set (IPC), no AdapterTypes entry is needed. All types and classes: [Protocol adapter types and classes](../sfc-running-adapters.md#protocol-adapter-types-and-classes).

**Type**: String

---

### Description

An optional free-form text field that allows users to provide a human-readable description of the protocol adapter, helping to document its purpose or specific configuration details.

**Type**: String

---

### Metrics

Defines the metrics collection configuration for the protocol adapter, specifying how performance and operational metrics should be gathered and processed from this adapter source.

Type: [MetricsSourceConfiguration](./metrics-source-configuration.md)

[^top](#protocoladapterconfiguration)



## Schema



```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "title": "Protocol Adapter Configuration Schema",
  "properties": {
    "AdapterServer": {
      "type": "string",
      "description": "Reference to an adapter server defined in the AdapterServers Section in SFC top level config, runs the adapter as an IPC service"
    },
    "AdapterType": {
      "type": "string",
      "description": "Type code of the adapter (e.g. OPCUA, MODBUS-TCP), in uberjar and in-process mode also the key of the AdapterTypes entry in SFC top level config"
    },
    "Description": {
      "type": "string",
      "description": "Description of the protocol adapter configuration"
    },
    "Metrics": {
      "$ref": "#/definitions/MetricsSourceConfiguration",
      "description": "Configuration for metrics collection"
    }
  },
  "required": ["AdapterType"]
}
```



## Examples



Example with AdapterType, adapter running in the SFC core process (uberjar or in-process):

```json
{
  "AdapterType": "MODBUS-TCP",
  "Description": "Modbus connection to PLC using in-process adapter"
}
```



Example with AdapterServer, adapter running as an IPC service (AdapterType is still required):

```json
{
  "AdapterType": "S7",
  "AdapterServer": "S7AdapterServer"
}
```



Example with AdapterType and Metrics:

```json
{
  "AdapterType": "OPCUA",
  "Description": "Building automation controller",
  "Metrics": {
    "CommonDimensions": {
      "Environment": "Production",
      "Location": "Building2",
      "Device" : "Conveyor1"
    }
  }
}
```

[^top](#protocoladapterconfiguration)
