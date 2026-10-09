# ADS Protocol Configuration



The ADS protocol adapter enables direct communication with Beckhoff PLCs through the ADS (Automation Device Specification) protocol. The adapter requires configuration of AMS Net IDs and ports for both source and target devices, which are essential for establishing the ADS communication route.

Key configuration points:

- Source AMS NetId/Port: Your SFC instance's ADS identity
- Target AMS NetId/Port: The Beckhoff PLC's ADS identity
- AdapterDevice: References the specific Beckhoff PLC in your devices configuration
- Channels: Define the PLC variables you want to read, mapped to SFC channels

The adapter handles the protocol-specific details of ADS communication, making it straightforward to integrate Beckhoff data into your existing SFC data collection infrastructure. Supported data types are BOOL, BYTE, WORD, DWORD, SINT, USINT, INT, UINT, DINT, UDINT, LINT, ULINT, REAL, LREAL, STRING, WSTRING, TIME, LTIME, DATE, DATE_AND_TIME, arrays of these (up to three dimensions) and the TwinCAT system-info structures. TIME_OF_DAY values are decoded as seconds instead of milliseconds since midnight, so they come out 1000 times too large. Other types are returned as raw bytes. If a SymbolName is not found, the error log lists the symbols the PLC offers.

**Try it without hardware:** [uberjar-plc-sim-s3tables](../../examples/uberjar-plc-sim-s3tables/README.md) reads a simulated TwinCAT 3 runtime served by the `omni-plc-sim` PLC simulator (`"TargetAmsNetId": "192.168.100.10.1.1"`, `"TargetAmsPort": 851`, symbols such as `GVL_Static.nInt` and `GVL_Dynamic.fSine`); the example's README shows how to list every simulated symbol.

## Deploy this adapter

`AdapterType` is `ADS` in every deployment mode. In the uberjar and in-process modes the `AdapterTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configuration-in-each-mode). All types and classes: [Protocol adapter types and classes](../sfc-running-adapters.md#protocol-adapter-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"AdapterTypes": {
  "ADS": { "FactoryClassName": "com.amazonaws.sfc.ads.AdsAdapter" }
}
```

**In-process** - module bundle `ads` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"AdapterTypes": {
  "ADS": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/ads/lib"],
    "FactoryClassName": "com.amazonaws.sfc.ads.AdsAdapter"
  }
}
```

**IPC** - no `AdapterTypes`; the adapter runs as its own service:

```json
"ProtocolAdapters": {
  "AdsAdapter": {
    "AdapterType": "ADS",
    "AdapterServer": "AdsServer"
  }
},
"AdapterServers": {
  "AdsServer": { "Address": "localhost", "Port": 50000 }
}
```

Start the service before SFC, on the port of its `AdapterServers` entry:

**Linux / macOS**

```shell
ads/bin/ads -port 50000
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\ads\lib\*" com.amazonaws.sfc.ads.AdsProtocolService -port 50000
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.ads.AdsProtocolService -port 50000` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.ads.AdsProtocolService -port 50000`).

**Examples:** uberjar: [uberjar-plc-sim-s3tables](../../examples/uberjar-plc-sim-s3tables/README.md), [uberjar-ads-file](../../examples/uberjar-ads-file/README.md) · in-process: [in-process-ads-s3](../../examples/in-process-ads-s3/README.md) · IPC: [ipc-ads-s3](../../examples/ipc-ads-s3/README.md) · all: [examples catalog](../examples/README.md)



**Configuration:**

- [AdsSourceConfiguration](#adssourceconfiguration)

- [AdsChannelConfiguration](#adschannelconfiguration)

- [AdsAdapterConfiguration](#adsadapterconfiguration)

- [AdsDeviceConfiguration](#adsdeviceconfiguration)

  

---

## AdsSourceConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [Sources](../core/sfc-configuration.md#sources) >  [Source](../core/source-configuration.md) 

Source configuration for the ADS protocol adapter. This type extends the [SourceConfiguration](../core/source-configuration.md) type and defines the necessary parameters to establish communication with a Beckhoff PLC through the ADS protocol. It specifies both the source (SFC) and target (PLC) AMS identities required for ADS routing, along with the device reference and channel configurations for data collection.

- [Schema](#adssourceconfiguration-schema)
- [Examples](#adssourceconfiguration-example) 

**Properties:**

- [AdapterDevice](#adapterdevice)
- [Channels](#channels)
- [SourceAmsNetId](#sourceamsnetid)
- [SourceAmsPort](#sourceamsport)
- [TargetAmsNetId](#targetamsnetid)
- [TargetAmsPort](#targetamsport)

---
### AdapterDevice
Specifies the device identifier that references a Beckhoff PLC defined in the Devices section of your ADS adapter configuration. This identifier must match an existing device entry in the ADS adapter's Devices configuration block. The referenced device contains the necessary PLC-specific settings and connection parameters required for establishing ADS communication.

**Type**: String

Must be an identifier of a server in the [Devices](#devices) section of the [ADS adapter](#adsadapterconfiguration) used by the source.

---
### Channels
Defines a map of channel configurations where each key is a unique channel identifier and each value contains the configuration for reading a specific PLC variable. Each channel specifies how to read and interpret data from the Beckhoff PLC, including the variable name, data type, and any necessary conversion parameters. The channel identifiers are used throughout SFC to reference these data points and must be unique within the source.

Individual channels can be disabled by prefixing their identifier with '#' in the configuration, allowing for easy testing and troubleshooting without removing the configuration.

**Type**: Map[String,[AdsChannelConfiguration](#adschannelconfiguration)]

At least 1 channel must be configured.

---
### SourceAmsNetId
The AMS (Automation Message Specification) NetID that identifies your SFC instance in the ADS network. The AMS NetID is a unique address in the format 'X.X.X.X.X.X' where X is a number between 0 and 255. This ID, combined with the AMS port, forms the complete ADS address that allows the Beckhoff PLC to recognize and communicate with your SFC instance as a valid ADS device.

For example: '192.168.1.10.1.1'

Note: The AMS NetID is different from an IP address, although the first four octets often match the IP address of the device. The last two octets are used to identify different ADS devices on the same network interface.


**Type**: String

The AMS Net ID consists of 6 bytes and is represented in a dot notation. For clients this is typically the network address + .1.1, e.g. 192.168.1.65.1.1

To authorize SFC as a client, this AMS Net ID must be added as an AMS route in SYSTEM/Routes of the TwinCAT target.

---
### SourceAmsPort
The AMS port of SFC itself, which together with [SourceAmsNetId](#sourceamsnetid) creates a unique address for your SFC instance in the ADS network. SFC only requires that it is set; the examples use 32905.

**Type**: Integer

---
### TargetAmsNetId
The Target AMS NetID identifies the Beckhoff PLC you want to communicate with in the ADS network. This is a unique address in the format 'X.X.X.X.X.X' where X is a number between 0 and 255 (for example: '192.168.1.20.1.1').

This ID represents the destination PLC for your ADS communications and must match the AMS NetID configured in the PLC's TwinCAT system. You can find the Target AMS NetID in TwinCAT by:

- Opening TwinCAT System Manager on the target PLC
- Right-clicking on the system tree
- Selecting 'Router' → 'Show Route Settings'
- Looking for the 'AMS Net ID' field

The Target AMS NetID, combined with the Target AMS Port, forms the complete address that SFC uses to route ADS messages to the correct PLC in your network. Incorrect configuration of this ID will prevent successful communication with the PLC.


**Type**: String

The AMSNetID consists of 6 bytes and is represented in a dot notation.

---
### TargetAmsPort
The AMS port of the runtime system you want to access on the target Beckhoff PLC. Together with [TargetAmsNetId](#targetamsnetid) it creates the complete address for routing messages to the correct service on the PLC. SFC reads the symbol table and the values from this port. If no ADS service runs on it, the PLC answers with ADS router error 6, which SFC logs as "Target port not found".

For TwinCAT systems the port numbers are predefined based on the runtime system:

TwinCAT 3:

- Runtime system 1: 851
- Runtime system 2: 852
- Runtime system 3: 853
- Runtime system 4: 854
- Runtime system 5: 855
- Additional runtime systems follow the pattern: 850 + n

TwinCAT 2: 801 for the first runtime system.

**Type**: Integer

[^top](#ads-protocol-configuration)



### AdsSourceConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "allOf": [
    {
      "$ref": "#/definitions/BaseSourceConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "AdapterDevice": {
          "type": "string",
          "description": "ADS adapter device identifier"
        },
        "Channels": {
          "type": "object",
          "description": "Map of channel configurations indexed by string",
          "patternProperties": {
            "^.*$": {
              "$ref": "external-schema.json#/definitions/AdsChannelConfiguration"
            }
          },
          "minProperties": 1
        },
        "SourceAmsNetId": {
          "type": "string",
          "description": "AMS Net ID of SFC itself"
        },
        "SourceAmsPort": {
          "type": "integer",
          "description": "AMS port of SFC itself",
          "minimum": 0,
          "maximum": 65535
        },
        "TargetAmsNetId": {
          "type": "string",
          "description": "AMS Net ID of the PLC"
        },
        "TargetAmsPort": {
          "type": "integer",
          "description": "AMS port of the PLC runtime system"
        }
      },
      "required": ["AdapterDevice", "Channels", "SourceAmsNetId", "SourceAmsPort", "TargetAmsNetId", "TargetAmsPort"],
      "additionalProperties": false
    }
  ]
}

```

### AdsSourceConfiguration Example

```json
{
  "Description": "Assembly Line PLC",
  "Name": "AssemblyPLC1",
  "ProtocolAdapter": "ads-adapter",
  "AdapterDevice": "PLC1",
  "Channels": {
    "temperature": {
      "Name": "Temperature_Sensor",
      "SymbolName": "MAIN.Temperature"
    },
    "pressure": {
      "Name": "Pressure_Sensor",
      "SymbolName": "MAIN.PressureValue"
    },
    "speed": {
      "Name": "Conveyor_Speed",
      "SymbolName": "MAIN.ConveyorSpeed"
    }
  },
  "SourceAmsNetId": "192.168.1.10.1.1",
  "SourceAmsPort": 32905,
  "TargetAmsNetId": "192.168.1.20.1.1",
  "TargetAmsPort": 851
}
```





## AdsChannelConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [Sources](../core/sfc-configuration.md#sources) > [Source](../core/source-configuration.md)  > [Channels](../core/source-configuration.md#channels) > [Channel](../core/channel-configuration.md)

Defines the configuration for reading a PLC variable through ADS protocol by specifying the variable's symbol name as defined in the TwinCAT project.

The AdsChannelConfiguration type extends the [ChannelConfiguration](../core/channel-configuration.md) class with channel properties for the ADS protocol adapter.



- [Schema](#adschannelconfiguration-schema)
- [Example](#adschannelconfiguration-example)

**Properties:**

- [SymbolName](#symbolname)

---
### SymbolName
The name of the PLC variable to read via ADS protocol. Must match a symbol name exactly as listed in the PLC symbol table, for example 'MAIN.Temperature' or 'GVL_Dynamic.fSine'. The name is case-sensitive.

Member paths such as 'MAIN.MyStruct.Temperature' are not resolved. Apart from the TwinCAT system-info types (PlcAppSystemInfo, PlcTaskSystemInfo, ST_LibVersion), user structures, enums, function blocks and LWORD are returned as raw bytes.

**Type**: String

[^top](#ads-protocol-configuration)



### AdsChannelConfiguration Schema

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
        "SymbolName": {
          "type": "string",
          "description": "ADS symbol name for the channel"
        }
      },
      "additionalProperties": false
    }
  ]
}

```



### AdsChannelConfiguration Example

```json
{
      "Name": "Temperature_Sensor",
      "SymbolName": "MAIN.Temperature"
    }
```



## AdsAdapterConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [ProtocolAdapters](../core/sfc-configuration.md#protocoladapters) > [Adapter](../core/protocol-adapter-configuration.md) 

Configuration for the ADS protocol adapter that enables communication with Beckhoff PLCs. Extends the base AdapterConfiguration type to provide ADS-specific settings.

AdsAdapterConfiguration extends the [AdapterConfiguration](../core/protocol-adapter-configuration.md) with properties for the ADS Protocol adapter.

- [Schema](#adsadapterconfiguration-schema)
- [Example](#adsadapterconfiguration-example)

**Properties:**

- [Devices](#devices)

---
### Devices
Collection of Beckhoff PLC device configurations that specify the connection parameters for each PLC that will be accessed through the ADS protocol. Devices configured for this adapter. The ADS source using the adapter must have a reference to one of these in its AdapterDevice attribute.

**Type**: Map[String,[AdsDeviceConfiguration](#adsdeviceconfiguration)]

[^top](#ads-protocol-configuration)



### AdsAdapterConfiguration Schema

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
          "description": "Map of ADS devices indexed by string",
          "patternProperties": {
            "^.*$": {
              "$ref": "external-schema.json#/definitions/AdsDeviceConfiguration"
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



### AdsAdapterConfiguration Example

```json
{
  "Description": "Production line ADS adapter",
  "AdapterType" : "ADS",
  "Devices": {
    "assembly_plc": {
      "Address": "192.168.1.101"
    },
    "packaging_plc": {
      "Address": "192.168.1.102"
    },
    "quality_plc": {
      "Address": "192.168.1.103"
    }
  }
}

```





## AdsDeviceConfiguration

[AdsAdapterConfiguration](#adsadapterconfiguration) > [Devices](#devices)

Configuration for a specific Beckhoff PLC device that will be accessed through the ADS protocol. Defines the connection parameters required to establish communication with the PLC. Each device configuration can be referenced by ADS sources through their AdapterDevice attribute.

- [Schema](#adsdeviceconfiguration-schema)
- [Example](#adsdeviceconfiguration-example)


**Properties:**
- [Address](#address)
- [CommandTimeout](#commandtimeout)
- [ConnectTimeout](#connecttimeout)
- [Port](#port)
- [ReadTimeout](#readtimeout)
- [WaitAfterConnectError](#waitafterconnecterror)
- [WaitAfterReadError](#waitafterreaderror)
- [WaitAfterWriteError](#waitafterwriteerror)

---
### Address
The IP address or hostname of the Beckhoff PLC device that will be accessed through ADS protocol.

**Type**: String

IP address in format aaa.bbb.ccc.ddd

---
### CommandTimeout
The maximum time, in milliseconds, to wait for an ADS command to complete before timing out. Controls how long the adapter will wait for responses from the PLC device

**Type**: Integer

Default is 10000 milliseconds

---
### ConnectTimeout
The maximum time, in milliseconds, to wait when attempting to establish a connection with the Beckhoff PLC device. If the connection cannot be established within this time period, the connection attempt will fail.

**Type**: Integer

Default is 10000

---
### Port
The TCP/IP port number used to communicate with the Beckhoff PLC device. The default ADS port number is typically 48898, but may be configured differently based on the PLC's network configuration.

**Type**: Integer

Default is 48898

---
### ReadTimeout
The maximum time, in milliseconds, to wait for each byte of a response from the Beckhoff PLC device. The complete request and response are bounded by [CommandTimeout](#commandtimeout).

**Type**: Integer

Default is 1000

---
### WaitAfterConnectError
The delay time, in milliseconds, that the adapter will wait before attempting to reconnect to the Beckhoff PLC device after experiencing a connection error. This helps prevent rapid reconnection attempts that could overwhelm the network or device.

**Type**: Integer

Default is 10000

---
### WaitAfterReadError
The delay time, in milliseconds, that the adapter will wait before attempting another read operation after encountering a read error. This delay helps prevent excessive read attempts during error conditions and allows the PLC device time to recover from error states.

**Type**: Integer

Default is 10000

---
### WaitAfterWriteError
The delay time, in milliseconds, that the adapter will wait before attempting another write operation after encountering a write error. This delay helps prevent excessive write attempts during error conditions and allows the PLC device time to recover from communication or processing failures.

**Type**: Integer

Default is 10000

[^top](#ads-protocol-configuration)



### AdsDeviceConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "description": "Configuration for an ADS device",
  "properties": {
    "Address": {
      "type": "string",
      "description": "IP address or hostname of the ADS device"
    },
    "CommandTimeout": {
      "type": "integer",
      "description": "Timeout for command execution in milliseconds",
      "default": 10000
    },
    "ConnectTimeout": {
      "type": "integer",
      "description": "Timeout for connection establishment in milliseconds",
      "default": 10000
    },
    "Port": {
      "type": "integer",
      "description": "TCP port number for the ADS connection",
      "default": 48898
    },
    "ReadTimeout": {
      "type": "integer",
      "description": "Timeout per response byte in milliseconds",
      "default": 1000
    },
    "WaitAfterConnectError": {
      "type": "integer",
      "description": "Wait time after connection error in milliseconds",
      "default": 10000
    },
    "WaitAfterReadError": {
      "type": "integer",
      "description": "Wait time after read error in milliseconds",
      "default": 10000
    },
    "WaitAfterWriteError": {
      "type": "integer",
      "description": "Wait time after write error in milliseconds",
      "default": 10000
    }
  },
  "required": ["Address"]
}
```



### AdsDeviceConfiguration Example

Basic configuration:

```json
{
  "Address": "192.168.1.100",
  "Port": 48898
}
```

Full configuration:

```json
{
  "Address": "192.168.1.100",
  "Port": 48898,
  "CommandTimeout": 5000,
  "ConnectTimeout": 10000,
  "ReadTimeout": 1000,
  "WaitAfterConnectError": 5000,
  "WaitAfterReadError": 1000,
  "WaitAfterWriteError": 1000
}
```

[^top](#ads-protocol-configuration)

