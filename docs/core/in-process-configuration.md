## InProcessConfiguration

[SFC Configuration](./sfc-configuration.md) > [AdapterTypes](./sfc-configuration.md#adaptertypes)

[SFC Configuration](./sfc-configuration.md) > [TargetTypes](./sfc-configuration.md#targettypes) 

[SFC Configuration](./sfc-configuration.md) > [Metrics](./metrics-configuration.md) > [Writer](./metrics-configuration.md#writer) > [MetricsWriter](./metrics-writer-configuration.md#metricswriter)

[SFC Configuration](./sfc-configuration.md) > [LogWriter](./sfc-configuration.md#logwriter)

[SFC Configuration](./sfc-configuration.md) > [ConfigProvider](./sfc-configuration.md#configprovider)

[SFC Configuration](./sfc-configuration.md) > [Targets](./sfc-configuration.md#targets) > [Target](./target-configuration.md) > [Formatter](./target-configuration.md#formatter)

The InProcessConfiguration class defines settings for loading and instantiating Java components (like protocol adapters or targets) that run within the SFC process. It specifies the factory class responsible for creating component instances and the locations of required JAR files, supporting both individual JAR files and directories containing multiple JARs.

With the SFC uberjar every adapter, target and metrics writer is already on the classpath, so an entry only needs `FactoryClassName`; with the per-module bundles (in-process mode) it also lists the bundle's `lib` directory in `JarFiles`. See [Configure a component in each mode](../sfc-deployment.md#configuration-in-each-mode).

- [Schema](#schema)
- [Examples](#examples)

**Properties:**

- [FactoryClassName](#factoryclassname)
- [JarFiles](#jarfiles)

---
### FactoryClassName
The FactoryClassName property specifies the fully qualified name of the factory class responsible for creating instances of protocol adapters or targets. The class must have a static `newInstance(vararg createParameters: Any?)` method (in Kotlin a `@JvmStatic` function in the companion object), see [Extending the SFC Framework](../sfc-extending.md#creating-an-in-process-protocol-adapter-instance). The factory classes of the adapters and targets in this repository are listed in [Protocol adapter types and classes](../sfc-running-adapters.md#protocol-adapter-types-and-classes) and [Target types and classes](../sfc-running-targets.md#target-types-and-classes).

**Type**: String

---
### JarFiles
The JarFiles property is an array of strings that specifies the locations of JAR files containing the component implementation that the SFC core requires to load. The property accepts two types of path entries:

1. Direct JAR file paths - Paths pointing to specific JAR files
2. Directory paths - Paths to directories containing JAR files. Every `*.jar` file directly in the directory is loaded; subdirectories are not searched.

The paths of the adapter and target types that are used must exist. Relative paths are resolved against the directory SFC is started from. Prefer a placeholder for the directory where the module bundles are unpacked, for example `"JarFiles": ["${SFC_DEPLOYMENT_DIR}/opcua/lib"]`, and set the variable before starting SFC:

**Linux / macOS**

```shell
export SFC_DEPLOYMENT_DIR=/sfc
```

**Windows (PowerShell)**

```powershell
$env:SFC_DEPLOYMENT_DIR = "C:/sfc"
```

On Windows use forward slashes, in the variable and in paths in the configuration (`"C:/sfc/opcua/lib"`): a single backslash is a JSON escape, and in the `LogWriter` and `ConfigProvider` sections a backslash in the variable value breaks the configuration. How to unpack the bundles and start SFC in this mode: [In-process](../sfc-deployment.md#in-process).

This property is optional and allows for flexible JAR file organization, whether you prefer specifying individual JAR files or grouping them in directories.

If `JarFiles` is not specified, is empty or contains no JAR files, the factory class and its dependencies are loaded from the current classpath. This is how components are configured for the uberjar. Exception: a [ConfigProvider](./sfc-configuration.md#configprovider) or [LogWriter](./sfc-configuration.md#logwriter) section is ignored, without an error message, unless it contains the `JarFiles` key, so with the uberjar write `"JarFiles": []` there.

Classes that are already on the classpath of the SFC core take precedence over the classes in `JarFiles`. When SFC runs from the uberjar these are all classes bundled in it, so `JarFiles` cannot replace a bundled dependency; with `sfc-main` (in-process mode) they are only the classes in the `lib` directory of `sfc-main`. An IPC service started from its module bundle uses only the classes of that bundle.

**Type**: String[]

[^top](#inprocessconfiguration)



## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "FactoryClassName": {
      "type": "string",
      "description": "Fully qualified name of the factory class"
    },
    "JarFiles": {
      "type": "array",
      "items": {
        "type": "string",
        "description": "Path to JAR file or directory"
      },
      "description": "List of JAR files to be loaded or directories containing the JAR files"
    }
  },
  "required": [
    "FactoryClassName"
  ]
}

```

`JarFiles` is optional, except in the `ConfigProvider` and `LogWriter` sections, which are ignored without it (use `"JarFiles": []` with the uberjar).



## Examples

Uberjar, the factory class is loaded from the SFC classpath:

```json
{
  "FactoryClassName": "com.amazonaws.sfc.opcua.OpcuaAdapter"
}
```



In-process, JAR directory of the `opcua` module bundle unpacked into the directory named by `SFC_DEPLOYMENT_DIR`:

```json
{
  "FactoryClassName": "com.amazonaws.sfc.opcua.OpcuaAdapter",
  "JarFiles": [
    "${SFC_DEPLOYMENT_DIR}/opcua/lib"
  ]
}
```



Custom adapter, individual JAR files:

```json
{
  "FactoryClassName": "com.example.MyAdapter",
  "JarFiles": [
    "./adapters/my-adapter.jar",
    "./adapters/my-adapter-dependency.jar"
  ]
}
```



Uberjar, custom log writer from the [custom log writer example](../../examples/custom-log-writer/README.md), which is included in the uberjar; the `LogWriter` section needs the `JarFiles` key:

```json
"LogWriter": {
  "FactoryClassName": "com.amazonaws.sfc.log.CustomLogWriter",
  "JarFiles": []
}
```



[^top](#inprocessconfiguration)
