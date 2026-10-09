# Modbus TCP Protocol Configuration

The Modbus TCP protocol adapter enables communication with devices supporting the Modbus TCP protocol over TCP/IP networks. It reads coils, discrete inputs, holding registers and input registers (function codes 1-4). Configure device connections using IP address and port, specify unit IDs, and define register addresses and data types for your channels. The adapter handles all protocol-specific details, making it easy to integrate Modbus device data into your SFC infrastructure.

## Deploy this adapter

`AdapterType` is `MODBUS-TCP` in every deployment mode. In the uberjar and in-process modes the `AdapterTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode). All types and classes: [Protocol adapter types and classes](../sfc-running-adapters.md#protocol-adapter-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"AdapterTypes": {
  "MODBUS-TCP": { "FactoryClassName": "com.amazonaws.sfc.modbus.tcp.ModbusTcpAdapter" }
}
```

**In-process** - module bundle `modbus-tcp` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"AdapterTypes": {
  "MODBUS-TCP": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/modbus-tcp/lib"],
    "FactoryClassName": "com.amazonaws.sfc.modbus.tcp.ModbusTcpAdapter"
  }
}
```

**IPC** - no `AdapterTypes`; the adapter runs as its own service:

```json
"ProtocolAdapters": {
  "ModbusAdapter": {
    "AdapterType": "MODBUS-TCP",
    "AdapterServer": "ModbusServer"
  }
},
"AdapterServers": {
  "ModbusServer": { "Address": "localhost", "Port": 50000 }
}
```

Start the service before SFC, on the port of its `AdapterServers` entry:

**Linux / macOS**

```shell
modbus-tcp/bin/modbus-tcp -port 50000
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\modbus-tcp\lib\*" com.amazonaws.sfc.modbus.tcp.ModbusTcpProtocolService -port 50000
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.modbus.tcp.ModbusTcpProtocolService -port 50000` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.modbus.tcp.ModbusTcpProtocolService -port 50000`).

**Examples:** uberjar: [uberjar-modbus-file](../../examples/uberjar-modbus-file/README.md) · all: [examples catalog](../examples/README.md)



**Configuration**:

- [ModbusSourceConfiguration](#modbussourceconfiguration)
- [ModbusOptimization](#modbusoptimization)
- [ModbusChannelConfiguration](#modbuschannelconfiguration)
- [ModbusTcpAdapterConfiguration](#modbustcpadapterconfiguration)
- [ModbusTcpDeviceConfiguration](#modbustcpdeviceconfiguration)

## ModbusSourceConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [Sources](../core/sfc-configuration.md#sources) >  [Source](../core/source-configuration.md) 

Source configuration for the Modbus TCP protocol adapter. This type extends the [SourceConfiguration](../core/source-configuration.md) type with the device to read from, the channels to read and the read settings. The connection details of the device are in the [Devices](#devices) of the adapter.

- [Schema](#modbussourceconfiguration-schema)
- [Example](#modbussourceconfiguration-example)

**Properties:**
- [AdapterDevice](#adapterdevice)
- [Channels](#channels)
- [Optimization](#optimization)
- [ReadTimeout](#readtimeout)

---

### AdapterDevice
The identifier that references a specific Modbus TCP device defined in the Devices section of the adapter configuration. It must match a key of the [Devices](#devices) map of the adapter named in ProtocolAdapter (for example "plc1"). This is not the [DeviceId](#deviceid) (the Modbus unit ID).

**When multiple sources read from the same device, by using the same IP address, then a device for each source must be configured for each source to use.**

**Type**: String

---
### Channels
A collection of channel configurations that define what data to read from the Modbus TCP device. Each channel is identified by a unique key in the map and contains the configuration for reading specific registers or coils. Channels can be temporarily disabled by prefixing the channel identifier with '#'. The channel identifier serves as both the map key and the name used to reference the data point in the SFC system.

**Type**: Map[String,[ModbusChannelConfiguration](#modbuschannelconfiguration)]

At least 1 channel must be configured.

---
### Optimization
Settings that control how the adapter optimizes read operations by combining multiple register or coil reads into single Modbus requests. When enabled, the adapter will analyze channel configurations to group adjacent or nearby addresses into consolidated read operations, reducing network traffic and improving performance.

**Type**: [ModbusOptimization](#modbusoptimization)

Default optimization is enabled with a [RegisterMaxGapSize](#registermaxgapsize) of 8 and a [CoilMaxGapSize](#coilmaxgapsize) of 16.

---
### ReadTimeout
The maximum time, in milliseconds, to wait for a response from the Modbus device when executing a read request. If the device does not respond within this time period, the read operation will be considered failed and an error will be raised. This setting helps prevent the adapter from hanging when communication issues occur.

**Type**: Integer

Default is 10000.

[^top](#modbus-tcp-protocol-configuration)\

### ModbusSourceConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ModbusSourceConfiguration",
  "type": "object",
  "allOf": [
    {
      "$ref": "external-schema.json#/definitions/SourceConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "AdapterDevice": {
          "type": "string",
          "description": "Identifier of the Modbus adapter device"
        },
        "Channels": {
          "type": "object",
          "description": "Map of Modbus channel configurations indexed by string",
          "patternProperties": {
            "^.*$": {
              "$ref": "external-schema.json#/definitions/ModbusChannelConfiguration"
            }
          },
          "minProperties": 1
        },
        "Optimization": {
          "$ref": "external-schema.json#/definitions/ModbusOptimization",
          "description": "Read optimization settings"
        },
        "ReadTimeout": {
          "type": "integer",
          "description": "Timeout for read operations in milliseconds",
          "minimum": 1
        }
      },
      "required": [
        "AdapterDevice",
        "Channels"
      ],
      "additionalProperties": false
    }
  ]
}

```



### ModbusSourceConfiguration Example

Every source needs a `Name`, and its `ProtocolAdapter` must name an adapter with `"AdapterType": "MODBUS-TCP"`; the adapter ignores sources of other adapters.

Minimal configuration:

```json
{
  "Name": "ModbusSource1",
  "ProtocolAdapter": "ModbusAdapter",
  "AdapterDevice": "plc1",
  "Channels": {
    "temperature": {
      "Address": 1,
      "Type": "HoldingRegister"
    }
  }
}
```



Full configuration:

```json
{
  "Name": "ModbusSource1",
  "Description": "Production line Modbus source",
  "ProtocolAdapter": "ModbusAdapter",
  "AdapterDevice": "plc1",
  "Channels": {
    "temp1": {
      "Name": "Temperature1",
      "Address": 1,
      "Type": "HoldingRegister"
    },
    "pressure1": {
      "Name": "Pressure1",
      "Address": 2,
      "Type": "HoldingRegister"
    },
    "status": {
      "Name": "Status",
      "Address": 1,
      "Type": "DiscreteInput"
    }
  },
  "Optimization": {
    "Enabled": true,
    "RegisterMaxGapSize": 8,
    "CoilMaxGapSize": 16
  },
  "ReadTimeout": 5000
}
```





## ModbusOptimization

[ModbusSource](#modbussourceconfiguration) > [Optimization](#modbusoptimization)

Configuration settings that control how the Modbus TCP adapter optimizes read operations by combining multiple register or coil reads into single requests. This optimization reduces network traffic and improves overall performance by minimizing the number of individual Modbus transactions required to collect data from adjacent or nearby addresses.

- [Schema](#modbusoptimization-schema)
- [Example](#modbusoptimization-example)

**Properties:**

- [Enabled](#enabled)
- [RegisterMaxGapSize](#registermaxgapsize)
- [CoilMaxGapSize](#coilmaxgapsize)

---
### Enabled
Controls whether the Modbus read optimization feature is enabled or disabled. When enabled, the adapter will attempt to combine multiple register or coil reads into single requests based on the configured gap settings. When disabled, each channel will generate its own individual read request.

**Type**: Boolean

Default is true

---
### RegisterMaxGapSize
The maximum number of registers that can be skipped between two read operations while still combining them into a single Modbus request. For example, if set to 10, two register reads separated by up to 10 addresses will be combined into one request. This helps optimize network traffic while balancing memory usage and response time.

**Type**: Integer

Default is 8

---
### CoilMaxGapSize
The maximum number of coils or discrete inputs that can be skipped between two read operations while still combining them into a single Modbus request. For example, if set to 10, two coil reads separated by up to 10 addresses will be combined into one request. This helps optimize network traffic while balancing memory usage and response time.

**Type**: Integer

Default is 16

[^top](#modbus-tcp-protocol-configuration)



### ModbusOptimization Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ModbusOptimization",
  "type": "object",
  "properties": {
    "Enabled": {
      "type": "boolean",
      "description": "Enable/disable Modbus optimization",
      "default" : true
    },
    "RegisterMaxGapSize": {
      "type": "integer",
      "description": "Maximum gap size between registers for optimization",
      "default": 8
    },
    "CoilMaxGapSize": {
      "type": "integer",
      "description": "Maximum gap size between coils for optimization",
      "default": 16
    }
  }
}

```



### ModbusOptimization Example

```json
{
  "Enabled": true,
  "RegisterMaxGapSize": 8,
  "CoilMaxGapSize": 16
}
```



## ModbusChannelConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [Sources](../core/sfc-configuration.md#sources) > [Source](../core/source-configuration.md)  > [Channels](../core/source-configuration.md#channels) > [Channel](../core/channel-configuration.md)

A configuration class that defines how to read a specific data point from a Modbus device. It specifies the register type (coil, discrete input, input register, or holding register), address location, data format, and optional scaling parameters. Each channel configuration maps to a single data point that will be collected from the Modbus device and made available through the SFC system.

The ModbusChannelConfiguration type extends the [ChannelConfiguration](../core/channel-configuration.md) class with channel properties for the Modbus TCP  protocol adapter.

- [Schema](#modbuschannelconfiguration-schema)
- [Examples](#modbuschannelconfiguration-examples)


**Properties:**
- [Address](#address)
- [Size](#size)
- [Type](#type)

---
### Address
The Modbus address location from which to read the data value. This address specifies the exact register or coil location in the Modbus device's memory map. Address is the 1-based number within the table selected by [Type](#type) (Address 1 = protocol address 0, range 1-32767). Do not use 0x/1x/3x/4x prefixes: holding register 40001 is `"Type": "HoldingRegister", "Address": 1`.

**Type**: Integer

---
### Size
The number of consecutive registers or coils to read starting from the specified address. This is particularly useful when reading multi-register values like floating point numbers, strings, or arrays of values. 

**Type**: Integer

Default is 1.
The maximum for reading coils and discrete inputs is 2000.
The maximum for reading registers is 125.

---
### Type
Specifies which type of Modbus data object to read from the device. Each type serves a different purpose in Modbus communications:

- Coil: Single-bit read/write values typically used for digital outputs or control flags
- DiscreteInput: Single-bit read-only values usually representing digital inputs or status flags
- HoldingRegister: 16-bit read/write registers used for configuration values or analog outputs
- InputRegister: 16-bit read-only registers commonly used for measured values or analog inputs

The selection determines how the adapter interprets the address and interacts with the device.

**Type**: String, any of 

- "Coil"
- "DiscreteInput"
- "HoldingRegister"
- "InputRegister"

**Values**: a Coil or DiscreteInput channel returns a boolean, a HoldingRegister or InputRegister channel an unsigned 16-bit number; with a [Size](#size) above 1 the value is a list. Targets write register values to JSON as strings, for example `"165"`, or `["17984", "58880"]` for a Size of 2, unless the target sets [UnquoteNumericJsonValues](../core/target-configuration.md#unquotenumericjsonvalues); over IPC a single register value (Size 1) is written as a number. For a 32-bit float or integer held in two registers, set Size to 2 and apply a transformation such as [NumbersToFloatBE](../core/transformation-operator-configuration.md#numberstofloatbe) or [Int16sToInt32](../core/transformation-operator-configuration.md#int16stoint32) (see the last example below).

[^top](#modbus-tcp-protocol-configuration)



### ModbusChannelConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "allOf": [
    {
      "$ref": "external-schema.json#/definitions/ChannelConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "Address": {
          "type": "integer",
          "description": "Modbus address for the channel",
          "minimum": 1,
          "maximum": 32767
        },
        "Size": {
          "type": "integer",
          "description": "Size of the channel in registers/coils",
          "default": 1
        },
        "Type": {
          "type": "string",
          "description": "Type of Modbus data point",
          "enum": [
            "Coil",
            "DiscreteInput",
            "HoldingRegister",
            "InputRegister"
          ]
        }
      },
      "required": [
        "Address",
        "Type"
      ]
    }
  ]
}

```



### ModbusChannelConfiguration Examples

```json
{    
   "Address": 1,
   "Type": "DiscreteInput"
}
```



```json
{
    "Name": "Speed",
    "Address": 1,
    "Size": 2,
    "Type": "HoldingRegister"
  }
```



```json
{
    "Name": "Pump",
    "Address": 1,
    "Type": "Coil"
  }
```



A 32-bit float in holding registers 23 and 24 (big-endian), decoded by a transformation:

```json
{
    "Name": "Temperature",
    "Address": 23,
    "Size": 2,
    "Type": "HoldingRegister",
    "Transformation": "F32BE"
  }
```

with this entry in the [Transformations](../core/sfc-configuration.md#transformations) section of the configuration:

```json
"Transformations": {
  "F32BE": [{ "Operator": "NumbersToFloatBE" }]
}
```



## ModbusTcpAdapterConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [ProtocolAdapters](../core/sfc-configuration.md#protocoladapters) > [Adapter](../core/protocol-adapter-configuration.md) 

A configuration class that defines the connection and behavior settings for communicating with Modbus TCP devices.

ModbusTcpAdapterConfiguration extends the [AdapterConfiguration](../core/protocol-adapter-configuration.md) with properties for the Modbus TCP Protocol adapter.

- [Schema](#modbustcpadapterconfiguration-schema)
- [Example](#modbustcpadapterconfiguration-example)

**Properties:**

- [Devices](#devices)

---
### Devices
A collection of Modbus TCP device configurations that defines all the available Modbus servers this adapter can communicate with. Each device configuration specifies connection details like IP address and port number. When setting up a Modbus TCP source in the SFC system, the AdapterDevice property must reference one of these configured devices by name to establish which specific Modbus server to connect to for data collection.

NOTE: When multiple sources read from the same device by using the same IP address, then for each source, a device must be configured in the adapter.

**Type**: Map[String,[ModbusTcpDeviceConfiguration](#modbustcpdeviceconfiguration)]



### ModbusTcpAdapterConfiguration schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "allOf": [
    {
      "$ref": "external-schema.json#/definitions/AdapterConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "Devices": {
          "type": "object",
          "description": "Map of Modbus TCP device configurations indexed by string",
          "patternProperties": {
            "^.*$": {
              "$ref": "external-schema.json#/definitions/ModbusTcpDeviceConfiguration"
            }
          },
          "minProperties": 1
        }
      },
      "required": ["Devices"]
    }
  ]
}

```

### ModbusTcpAdapterConfiguration Example

```json
{
  "AdapterType" : "MODBUS-TCP",
  "Devices": {
    "plc1": {
      "Address": "192.168.1.100",
      "Port": 502,
      "ConnectTimeout": 5000,
      "WaitAfterConnectError": 5000,
      "WaitAfterWriteError": 1000,
      "WaitAfterReadError": 1000
    }
  }
}

```



[^top](#modbus-tcp-protocol-configuration)



## ModbusTcpDeviceConfiguration

[ModbusTcpAdapter](#modbustcpadapterconfiguration) > [Devices](#devices)

A configuration class that defines the connection parameters for a specific Modbus TCP server device. It contains the network addressing information and device-specific settings needed to establish communication with a Modbus TCP device. This configuration is referenced by Modbus TCP sources to identify which device to connect to and how to communicate with it, ensuring proper routing of Modbus requests to the correct network endpoint

- [Schema](#modbustcpdeviceconfiguration-schema)
- [Example](#modbustcpdeviceconfiguration-example)

**Properties:**

- [Address](#address-1)
- [ConnectTimeout](#connecttimeout)
- [DeviceId](#deviceid)
- [Port](#port)
- [RequestDepth](#requestdepth)
- [WaitAfterConnectError](#waitafterconnecterror)
- [WaitAfterReadError](#waitafterreaderror)
- [WaitAfterWriteError](#waitafterwriteerror)

---
### Address
The IP address or hostname of the Modbus TCP server device. This address specifies the network location where the device can be reached for Modbus communications. For example, "192.168.1.100" or "plc.local".

**Type**: String

---
### ConnectTimeout
The maximum time in milliseconds that the adapter will wait when attempting to establish a TCP connection with the Modbus device. If a connection cannot be established within this time period, the connection attempt will be aborted and considered failed. This setting helps prevent the system from hanging when network issues or device unavailability occur.

**Type**: Integer

Default is 10000, the minimum value is 1000

---
### DeviceId
The Modbus unit ID used to communicate with this specific device. In Modbus TCP networks, this ID helps identify the target device when multiple Modbus devices are connected through the same TCP/IP connection, such as when communicating through a gateway or when a single TCP/IP endpoint serves multiple logical Modbus devices. Each device behind such an endpoint has its own unit ID, so that requests and responses are routed to the right device.

**Type**: Integer

Default is 1

---
### Port
The TCP port number that the Modbus TCP server is listening on. The default Modbus TCP port is 502, but some devices or configurations may use different port numbers. This port must match the listening port configured on the target Modbus device for successful communication.

**Type**: Integer

Default is 502

---
### RequestDepth
The maximum number of requests the adapter sends to the device before it has received a response.

**Type**: Integer

Default is 1, the minimum value is 1

---
### WaitAfterConnectError
The time in milliseconds to wait before attempting to reconnect after a connection error occurs. This delay helps prevent excessive reconnection attempts when a device is unavailable, reducing network traffic and system resource usage. The waiting period provides time for potential temporary network issues to resolve or for the target device to recover before initiating a new connection attempt

**Type**: Integer

Default is 10000, the minimum value is 1000

---
### WaitAfterReadError
The time in milliseconds to wait before retrying a read operation after encountering a read error. This delay helps manage error recovery when data reading fails, preventing rapid-fire retry attempts that could overwhelm the device or network. The waiting period allows time for temporary communication issues to clear or for the device to recover from busy states before attempting another read operation.

**Type**: Integer

Default is 10000, the minimum value is 1000

---
### WaitAfterWriteError
The time in milliseconds to wait after an error sending a request to the device before sending again. After such an error the adapter closes the connection and connects again.

**Type**: Integer

Default is 10000, the minimum value is 1000



### ModbusTcpDeviceConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "Address": {
      "type": "string",
      "description": "IP address or hostname of the Modbus TCP device"
    },
    "ConnectTimeout": {
      "type": "integer",
      "description": "Connection timeout in milliseconds",
      "minimum": 1000,
      "default" : 10000
    },
    "DeviceId": {
      "type": "integer",
      "description": "Modbus unit ID",
      "default" : 1
    },
    "Port": {
      "type": "integer",
      "description": "TCP port number",
      "default": 502
    },
    "RequestDepth": {
      "type": "integer",
      "description": "Maximum number of requests sent before a response is received",
      "minimum": 1,
      "default": 1
    },
    "WaitAfterConnectError": {
      "type": "integer",
      "description": "Wait time after connection error in milliseconds",
      "minimum": 1000,
      "default" : 10000
    },
    "WaitAfterReadError": {
      "type": "integer",
      "description": "Wait time after read error in milliseconds",
      "minimum": 1000,
      "default" : 10000
    },
    "WaitAfterWriteError": {
      "type": "integer",
      "description": "Wait time after write error in milliseconds",
      "minimum": 1000,
      "default" : 10000
    }
  },
  "required": [
    "Address"
  ]
}
```



### ModbusTcpDeviceConfiguration Example

```json
{
  "Address": "192.168.1.100",
  "ConnectTimeout": 10000,
  "DeviceId": 1,
  "Port": 502,
  "WaitAfterConnectError": 5000,
  "WaitAfterReadError": 1000
}
```



[^top](#modbus-tcp-protocol-configuration)

