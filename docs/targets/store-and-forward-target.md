# Store and Forward Target

[SFC Configuration](../core/sfc-configuration.md) > [Targets](../core/sfc-configuration.md#targets) >  [Target](../core/target-configuration.md) 

The SFC Store and Forward Target acts as an intermediate buffer between SFC-Core and downstream targets, providing reliable message delivery through persistent storage. When configured targets become unavailable, this target automatically stores data to disk, preventing message loss during network interruptions or target system outages. Once connectivity is restored, the stored messages are forwarded to their intended destinations in the order they were received, reducing data loss in the processing pipeline.

Buffering starts when a next target in the chain cannot accept a record or reports it as not acknowledged (NACK), see [Known limitations](#known-limitations). How to configure a chain: [Target chaining](../sfc-targets-chaining.md).

The store and forward target uses the following logic:

- In normal situations the target will forward the target data to the next targets.
- For messages that can be delivered to their destinations these targets will send ACKs containing the serial number of
  the delivered messages.
- When the targets cannot deliver messages, NACKS, including the full message will be returned.
- When receiving NACKs the store and forward target will go into buffering mode and will start buffering data received
  by the core to disk.
- In buffering mode, the store and forward target will periodically send a buffered message, which is the oldest message
  that falls in the retention strategy (see below) of the buffer if the buffer is configured to operate in FIFO mode,
  which is the default. In LIFO mode the most recent message is used. An internal flag is set in the message to indicate
  to the target that this message should not be buffered but send directly to their destinations.
- The target will try to deliver this message to the destination and report an ACK or NACK for that message.
- When an ACK is received the store and forward target will switch back from buffering mode into normal mode after
  submitting the buffered data. This will happen in FIFO or LIFO mode based on configuration.
- Messages for which an ERROR is received are not stored and in case they are buffered removed from the store as this
  means they cannot be processed by the target.


## Known limitations

- Records that a next target reports as an error are dropped, not buffered. The MQTT target reports a NACK only when it
  never connected or a publish times out, so a broker connection that is lost while SFC runs is reported as an error.
  Most AWS targets report a NACK only when the service host name cannot be resolved or the connection pool is shut
  down, so a refused connection or a connect timeout is reported as an error.
- Enable metrics collection (a top-level `Metrics` section with a `Writer`, see
  [Metrics collection](../sfc-logging-metrics.md#metrics-collection)). Without it, the target stops resubmitting
  buffered records once the next targets recover.
- At least two of [RetainFiles](#retainfiles), [RetainPeriod](#retainperiod) and [RetainSize](#retainsize) must be
  set; a configuration with exactly one is rejected. Only the first one that is set, in the order RetainFiles,
  RetainPeriod, RetainSize, is applied.


## Retention strategies

In order to prevent running out of disk space of the device that is used to store the buffered messages a retention
strategy must be defined for a store and forward target. This can be a period in minutes, a number of messages
per target, or the total size in MB per target (see [Known limitations](#known-limitations)). Data in the buffer that
falls outside the used retention criteria will not be resubmitted and automatically deleted from the storage device.

In order to reduce the storage of buffered messages the target will try to use hard links for messages that need to be
stored for multiple end targets, if the file system of that device supports it (NTFS does; on FAT32 and exFAT volumes
a separate copy is written for each target).

**PLEASE NOTE**  

Storing messages to a physical device can reduce the throughput of the SFC deployment. It is strongly recommended to run
the process that contains the store and forward target, in-process or as an IPC service, on a device that has a fast
storage device.

## Deploy this target

`TargetType` is `STORE-FORWARD` in every deployment mode. In the uberjar and in-process modes the `TargetTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configuration-in-each-mode). All types and classes: [Target types and classes](../sfc-running-targets.md#target-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"TargetTypes": {
  "STORE-FORWARD": { "FactoryClassName": "com.amazonaws.sfc.storeforward.StoreForwardTargetWriter" }
}
```

**In-process** - module bundle `store-forward-target` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"TargetTypes": {
  "STORE-FORWARD": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/store-forward-target/lib"],
    "FactoryClassName": "com.amazonaws.sfc.storeforward.StoreForwardTargetWriter"
  }
}
```

**IPC** - no `TargetTypes`; the target runs as its own service:

```json
"Targets": {
  "StoreForwardTarget": {
    "TargetType": "STORE-FORWARD",
    "TargetServer": "StoreForwardTargetServer"
  }
},
"TargetServers": {
  "StoreForwardTargetServer": { "Address": "localhost", "Port": 50001 }
}
```

Start the service before SFC, on the port of its `TargetServers` entry:

**Linux / macOS**

```shell
store-forward-target/bin/store-forward-target -port 50001
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\store-forward-target\lib\*" com.amazonaws.sfc.storeforward.AwsStoreForwardTargetService -port 50001
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.storeforward.AwsStoreForwardTargetService -port 50001` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.storeforward.AwsStoreForwardTargetService -port 50001`).

**Examples:** none yet - start from [Quickstart step 2](../../README.md#2-helloworld-simulator-example) and swap in this component. All: [examples catalog](../examples/README.md)

**Configuration:**

---

## StoreForwardTargetConfiguration

StoreForwardTargetConfiguration extends the type [TargetConfiguration](../core/target-configuration.md) with specific configuration data for forwarding and buffering target data to the next targets configured for this target. The Targets configuration element can contain entries of this type; the TargetType of these entries must be set to **"STORE-FORWARD"**.



- [Schema](#storeforwardtargetconfiguration-schema)
- [Examples](#storeforwardtargetconfiguration-examples)

**Properties:**

- [CleanupInterval](#cleanupinterval)
- [Directory](#directory)
- [Fifo](#fifo)
- [RetainFiles](#retainfiles)
- [RetainPeriod](#retainperiod)
- [RetainSize](#retainsize)
- [Targets](#targets)
- [WriteTimeout](#writetimeout)

---
### CleanupInterval
The CleanupInterval property defines how frequently (in seconds) the target executes its internal cleanup procedure while operating in buffering mode. This maintenance process helps manage stored data and system resources. If not specified, the cleanup procedure runs every 60 seconds.

**Type**: Int

---
### Directory
The Directory property specifies the filesystem path where buffered messages will be stored when targets are unavailable. The specified directory must exist prior to target initialization, and the process running the Store and Forward target must have both read and write permissions for this location. A relative path resolves against the directory that process is started from. On Windows write the path with forward slashes, e.g. `"Directory": "C:/sfc/store"`.

**Type**: String

---
### Fifo
The Fifo property controls the order in which buffered messages are resubmitted to targets. When set to true (default), messages are processed in First-In-First-Out order, ensuring the oldest stored messages are sent first. When set to false, the most recent messages take priority in resubmission.

**Type**: Boolean


---
### RetainFiles
The RetainFiles property sets the maximum number of buffered files to retain per target before implementing deletion. The minimum allowed value is 100 files. This property is part of the retention strategy system - currently at least two of RetainFiles, [RetainPeriod](#retainperiod) and [RetainSize](#retainsize) must be configured, and only the first one in that order is applied (see [Known limitations](#known-limitations)).

**Type**: Int

---
### RetainPeriod
The RetainPeriod property defines how long (in minutes) buffered messages are kept before deletion. The minimum retention period is 5 minutes. This property is part of the retention strategy system - currently at least two of [RetainFiles](#retainfiles), RetainPeriod and [RetainSize](#retainsize) must be configured, and only the first one in that order is applied (see [Known limitations](#known-limitations)).

**Type**: Int

---
### RetainSize
The RetainSize property specifies the maximum total size (in megabytes) of buffered files to retain per target before implementing deletion. The minimum allowed value is 1 MB. This property is part of the retention strategy system - currently at least two of [RetainFiles](#retainfiles), [RetainPeriod](#retainperiod) and RetainSize must be configured, and only the first one in that order is applied (see [Known limitations](#known-limitations)).

**Type**: Int

---
### Targets
The Targets property defines an array of target IDs for which message buffering and forwarding will be enabled. These specified targets must be already configured within the same configuration file, either as in-process targets or as IPC service targets, and must be listed in the [Targets](../core/sfc-configuration.md#targets) property of the SFC configuration. 

**Type**: Array of String

---
### WriteTimeout
The WriteTimeout property specifies the maximum time (in seconds) allowed for write operations to complete when storing messages to the storage device. If a write operation exceeds this timeout, it will be considered failed. If not specified, the default timeout is 10 seconds.

**Type**: Int



### StoreForwardTargetConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "StoreForwardTargetConfiguration",
  "type": "object",
  "allOf": [
    {
      "$ref": "#/definitions/TargetConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "CleanupInterval": {
          "type": "integer",
          "description": "Interval in seconds between cleanup operations"
        },
        "Directory": {
          "type": "string",
          "description": "Directory path for storing files"
        },
        "Fifo": {
          "type": "boolean",
          "description": "Use FIFO (First In First Out) processing order",
          "default": true
        },
        "RetainFiles": {
          "type": "integer",
          "description": "Maximum number of files to retain"
        },
        "RetainPeriod": {
          "type": "integer",
          "description": "Period in minutes to retain files"
        },
        "RetainSize": {
          "type": "integer",
          "description": "Maximum total size in MB to retain",
          "minimum": 1
        },
        "Targets": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "description": "List of target IDs to forward data to",
          "minItems": 1
        },
        "WriteTimeout": {
          "type": "integer",
          "description": "Timeout in seconds for write operations",
          "minimum": 0
        }
      },
      "required": ["Directory", "Targets"]
    }
  ]
}

```

### StoreForwardTargetConfiguration Examples

A store and forward target in front of a [File target](./file.md), in the uberjar style. To try it, use these sections in place of the `Targets` and `TargetTypes` of [Quickstart step 2](../../README.md#2-helloworld-simulator-example), set the schedule's `Targets` to `["StoreForward"]`, and create the `store` and `out` directories in the directory you start SFC from:

**Linux / macOS**

```shell
mkdir -p store out
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force store, out | Out-Null
```

```json
"Targets": {
  "StoreForward": {
    "TargetType": "STORE-FORWARD",
    "Directory": "./store",
    "Targets": ["File"],
    "Fifo": true,
    "RetainSize": 10240,
    "RetainFiles": 1000,
    "CleanupInterval": 60
  },
  "File": {
    "TargetType": "FILE-TARGET",
    "Directory": "./out",
    "Json": true,
    "Extension": ".json",
    "BufferCount": 1
  }
},
"TargetTypes": {
  "STORE-FORWARD": { "FactoryClassName": "com.amazonaws.sfc.storeforward.StoreForwardTargetWriter" },
  "FILE-TARGET": { "FactoryClassName": "com.amazonaws.sfc.filetarget.FileTargetWriter" }
}
```

Both `RetainSize` and `RetainFiles` are set because the current release needs two retention criteria; only `RetainFiles` is applied (see [Known limitations](#known-limitations)).

[^top](#store-and-forward-target)

