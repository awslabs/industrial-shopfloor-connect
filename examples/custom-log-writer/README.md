# Custom Log Writer

Template for a [custom log writer](../../docs/sfc-extending.md#custom-logging).
`com.amazonaws.sfc.log.CustomLogWriter` replaces SFC's console writer and prints every log entry to standard output as
`<date and time> <LEVEL>- [<source>] : <message>`.

## Use it

The class is part of the uberjar installed by [sfcup](../../README.md#1-install). Add this section at the top level of
a configuration, for example the [Quickstart `simulator.json`](../../README.md#2-first-data--no-hardware-no-cloud):

```json
"LogWriter": {
  "JarFiles": [],
  "FactoryClassName": "com.amazonaws.sfc.log.CustomLogWriter"
}
```

Keep the empty `JarFiles` list: SFC ignores a `LogWriter` section without it and keeps its console writer. Then start
SFC (the same command in Windows PowerShell):

```shell
sfcx -config simulator.json -info
```

To build your own writer, copy this folder, for example to `examples/my-log-writer`, and give the package and the
class your own names: when SFC runs from the uberjar, a class with the name of one in the uberjar is never loaded from
`JarFiles`. Build it from the repository root:

**Linux / macOS**

```shell
./gradlew :examples:my-log-writer:build
```

**Windows (PowerShell)**

```powershell
.\gradlew.bat :examples:my-log-writer:build
```

Then set `"JarFiles": ["examples/my-log-writer/build/libs"]` and your class in `FactoryClassName`, and start SFC from
the repository root; relative paths resolve against the directory SFC is started from. More in
[Loading extensions](../../docs/sfc-extending.md#loading-extensions).

Docs used: [Custom logging](../../docs/sfc-extending.md#custom-logging) · [LogWriter](../../docs/core/sfc-configuration.md#logwriter) · [Logging](../../docs/sfc-logging-metrics.md#logging) · [All examples](../../docs/examples/README.md)
