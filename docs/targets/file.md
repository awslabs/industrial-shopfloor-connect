# File Target

[SFC Configuration](../core/sfc-configuration.md) > [Targets](../core/sfc-configuration.md#targets) >  [Target](../core/target-configuration.md) 

The SFC File target adapter enables writing collected data to files in the local file system.

> **Windows:** the line breaks that the file target adds between and after records are CRLF (the pretty-printed JSON of a record uses LF). On Java 17 it also uses the Windows ANSI code page (for example windows-1252) instead of UTF-8, so characters outside that code page are written as `?`; Java 18 and later write UTF-8. On Java 17, set `$env:JAVA_TOOL_OPTIONS = "-Dfile.encoding=UTF-8"` in the terminal before you start SFC.

## Deploy this target

`TargetType` is `FILE-TARGET` in every deployment mode. In the uberjar and in-process modes the `TargetTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode). All types and classes: [Target types and classes](../sfc-running-targets.md#target-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"TargetTypes": {
  "FILE-TARGET": { "FactoryClassName": "com.amazonaws.sfc.filetarget.FileTargetWriter" }
}
```

**In-process** - module bundle `file-target` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"TargetTypes": {
  "FILE-TARGET": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/file-target/lib"],
    "FactoryClassName": "com.amazonaws.sfc.filetarget.FileTargetWriter"
  }
}
```

**IPC** - no `TargetTypes`; the target runs as its own service:

```json
"Targets": {
  "FileTarget": {
    "TargetType": "FILE-TARGET",
    "TargetServer": "FileTargetServer"
  }
},
"TargetServers": {
  "FileTargetServer": { "Address": "localhost", "Port": 50001 }
}
```

Start the service before SFC, on the port of its `TargetServers` entry:

**Linux / macOS**

```shell
file-target/bin/file-target -port 50001
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\file-target\lib\*" com.amazonaws.sfc.filetarget.FileTargetService -port 50001
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.filetarget.FileTargetService -port 50001` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.filetarget.FileTargetService -port 50001`).

**Examples:** uberjar: [uberjar-plc-sim-s3tables](../../examples/uberjar-plc-sim-s3tables/README.md#4-look-at-the-data) (writes every record to `out/`), every `uberjar-*-file` example in [one example per adapter and AWS target](../examples/README.md#one-example-per-adapter-and-aws-target) · all: [examples catalog](../examples/README.md)

## FileConfiguration

FileConfiguration extends the type  TargetConfiguration with specific configuration data for writing data to the local file system. The Targets configuration element can contain entries of this type; the TargetType of these entries must be set to **"FILE-TARGET"**

- [Schema](#fileconfiguration-schema)
- [Examples](#fileconfiguration-examples)

**Properties:**

- [BufferCount](#buffercount)
- [BufferSize](#buffersize)
- [Compression](#compression)
- [Directory](#directory)
- [Extension](#extension)
- [Formatter](#formatter)
- [Interval](#interval)
- [Json](#json)
- [Template](#template)
- [UtcTime](#utctime)

---
### BufferCount

The maximum number of messages to accumulate in the buffer. When this count is reached, all buffered messages are written to a file.

Batching is triggered when any configured threshold (BufferCount, [BufferSize](#buffersize), or [Interval](#interval)) is reached

**Type**: Int

Optional; when not set, only BufferSize and Interval apply.

---

### BufferSize

The size of the internal write buffer in kilobytes (KB) that determines when buffered data is flushed to the output file. When the buffer reaches this size, its contents are written to disk.

**Type**: Int

Must be in range 1-1024KB, default is 16KB

---
### Compression
The type of compression algorithm used to compress data written to the output file. 

**Type**: String

Possible values are:

- "None" (Default)
- "GZip"
- "Zip"

The values are case-sensitive; an unknown value such as "gzip" silently writes uncompressed files.

---
### Directory
The filesystem path where output files will be stored. Files are automatically organized in a hierarchical directory structure based on timestamp (year/month/day/hour/minute) with a unique UUID filename and appropriate extension.

**Type**: String

Files are written as `<Directory>/<year>/<month>/<day>/<hour>/<minute>/<uuid><extension>` (see [Extension](#extension)), for example `out/2026/10/8/9/5/3f1c….json`. The date and time components are not zero-padded, and on Windows the separators are backslashes.

The directory must exist before the target starts; a relative path resolves against the directory that the process running the target (SFC, or the file target service in IPC mode) is started from. Create it first:

**Linux / macOS**

```shell
mkdir -p /data/logs
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force C:\sfc\data | Out-Null
```

In the configuration write Windows paths with forward slashes, e.g. `"Directory": "C:/sfc/data"`.

---
### Extension
The file extension to be used for output files. If no extension is specified, but the file is compressed, then the corresponding extension for the compression method is used (`.zip` for Zip, `.gzip` for GZip). For compression types that support entry names (e.g., zip), the extension of the entry will be set to ".json" if the [Json](#json) field is true.

**Type**: String

---

### Formatter

Configuration allows for custom formatting of data written by a target. A [custom formatter](../sfc-extending.md#custom-formatters), implemented as a JVM class, converts a sequence of target data messages into a specific format and returns the formatted data as an array of bytes.

Formatter and [Template](#template) are mutually exclusive; setting both is a configuration error.

**Type:** [InProcessConfiguration](../core/in-process-configuration.md)

---
### Interval
The time interval in seconds that determines how often the internal buffer is flushed and written to the output file, regardless of  [buffer size](#buffersize).

**Type**: Int

Must be in range 60-900 seconds, default is 60 seconds

---
### Json
Determines whether the output file should be formatted as a valid JSON array document. When enabled and no [Template](#template) is set, the target wraps all output lines with square brackets and separates entries with commas. When disabled, records are written back to back without separators (without a Template, each record is pretty-printed JSON). Use it with [BufferCount](#buffercount) 1 (one record per file) or with a [Template](#template) that writes its own line endings.

**Type**: Boolean

Default is true

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
### UtcTime

Controls whether UTC or local system time is used when generating the timestamp-based directory structure and filenames. When true, UTC time is used; when false, the local time of the system running the adapter is used. 

**Type**: Boolean

Default is false

### FileConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "FileConfiguration",
  "type": "object",
  "allOf": [
    {
      "$ref": "#/definitions/TargetConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "BufferCount": {
          "type": "integer",
          "description": "Number of buffered messages that triggers writing a file"
        },
        "BufferSize": {
          "type": "integer",
          "description": "Buffer size in KB",
          "minimum": 1,
          "maximum": 1024,
          "default": 16
        },
        "Compression": {
          "type": "string",
          "description": "Type of compression to use",
          "enum": ["None", "Zip", "GZip"],
          "default": "None"
        },
        "Directory": {
          "type": "string",
          "description": "Directory path where files will be written"
        },
        "Extension": {
          "type": "string",
          "description": "File extension"
        },
        "Interval": {
          "type": "integer",
          "description": "Interval in seconds between file writes",
          "minimum": 60,
          "maximum": 900,
          "default": 60
        },
        "Json": {
          "type": "boolean",
          "description": "Whether to write in JSON format"
        },
        "UtcTime": {
          "type": "boolean",
          "description": "Whether to use UTC time for timestamps"
        }
      },
      "required": ["Directory"]
    }
  ]
}

```

### FileConfiguration Examples

```json

{
  "TargetType" : "FILE-TARGET",
  "Directory": "/data/logs",
  "Extension": ".json",
  "Json": true,
  "UtcTime": true,
  "Interval": 300,
  "BufferSize": 32
}
```

 Compressed Files:

```json
{
  "TargetType" : "FILE-TARGET",
  "Directory": "/var/log/sensors",
  "Compression": "GZip",
  "BufferSize": 64,
  "Interval": 600,
  "UtcTime": true
}
```

[^top](#file-target)

