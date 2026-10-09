## SFC configuration

*Configuration file reference: every top-level key. How-to topics such as placeholders, secrets, templates, includes and signing are in the [configuration guide](../sfc-configuration.md).*

The Shop Floor Connectivity (SFC) top-level configuration defines the core structure and behavior of a system designed for industrial data collection and connectivity. It provides a framework for connecting manufacturing shopfloor devices and systems to AWS services, with features for protocol adaptation, data filtering, scheduling, and secure data transmission. The configuration manages everything from source connections to target destinations, including security credentials, health monitoring, logging, and data transformation capabilities, enabling consistent data collection from diverse industrial equipment.

A minimal working configuration (simulator to console, uberjar) is the [Quickstart simulator.json](../../README.md#2-helloworld-simulator-example). All configuration types: [core configuration types](./README.md).

How the sections connect:

- A [schedule](#schedules) lists source IDs (keys of [Sources](#sources)) with their channel IDs, and target IDs (keys of [Targets](#targets)).
- Each source names its protocol adapter with `ProtocolAdapter`, a key of [ProtocolAdapters](#protocoladapters).
- Each protocol adapter and target sets its static type with `AdapterType` or `TargetType`. The type is required in every deployment mode.
- The deployment mode decides where the code for that type is loaded from:

| Mode | Type sections | Protocol adapter or target entry |
|---|---|---|
| Uberjar | [AdapterTypes](#adaptertypes) / [TargetTypes](#targettypes), keyed by the type, with `FactoryClassName` only | `AdapterType` / `TargetType` |
| In-process | The same, plus `"JarFiles": ["${SFC_DEPLOYMENT_DIR}/<module>/lib"]` | `AdapterType` / `TargetType` |
| IPC | None; [AdapterServers](#adapterservers) / [TargetServers](#targetservers) instead, one service process per server | `AdapterType` / `TargetType`, plus `AdapterServer` / `TargetServer` |

Details: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode).

> **File paths on Windows.** In JSON a backslash starts an escape sequence. Write Windows paths with forward slashes, `"C:/sfc/certs/server.pem"`, or doubled backslashes, `"C:\\sfc\\certs\\server.pem"`. A single backslash either fails to parse (for example `Invalid escape sequence`) or silently changes the path (`"C:\temp"` contains a TAB). Relative paths are resolved against the directory SFC was started from, not the directory of the configuration file.

- [Schema](#schema)
- [Examples](#examples)


**Properties:**

- [AWSVersion](#awsversion)
- [AdapterServers](#adapterservers)
- [AdapterTypes](#adaptertypes)
- [AwsIotCredentialProviderClients](#awsiotcredentialproviderclients)
- [CacheUrlConfigResults](#cacheurlconfigresults)
- [CacheUrlConfigDirectory](#cacheurlconfigdirectory)
- [ChangeFilters](#changefilters)
- [ConditionFilters](#conditionfilters)
- [ConfigProvider](#configprovider)
- [ConfigSignature](#configsignature)
- [Description](#description)
- [ElementNames](#elementnames)
- [HealthProbe](#healthprobe)
- [LogLevel](#loglevel)
- [LogWriter](#logwriter)
- [Metadata](#metadata)
- [Metrics](#metrics)
- [MonitorIncludedConfigContentInterval](#monitorincludedconfigcontentinterval)
- [MonitorIncludedConfigFiles](#monitorincludedconfigfiles)
- [Name](#name)
- [ProtocolAdapters](#protocoladapters)
- [Schedules](#schedules)
- [SecretsManager](#secretsmanager)
- [Sources](#sources)
- [TargetServers](#targetservers)
- [TargetTypes](#targettypes)
- [Targets](#targets)
- [Templates](#templates)
- [Transformations](#transformations)
- [Tuning](#tuning)
- [ValueFilters](#valuefilters)
- [Version](#version)

---
### AWSVersion
Specifies the AWS compatibility version of the SFC configuration format. Optional; if present it must be "2022-04-02". This string value is used to maintain version control and manage future updates and extensions to the framework.

**Type**: String

---

### AdapterServers

Defines a mapping of [protocol adapter servers](../sfc-running-adapters.md#running-the-jvm-protocol-adapters-as-an-ipc-service) that operate as independent processes. Each server is identified by a unique string key and contains connection details for the SFC Core to communicate with it. The SFC Core uses gRPC streaming for efficient inter-process communication with these servers. These server configurations are referenced by their identifiers in the [AdapterServer](./protocol-adapter-configuration.md#adapterserver) property of entries in the [ProtocolAdapters](#protocoladapters) section, allowing for flexible deployment architectures where protocol adapters run separately from the main SFC Core process.

This is the IPC deployment mode. A protocol adapter that runs as an IPC service keeps its `AdapterType` and sets `AdapterServer` to one of these keys; it needs no [AdapterTypes](#adaptertypes) entry. Start the service on the port of its entry before starting SFC; see [IPC](../sfc-deployment.md#ipc).

**Type**: Map[String,[ServerConfiguration](./server-configuration.md)]

---
### AdapterTypes

Defines configuration for protocol adapters [running within the SFC core's JVM](../sfc-running-adapters.md#running-protocol-adapters-in-process), which is the case in the uberjar and in the in-process deployment modes. Maps adapter types (like OPCUA, MODBUS-TCP, S7) to their implementation details: the factory class and, for module bundles, the JAR files. The SFC core uses this configuration to dynamically load and create adapter instances, enabling new protocol types without core modifications. Limited to JVM implementations.

Each key is the static type of an adapter and must equal the `AdapterType` of the [protocol adapters](#protocoladapters) that use it. Use the type name given on the adapter's page (for example SIMULATOR, OPCUA, MODBUS-TCP, S7; all types: [Protocol adapter types and classes](../sfc-running-adapters.md#protocol-adapter-types-and-classes)); an adapter implementation does not pick up entries with other names.

- Uberjar ([installed by sfcup](../../README.md#1-install)): `FactoryClassName` only, no `JarFiles`.
- In-process with module bundles: `FactoryClassName` plus `"JarFiles": ["${SFC_DEPLOYMENT_DIR}/<module>/lib"]`.
- IPC: omit the entry. The protocol adapter keeps its `AdapterType` and sets `AdapterServer` to a key of [AdapterServers](#adapterservers).

How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode).

**Type**: Map[String,[InProcessConfiguration](./in-process-configuration.md)]

---

### AwsIotCredentialProviderClients
Defines a map of configurations for clients that use AWS IoT Core's credential provider service to obtain temporary security credentials. Each entry in the map consists of a client identifier (String) paired with its corresponding credential provider configuration. This allows devices to authenticate using X.509 certificates instead of storing long-term AWS credentials, enhancing security by providing temporary, limited-privilege session [credentials for accessing AWS services](../sfc-aws-service-credentials.md).

**Type**: Map[String,[AwsIotCredentialProviderClientConfiguration](./aws-iot-credential-provider-configuration.md)]

---
### ChangeFilters
[ChangeFilters](../sfc-data-processing-filtering.md#data-change-filters) that control when data values pass through based on detected changes. A value passes an Absolute or Percent filter when it differs from the last value that passed by at least the configured difference or percentage; all types are described under [Type](./change-filter-configuration.md#type). With [AtLeast](./change-filter-configuration.md#atleast), a value that did not change is passed again after a minimum interval; values that changed by less than the threshold stay filtered. These filters can be applied at both source and individual channel levels to optimize data transmission by filtering out insignificant changes.

**Type**: Map[String,[ChangeFilterConfiguration](./change-filter-configuration.md)]


Example:

```json

"ChangeFilters" : {
   "Change1PercentOrPer10Sec" : {
	   "Type": "Percent",
      "Value": 1,			
      "AtLeast": 10000
	},
   "AllChangesOrOncePer10Sec" : {
      "Type": "Always",
	   "AtLeast": 10000
   }				
}
```




---
### CacheUrlConfigResults

When enabled, configuration data retrieved from [external HTTP sources](../sfc-configuration.md#including-configuration-sections) will be cached in local files. If subsequent HTTP calls to fetch configuration data fail, the cached data will be used as a fallback. The location where these cached configuration files are stored is specified by the [CacheUrlConfigDirectory](#cacheurlconfigdirectory)  property. Default value is false.

**Type** : Boolean

---

### CacheUrlConfigDirectory

Directory where configuration data from [external HTTP sources](../sfc-configuration.md#including-configuration-sections) is cached when [CacheUrlConfigResults](#cacheurlconfigresults) is enabled. If subsequent HTTP calls to fetch configuration data fail, the cached files from this directory will be used as a fallback. The default is the working directory of the SFC core process, the directory SFC is started from. The directory must already exist. On Windows write the path with forward slashes, for example `"C:/sfc/cache"`.

**Type**: String

---

### ConditionFilters

[ConditionFilters](../sfc-data-processing-filtering.md#condition-filters) defines rules that evaluate whether specific channels have been read from a source, regardless of their actual values. This configuration checks for the presence or absence of channels in the data stream, rather than examining the data values within those channels. For example, it can verify if certain channels were successfully read, if they're missing, or create logical combinations of channel presence/absence 

**Type**: Map[String,[ConditionFilterConfiguration](./condition-filter-configuration.md)]


---
### ConfigProvider
Specifies the configuration for a [custom configuration handler](../sfc-extending.md#custom-configuration-handlers) that runs in-process with the main application. This allows for customized handling and processing of configuration data, enabling users to implement their own configuration management logic beyond the default functionality provided by the framework.

`JarFiles` is required in this section, as a list: list the provider's JAR files, or use `[]` when the class is already on the classpath, as with the uberjar, which bundles the example providers. Without `JarFiles` the section is silently ignored.

```json
"ConfigProvider": {
  "JarFiles": [],
  "FactoryClassName": "com.amazonaws.sfc.config.YamlConfigProvider"
}
```

Examples: [yaml-custom-config-provider](../../examples/yaml-custom-config-provider/README.md), [mqtt-config-provider](../../examples/mqtt-config-provider/README.md), [opcua-auto-discovery](../../examples/opcua-auto-discovery/README.md), [custom-config-provider](../../examples/custom-config-provider/README.md) (template).

**Type**: [InProcessConfiguration](./in-process-configuration.md)

---

### ConfigSignature

Digital signature of the configuration, added by the [sign-sfc-config](../../examples/sign-sfc-config/README.md) tool. SFC checks it when started with `-verify <public key file>`. See [Securing the configuration](../sfc-configuration.md#securing-the-configuration).

**Type**: String

---

### Description

A free-form text field that allows users to provide a descriptive explanation of the configuration's purpose, contents, or any other relevant information. This helps document and identify the configuration's intended use. 

**Type**: String

---
### ElementNames

Defines custom names for output elements in the data structure. This map allows customization of key element names in the output, with each entry specifying an alternative name for a standard element. The configurable elements include:

- Metadata: Name of the metadata node at top, source and channel level (default: "metadata")
- Schedule: Root element for the schedule (default: "schedule")
- Sources: Container element for sources (default: "sources")
- Timestamp: Timestamp elements (default: "timestamp")
- Value: Value-containing elements (default: "value")
- Values: Map of channel values within a source (default: "values")
- Serial: Unique serial number for target data (default: "serial")

All entries are optional, and any omitted elements will use their default names.

> Targets running as IPC services currently ignore ElementNames and use the default names.


---
### HealthProbe
Specifies the configuration for the [health probe endpoint](../sfc-health-endpoints.md) that monitors the main process's health status. This configuration determines how the system's health is monitored and reported, allowing external systems to check the operational status of the application.

The health probe helps in:

- Monitoring system availability
- Performing health checks
- Determining if the process is functioning correctly

This configuration is optional and can be customized through the HealthProbeConfiguration settings.

**Type**: [HealthProbeConfiguration](./health-probe-configuration.md)

---
### LogLevel
Specifies the verbosity level of [logged output](../sfc-logging-metrics.md#logging)  information. There are four available logging levels, in order of decreasing detail:

- "Trace": Most detailed level, includes all messages and detailed trace information
- "Info": Standard level showing informational, warning, and error messages
- "Warning": Shows only warning and error messages
- "Error": Most restrictive level, shows only error messages

The default setting is "Info" if not specified. This setting can be overridden at runtime using command-line parameters:

- -trace for trace level
- -info for info level
- -warning for warning level
- -error for error level

Put these options after `-config`, for example `-config config.json -trace`. A log level option placed before `-config` stops SFC from reading `-config`.

**Type**: String

---
### LogWriter
Specifies the configuration for a [custom log writer](../sfc-extending.md#custom-logging) that determines how log messages are output. By default, the [ConsoleLogWriter](../sfc-logging-metrics.md#logging)   writes messages to the console, but this configuration allows for implementing custom logging behavior to write logs to different destinations (like files, databases, or other logging systems) by providing your own log writer implementation that runs in-process with the main application.

As for [ConfigProvider](#configprovider), `JarFiles` is required in this section, as a list; use `[]` when the class is already on the classpath (uberjar). Without `JarFiles` the section is silently ignored.

```json
"LogWriter": {
  "JarFiles": [],
  "FactoryClassName": "com.amazonaws.sfc.log.CustomLogWriter"
}
```

Example: [custom-log-writer](../../examples/custom-log-writer/README.md) (template).

**Type**: [InProcessConfiguration](./in-process-configuration.md)

---

### Metadata

The optional [Metadata](../README.md#metadata) element can be used to add additional data to the output at the top level. If metadata is specified, which is a map of string indexed values, it is added to the metadata node at the top level of each output message, merged with the [Metadata](./schedule-configuration.md#metadata) of the schedule (schedule values win). The name of that node can be configured through the "Metadata" entry of the [ElementNames](./sfc-configuration.md#elementnames) configuration element.

**Type**: Map[String, String]

---
### Metrics
Defines the configuration settings for [metrics collection](../sfc-logging-metrics.md#metrics-collection) within the system. This configuration determines how performance metrics, operational statistics, and other measurable data points are gathered, processed, and reported. It allows for customization of metrics collection behavior through the MetricsConfiguration settings.

**Type**: [MetricsConfiguration](metrics-configuration.md)

---
### MonitorIncludedConfigContentInterval
Controls how often (in seconds) the system checks for changes in [external configuration content](../sfc-configuration.md#including-configuration-sections). When configuration is loaded from external URLs, this setting determines the frequency of checking if those external sources have been updated. The default checking interval is 60 seconds, and you can disable this monitoring completely by setting the value to 0.

**Type**: Integer

Default is 60, set to 0 to disable

> **Known issue:** in a configuration that uses includes (`@include`, `@file`, `@http`), setting this key, even to 0, currently stops the configuration from loading; SFC logs an error and keeps waiting. Leave it unset until this is fixed.

---
### MonitorIncludedConfigFiles
Determines whether the system actively monitors [included configuration files](../sfc-configuration.md#including-configuration-sections) for changes. When enabled (default is true), the system will detect modifications to included configuration files and automatically reload them. Setting this to false disables the monitoring, requiring manual intervention or system restart to pick up changes in included configuration files.

**Type**: Boolean

---
### Name
A custom identifier that can be assigned to the configuration. This optional string value allows you to give the configuration a meaningful name for easier identification and reference purposes.

**Type**: String

Optional

---

### ProtocolAdapters
Protocol adapters are the sources to read data from and abstract the actual protocol that is used to read the data. Each source used in a schedule must have a reference to a protocol adapter. As protocol adapters can be of different types, each inherited type has additional specific attributes for the protocol.

**Type**: Map[String, [ProtocolAdapterConfiguration](./protocol-adapter-configuration.md)]

---
### Schedules
Defines a collection of schedules that control data collection, processing, and transmission timing. Each schedule specifies when and how data moves from sources to targets. At least one active schedule must be configured for the system to operate.

**Type**: [[Schedule](./schedule-configuration.md)]

At least one active schedule needs to be present

---
### SecretsManager
Specifies how to retrieve sensitive information from AWS Secrets Manager to replace configuration placeholders. This allows secure storage and management of confidential data like credentials or connection strings that are referenced in the configuration.

**Type**: [SecretsManagerConfiguration](./secrets-manager-configuration.md)

---
### Sources

Defines a mapping of input sources where data is collected from, identified by unique source identifiers. Each source combines common configuration attributes used by the SFC core for scheduling and data processing, along with protocol-specific settings. Protocol implementations handle their specific attributes while adhering to the common SourceConfiguration framework. The configuration requires at least one source to be defined

**Type**: Map[String, [SourceConfiguration](./source-configuration.md)]

---
### TargetServers

Defines a mapping of target servers that operate as separate processes from the SFC core. Each server is identified by a unique string key and contains connection details for communication. The SFC Core uses gRPC for inter-process communication to send data to these targets. These server configurations are referenced by their identifiers in the [TargetServer](./target-configuration.md#targetserver) property of entries in the [Targets](#targets) section, enabling distributed processing where targets run independently of the main SFC Core.

This is the IPC deployment mode. A target that runs as an IPC service keeps its `TargetType` and sets `TargetServer` to one of these keys; it needs no [TargetTypes](#targettypes) entry. Start the service on the port of its entry before starting SFC; see [IPC](../sfc-deployment.md#ipc).

**Type**: Map[String,[ServerConfiguration](./server-configuration.md)]

---
### TargetTypes

Defines configuration for targets [running within the SFC core's JVM](../sfc-running-targets.md#running-targets-in-process), which is the case in the uberjar and in the in-process deployment modes. Maps target types (like DEBUG-TARGET, AWS-S3, AWS-SQS) to their implementation details: the factory class and, for module bundles, the JAR files. The SFC core uses this to dynamically load and create target instances, enabling extensibility without core modifications. Limited to JVM implementations.

Each key is the static type of a target and must equal the `TargetType` of the [targets](#targets) that use it. Use the type name given on the target's page (all types: [Target types and classes](../sfc-running-targets.md#target-types-and-classes)); a target implementation does not pick up entries with other names.

- Uberjar ([installed by sfcup](../../README.md#1-install)): `FactoryClassName` only, no `JarFiles`.
- In-process with module bundles: `FactoryClassName` plus `"JarFiles": ["${SFC_DEPLOYMENT_DIR}/<module>/lib"]`.
- IPC: omit the entry. The target keeps its `TargetType` and sets `TargetServer` to a key of [TargetServers](#targetservers).

How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode).

**Type**: Map[String,[InProcessConfiguration](./in-process-configuration.md)]

---
### Targets

Defines a mapping of data destinations (targets) identified by unique target identifiers. Each target combines common attributes used by the SFC core for data transmission, along with type-specific configuration settings. Target implementations handle their specific attributes while adhering to the common TargetConfiguration framework. These targets can be referenced as output destinations within schedules, allowing flexible routing of processed data


**Type**: Map[String,[TargetConfiguration](./target-configuration.md)]

---
### Templates
Defines a mapping of named [configuration templates](../sfc-configuration.md#configuration-templates), where each template name is associated with a JSON value (for example an object, a list, a string or a number). These templates can be reused across the SFC configuration to maintain consistency and reduce duplication in configuration settings. Example: [in-process-slmp-s3](../../examples/in-process-slmp-s3/README.md) (templates.json).

**Type**: Map[String, any JSON value]. Only scalar templates can be used inside a longer string.

---
### Transformations

Defines a mapping of transformation sequences identified by unique identifiers. Each sequence contains ordered operators that modify data values from input channels or aggregated outputs. Operators have specific parameters and must maintain type compatibility between steps. Transformations can process both single values and arrays, applying the same operations to each array element. These transformations can be referenced elsewhere in the configuration to modify data during processing.

**Type**: Map[String,[TransformationOperator](./transformation-operator-configuration.md)[]]


Example:

```json
{
   "DivBy2Add1Round": [
       {
           "Operator" : "Divide",
           "Operand" : 2
       },
       {
          "Operator" : "Add",
          "Operand" : 1
       },
       {
         "Operator" : "Round"
       }
    ]
 }
```

The transformation with identifier DivBy2Add1Round above Divides the input value by 2, then adds 1 and rounds the result.




---
### Tuning
Defines system-level performance tuning parameters for the SFC, allowing optimization of resource usage and operational behavior through configurable settings.

**Type**: [TuningConfiguration](./tuning-configuration.md)

---
### ValueFilters
Defines a mapping of [value filters](../sfc-data-processing-filtering.md#value-filters) that can be applied to individual channel values. Each filter is identified by a unique name and contains filter expressions that determine whether values should be included or excluded from processing. Values are only passed through if they satisfy the specified filter conditions

**Type**: Map[String,[ValueFilterConfiguration](./value-filter-configuration.md)]


Example:

```json
"ValueFilters": {
   "ValueEqual5": {
      "Operator": "eq",
      "Value": 5
   },
   "ValueEqualYes": {
      "Operator": "eq",
      "Value": "Yes"
   },
   "ValueInRange0-10": {
      "Operator": "and",
      "Value": [
         {
           "Operator": "ge",
           "Value": 0
         },
         {
           "Operator": "le",
           "Value": 10
         }
      ]
   }
}
```



---
### Version
Specifies an optional user-defined version for the configuration, a free-form value such as 1 or "1.2". This allows users to track and manage different versions of their SFC configuration.

**Type**: String

Optional

[^top](#sfc-configuration)

## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "AWSVersion": {
      "type": "string",
      "const": "2022-04-02"
    },
    "Schedules": {
      "type": "array",
      "items": {
        "$ref": "#/definitions/Schedule"
      },
      "minItems": 1
    },
    "Sources": {
      "type": "object",
      "patternProperties": {
        "^.*$": {
          "$ref": "#/definitions/SourceConfiguration"
        }
      },
      "minProperties": 1
    },
    "Targets": {
      "type": "object",
      "patternProperties": {
        "^.*$": {
          "$ref": "#/definitions/TargetConfiguration"
        }
      },
      "minProperties": 1
    },
    "AwsIotCredentialProviderClients": {
      "type": "object",
      "patternProperties": {
        "^.*$": {
          "$ref": "#/definitions/AwsIotCredentialProviderClientConfiguration"
        }
      }
    },
    "ChangeFilters": {
      "type": "object",
      "patternProperties": {
        "^.*$": {
          "$ref": "#/definitions/ChangeFilterConfiguration"
        }
      }
    },
    "ConditionFilters": {
      "type": "object",
      "patternProperties": {
        "^.*$": {
          "$ref": "#/definitions/ConditionFilterConfiguration"
        }
      }
    },
    "ConfigProvider": {
      "$ref": "#/definitions/InProcessConfiguration"
    },
    "Description": {
      "type": "string"
    },
    "ElementNames": {
      "type": "object",
      "propertyNames": {
        "enum": [
          "Metadata",
          "Schedule",
          "Sources",
          "Timestamp",
          "Value",
          "Values",
          "Serial"
        ]
      },
      "patternProperties": {
        "^.*$": {
          "type": "string"
        }
      },
      "default": {
        "Metadata": "metadata",
        "Schedule": "schedule",
        "Sources": "sources",
        "Timestamp": "timestamp",
        "Value": "value",
        "Values": "values",
        "Serial": "serial"
      }
    },
    "HealthProbe": {
      "$ref": "#/definitions/HealthProbeConfiguration"
    },
    "LogLevel": {
      "type": "string",
      "enum": [
        "Trace",
        "Info",
        "Warning",
        "Error"
      ],
      "default": "Info"
    },
    "LogWriter": {
      "$ref": "#/definitions/InProcessConfiguration"
    },
    "Metadata": {
      "type": "object",
      "additionalProperties": {
        "type": "string"
      }
    },
    "Metrics": {
      "$ref": "#/definitions/MetricsConfiguration"
    },
    "MonitorIncludedConfigContentInterval": {
      "type": "integer",
      "default": 60
    },
    "MonitorIncludedConfigFiles": {
      "type": "boolean",
      "default": true
    },
    "Name": {
      "type": "string"
    },
    "AdapterServers": {
      "type": "object",
      "patternProperties": {
        "^.*$": {
          "$ref": "#/definitions/ServerConfiguration"
        }
      }
    },
    "AdapterTypes": {
      "type": "object",
      "patternProperties": {
        "^.*$": {
          "$ref": "#/definitions/InProcessConfiguration"
        }
      }
    },
    "ProtocolAdapters": {
      "type": "object"
    },
    "SecretsManager": {
      "$ref": "#/definitions/SecretsManagerConfiguration"
    },
    "TargetServers": {
      "type": "object",
      "patternProperties": {
        "^.*$": {
          "$ref": "#/definitions/ServerConfiguration"
        }
      }
    },
    "TargetTypes": {
      "type": "object",
      "patternProperties": {
        "^.*$": {
          "$ref": "#/definitions/InProcessConfiguration"
        }
      }
    },
    "Templates": {
      "type": "object",
      "patternProperties": {
        "^.*$": {}
      }
    },
    "Transformations": {
      "type": "object",
      "patternProperties": {
        "^.*$": {
          "type": "array",
          "items": {
            "$ref": "#/definitions/TransformationOperator"
          },
          "minItems": 1
        }
      }
    },
    "Tuning": {
      "$ref": "#/definitions/TuningConfiguration"
    },
    "ValueFilters": {
      "type": "object",
      "patternProperties": {
        "^.*$": {
          "$ref": "#/definitions/ValueFilterConfiguration"
        }
      }
    },
    "Version": {
      "type": ["string", "number"]
    }
  },
  "required": [
    "Schedules",
    "Sources",
    "Targets"
  ],
  "allOf": [
    {
      "anyOf": [
        {
          "required": [
            "TargetTypes"
          ],
          "properties": {
            "TargetTypes": {
              "minProperties": 1
            }
          }
        },
        {
          "required": [
            "TargetServers"
          ],
          "properties": {
            "TargetServers": {
              "minProperties": 1
            }
          }
        }
      ]
    },
    {
      "anyOf": [
        {
          "required": [
            "AdapterTypes"
          ],
          "properties": {
            "AdapterTypes": {
              "minProperties": 1
            }
          }
        },
        {
          "required": [
            "AdapterServers"
          ],
          "properties": {
            "AdapterServers": {
              "minProperties": 1
            }
          }
        }
      ]
    }
  ]
}
```



## Examples

A minimal uberjar configuration is the [Quickstart simulator.json](../../README.md#2-helloworld-simulator-example).

The first two examples below are in-process configurations. They load the module bundles from the directory in `SFC_DEPLOYMENT_DIR`; set it in the terminal that starts `sfc-main` (see [In-process](../sfc-deployment.md#in-process)):

**Linux / macOS**

```shell
export SFC_DEPLOYMENT_DIR="$HOME/sfc"
```

**Windows (PowerShell)**

```powershell
$env:SFC_DEPLOYMENT_DIR = "C:/sfc"
```

To run them with the uberjar instead, remove the `JarFiles` entries.



S7 data to (debug) terminal and OPCUA targets, in-process configuration (module bundles)

```json
{
  "AWSVersion": "2022-04-02",
  "Schedules": [
    {
      "Name": "ConveyorData",
      "Interval": 1000,
      "TimestampLevel": "Both",
      "Sources": {
        "S7-SOURCE": ["*"]
      },
      "Targets": [
        "DebugTarget",
        "OpcuaTarget"
      ]
    }
  ],
  
  "Sources": {
    "S7-SOURCE": {
      "Name": "FluidConveyor",
      "ProtocolAdapter": "S7",
      "AdapterController": "S7-PLC-1",
      "Channels": {
        "Power": {
          "Address": "%DB120:230:DINT"
        },
        "Speed": {
          "Address": "%DB120:234:DINT"
        },
        "Temperature": {
          "Address": "%DB120:242:REAL",
          "Metadata": {
            "Unit": "Celsius"
          }
        },
        "Pressure": {
          "Address": "%DB120:246:REAL"
        }
      }
    }
  },
  
  "Targets": {
    "DebugTarget": {
      "TargetType": "DEBUG-TARGET"
    },
    "OpcuaTarget": {
      "TargetType": "OPCUA-TARGET",
      "AutoCreate" : true
    }
  },
  
  "TargetTypes": {
    "DEBUG-TARGET": {
      "JarFiles": [
        "${SFC_DEPLOYMENT_DIR}/debug-target/lib"
      ],
      "FactoryClassName": "com.amazonaws.sfc.debugtarget.DebugTargetWriter"
    },
    
    "OPCUA-TARGET": {
      "JarFiles": [
        "${SFC_DEPLOYMENT_DIR}/opcua-target/lib"
      ],
      "FactoryClassName": "com.amazonaws.sfc.opcuatarget.OpcuaTargetWriter"
    }
  },
  
  "AdapterTypes": {
    "S7": {
      "JarFiles": [
        "${SFC_DEPLOYMENT_DIR}/s7/lib"
      ],
      "FactoryClassName": "com.amazonaws.sfc.s7.S7Adapter"
    }
  },
  
  "ProtocolAdapters": {
    "S7": {
      "AdapterType": "S7",
      "Controllers": {
        "S7-PLC-1": {
          "Address": "192.168.1.130",
          "ControllerType": "S7-1200"
        }
      }
    }
  }
}
```

Runnable version: [s7-opcua-auto-create.json](../../examples/in-process-s7-opcua/s7-opcua-auto-create.json) in [in-process-s7-opcua](../../examples/in-process-s7-opcua/README.md).



Example with OPCUA source and AWS IoT Core target with metadata, filtering and transformations, in-process configuration (module bundles). Using a credentials client to obtain credentials using X.509 certificates required to make IoT Core service calls

```json
{
  "AWSVersion": "2022-04-02",
  "Schedules": [
    {
      "Name": "Pumpdata",
      "Interval": 100,
      "TimestampLevel": "Both",
      "Sources": {
        "Pump": ["*"]
      },
      "Targets": [ "IoTCoreTarget" ]
    }
  ],
  
  "ChangeFilters": {
    "ChangedBy10Percent": {
      "Type": "Percent",
      "Value": 10,
      "AtLeast": 60000
    }
  },
  
  "ValueFilters": {
    "GreaterThan0": {
      "Operator": "gt",
      "Value": 0
    }
  },
  
  "Transformations": {
    "TwoDigits": [
      {
        "Operator": "TruncAt",
        "Operand": 2
      }
    ]
  },
  
 "Sources": {
   
    "Pump": {
      "Name": "MainLiquidPump",
      "ProtocolAdapter": "OPCUA",
      "AdapterOpcuaServer": "PUMP-OPCUA-SERVER",
      "SourceReadingMode": "Subscription",
      
      "Metadata" : {
        "location" : "AMS",
        "environment" : "Production",
        "line" : "Prod-1"
      },
      
      "Channels": {
        "Pressure": {
          "Name": "MainPressure",
          "NodeId": "ns=3;i=1001",
          "ChangeFilter": "ChangedBy10Percent",
          "Transformation": "TwoDigits",
          "Metadata": {
            "Units": "Bar"
          }
        },
        
        "Flow": {
          "NodeId": "ns=3;i=1002",
          "Transformation": "TwoDigits",
          "Metadata": {
            "Units": "meter/sec"
          }
        },
        
        "Power": {
          "NodeId": "ns=3;i=1003",
          "Transformation": "TwoDigits",
          "ValueFilter": "GreaterThan0",
          "Metadata": {
            "Units": "watt"
          }
        }
      }
    }
  },
  
  "Targets": {
    "IoTCoreTarget": {
      "TargetType": "AWS-IOT-CORE",
      "Region": "eu-west-1",
      "TopicName": "pump-data-topic",
      "CredentialProviderClient": "AwsIotClient"
    }
  },
  
  "TargetTypes": {
    "AWS-IOT-CORE": {
      "JarFiles": [ "${SFC_DEPLOYMENT_DIR}/aws-iot-core-target/lib"],
      "FactoryClassName": "com.amazonaws.sfc.awsiotcore.AwsIotCoreTargetWriter"
    }
  },
  "AdapterTypes": {
    "OPCUA": {
      "JarFiles": ["${SFC_DEPLOYMENT_DIR}/opcua/lib" ],
      "FactoryClassName": "com.amazonaws.sfc.opcua.OpcuaAdapter"
    }
  },
  
  "ProtocolAdapters": {
    "OPCUA": {
      "AdapterType": "OPCUA",
      "OpcuaServers": {
        "PUMP-OPCUA-SERVER": {
          "Address": "opc.tcp://uademo.prosysopc.com",
          "Path": "OPCUA/SimulationServer",
          "Port": 53530
        }
      }
    }
  },
  
  "AwsIotCredentialProviderClients": {
    "AwsIotClient": {
      "IotCredentialEndpoint": "aaaaaaaaaa.credentials.iot.eu-west-1.amazonaws.com",
      "RoleAlias": "PumpTokenExchangeRoleAlias",
      "ThingName": "PumpThing-1",
      "CertificateFile": "./certificates/thingCert.crt",
      "PrivateKeyFile": "./certificates/privKey.key",
      "RootCa": "./certificates/rootCA.pem"
    }
  }
}
```

A runnable variant (uberjar, with the default AWS credentials instead of a credential provider client): [OPC UA to AWS IoT Core using filters](../../examples/opcua-to-iot-using-filters/README.md).



Example with 2 OPCUA sources and AWS IoT Core and Amazon S3 targets using IPC configuration. The protocol adapter and the two targets run as IPC services on other hosts; start them before SFC, see [IPC](../sfc-deployment.md#ipc).

Configuration is using Templates for repeating channel sections and region value.

```json
{
  "AWSVersion": "2022-04-02",
  "Schedules": [
    {
      "Name": "Pumpdata",
      "Interval": 100,
      "TimestampLevel": "Both",
      "Sources": {
        "Pump1": ["*"],
        "Pump2": ["*"]
      },
      "Targets": ["IoTCoreTarget", "S3Target"]
    }
  ],
  
  
  "Sources": {
    
    "Pump1": {
      "Name": "MainLiquidPump1",
      "ProtocolAdapter": "OPCUA",
      "AdapterOpcuaServer": "PUMP1-OPCUA-SERVER",
      "SourceReadingMode": "Subscription",
      "Metadata": {
        "location": "AMS",
        "environment": "Production",
        "line": "Prod-1"
      },
      "Channels": "$(PUMPDATA-CHANNELS-TEMPLATE)"
    },
    
    "Pump2": {
      "Name": "MainLiquidPump2",
      "ProtocolAdapter": "OPCUA",
      "AdapterOpcuaServer": "PUMP2-OPCUA-SERVER",
      "SourceReadingMode": "Subscription",
      "Metadata": {
        "location": "AMS",
        "environment": "Production",
        "line": "Prod-2"
      },
      "Channels": "$(PUMPDATA-CHANNELS-TEMPLATE)"
    }
  },
  
  "Targets": {
    "IoTCoreTarget": {
      "TargetServer": "IotCoreTargetServer",
      "TargetType": "AWS-IOT-CORE",
      "Region": "$(REGION-TEMPLATE)",
      "TopicName": "pump-data-topic",
      "CredentialProviderClient": "AwsIotClient"
    },
    "S3Target": {
      "Active": true,
      "TargetType": "AWS-S3",
      "TargetServer": "S3TargetServer",
      "Region": "$(REGION-TEMPLATE)",
      "BucketName": "ams-production",
      "Interval": 60,
      "BufferSize": 1,
      "Prefix": "pumpdata",
      "CredentialProviderClient": "AwsIotClient",
      "Compression": "Zip"
    }
  },
  
  "ProtocolAdapters": {
    "OPCUA": {
      "AdapterType": "OPCUA",
      "AdapterServer": "OpcuaProtocolAdapterServer",
      "OpcuaServers": {
        "PUMP1-OPCUA-SERVER": {
          "Address": "opc.tcp://production1",
          "Path": "/pumpdata",
          "Port": 53530
        },
        "PUMP2-OPCUA-SERVER": {
          "Address": "opc.tcp://production2",
          "Path": "/pumpdata",
          "Port": 53530
        }
      }
    }
  },
  "AdapterServers": {
    "OpcuaProtocolAdapterServer": {
      "Address": "192.168.1.10",
      "Port": 50000
    }
  },
  "TargetServers": {
    "IotCoreTargetServer": {
      "Address": "192.168.1.11",
      "Port": 40000
    },
    "S3TargetServer": {
      "Address": "192.168.1.11",
      "Port": 40001
    }
  },
  
  "AwsIotCredentialProviderClients": {
    "AwsIotClient": {
      "IotCredentialEndpoint": "aaaaaaaaaa.credentials.iot.$(REGION-TEMPLATE).amazonaws.com",
      "RoleAlias": "PumpTokenExchangeRoleAlias",
      "ThingName": "PumpThing-1",
      "CertificateFile": "./certificates/thingCert.crt",
      "PrivateKeyFile": "./certificates/privKey.key",
      "RootCa": "./certificates/rootCA.pem"
    }
  },
  
  "Templates": {
    
    "REGION-TEMPLATE": "eu-west-1",
    
    "PUMPDATA-CHANNELS-TEMPLATE": {
      "Pressure": {
        "NodeId": "ns=3;i=1001",
        "Metadata": {
          "Units": "bar"
        }
      },
      "Flow": {
        "NodeId": "ns=3;i=1002",
        "Metadata": {
          "Units": "meter/sec"
        }
      },
      "Power": {
        "NodeId": "ns=3;i=1003",
        "Metadata": {
          "Units": "watt"
        }
      }
    }
  }
}
```

Related runnable IPC example: [ipc-opcua-msk](../../examples/ipc-opcua-msk/README.md) (OPC UA to Amazon MSK).

[^top](#sfc-configuration)
