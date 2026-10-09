# Debug Target

[SFC Configuration](../core/sfc-configuration.md) > [Targets](../core/sfc-configuration.md#targets) >  [Target](../core/target-configuration.md)

The SFC Debug target adapter provides a simple way to output collected data to the system console for debugging and development purposes. It can display source values, metadata, and timestamps in a readable format, helping developers verify data collection and transformation processes. The adapter is particularly useful for building and testing transformation templates, allowing developers to validate template output before configuring production targets. It supports configurable output formatting to facilitate troubleshooting of data flows.

## Deploy this target

`TargetType` is `DEBUG-TARGET` in every deployment mode. In the uberjar and in-process modes the `TargetTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configuration-in-each-mode). All types and classes: [Target types and classes](../sfc-running-targets.md#target-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"TargetTypes": {
  "DEBUG-TARGET": { "FactoryClassName": "com.amazonaws.sfc.debugtarget.DebugTargetWriter" }
}
```

**In-process** - module bundle `debug-target` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"TargetTypes": {
  "DEBUG-TARGET": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/debug-target/lib"],
    "FactoryClassName": "com.amazonaws.sfc.debugtarget.DebugTargetWriter"
  }
}
```

**IPC** - no `TargetTypes`; the target runs as its own service:

```json
"Targets": {
  "DebugTarget": {
    "TargetType": "DEBUG-TARGET",
    "TargetServer": "DebugTargetServer"
  }
},
"TargetServers": {
  "DebugTargetServer": { "Address": "localhost", "Port": 50001 }
}
```

Start the service before SFC, on the port of its `TargetServers` entry:

**Linux / macOS**

```shell
debug-target/bin/debug-target -port 50001
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\debug-target\lib\*" com.amazonaws.sfc.debugtarget.DebugTargetService -port 50001
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.debugtarget.DebugTargetService -port 50001` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.debugtarget.DebugTargetService -port 50001`).

**Examples:** uberjar: [Quickstart step 2](../../README.md#2-helloworld-simulator-example), [opcua-to-iot-using-filters](../../examples/opcua-to-iot-using-filters/README.md) · in-process: [in-process-sim-s3tables](../../examples/in-process-sim-s3tables/README.md), [in-process-opcua-sitewise](../../examples/in-process-opcua-sitewise/README.md), [in-process-opcua-sitewiseedge](../../examples/in-process-opcua-sitewiseedge/README.md) · IPC: [ipc-opcua-msk](../../examples/ipc-opcua-msk/README.md) · all: [examples catalog](../examples/README.md)

## Configuration

A debug target is a plain [TargetConfiguration](../core/target-configuration.md) entry; it has no additional elements. The Targets configuration element can contain entries of this type, the TargetType of these entries must be set to **"DEBUG-TARGET"**.

Each record is printed as pretty-printed JSON (or as the output of its [Template](#template) or [Formatter](#formatter)), as an Info message on the console of the process that runs the target: SFC itself, or the debug target service in IPC mode. With the log level of that process set to Warning or Error (`LogLevel` in its configuration, or the `-warning` and `-error` options) nothing is printed. [Quickstart step 2](../../README.md#2-helloworld-simulator-example) shows the output.

- [Schema](#schema)
- [Example](#example)

**Properties:**

- [Formatter](#formatter)

- [Template](#template)

---

### Formatter

Configuration allows for custom formatting of data written by a target. A [custom formatter](../sfc-extending.md#custom-formatters), implemented as a JVM class, converts a sequence of target data messages into a specific format and returns the formatted data as an array of bytes.

Formatter and [Template](#template) are mutually exclusive; setting both is a configuration error.

**Type:** [InProcessConfiguration](../core/in-process-configuration.md)

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



## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DebugConfiguration",
  "type": "object",
  "allOf": [
    {
      "$ref": "#/definitions/TargetConfiguration"
    }
  ]
}
```



## Example

```json
"Targets": {
  "DebugTarget": {
    "Active": true,
    "TargetType": "DEBUG-TARGET"
  }
}
```

