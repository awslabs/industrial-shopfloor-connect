# Custom Target Formatter

Sample Kotlin Project for a [custom target formatter](../../docs/sfc-extending.md#custom-formatters).
`com.amazonaws.sfc.formatter.CustomTargetFormatter` writes each target data record as the current UTC time followed by
the record, `<yyyy-MM-dd HH:mm:ss.SSS> TargetData(...)`; the records of a batch are joined without a separator.

## Use it

The class is part of the uberjar installed by [sfcup](../../README.md#1-install), so `FactoryClassName` is all the
[Formatter](../../docs/core/target-configuration.md#formatter) of a target needs. For example, in the `Targets`
section of the [Quickstart `simulator.json`](../../README.md#2-first-data--no-hardware-no-cloud):

```json
"Targets": {
  "DebugTarget": {
    "Active": true,
    "TargetType": "DEBUG-TARGET",
    "Formatter": { "FactoryClassName": "com.amazonaws.sfc.formatter.CustomTargetFormatter" }
  }
}
```

Then start SFC (the same command in Windows PowerShell):

```shell
sfcx -config simulator.json -info
```

A target takes a `Formatter` or a [Template](../../docs/core/target-configuration.md#template), not both. The targets
that apply a formatter are listed under [Custom formatters](../../docs/sfc-extending.md#custom-formatters).

To build your own formatter, copy this folder, for example to `examples/my-target-formatter`, and give the package and
the class your own names: when SFC runs from the uberjar, a class with the name of one in the uberjar is never loaded
from `JarFiles`. Build it from the repository root:

**Linux / macOS**

```shell
./gradlew :examples:my-target-formatter:build
```

**Windows (PowerShell)**

```powershell
.\gradlew.bat :examples:my-target-formatter:build
```

Then add `"JarFiles": ["examples/my-target-formatter/build/libs"]` to the `Formatter`, set your class in
`FactoryClassName`, and start SFC from the repository root; relative paths resolve against the directory SFC is
started from. More in [Loading extensions](../../docs/sfc-extending.md#loading-extensions).

Docs used: [Custom formatters](../../docs/sfc-extending.md#custom-formatters) · [Formatter](../../docs/core/target-configuration.md#formatter) · [Loading extensions](../../docs/sfc-extending.md#loading-extensions) · [All examples](../../docs/examples/README.md)
