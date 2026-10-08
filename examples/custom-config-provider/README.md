# Custom Config provider

Template for a custom [configuration provider](../../docs/sfc-extending.md#custom-configuration-handlers).
`com.amazonaws.sfc.config.CustomConfigProvider` passes on the configuration SFC was started with and sends it again
every 60 seconds; when SFC runs with `-verify`, it checks the signature first. Every configuration a provider sends
restarts the SFC pipeline, so this template restarts it every minute. A real provider should send a configuration only
when it has changed.

## Use it

The class is part of the uberjar installed by [sfcup](../../README.md#1-install). Add this section at the top level of
a configuration, for example the [Quickstart `simulator.json`](../../README.md#2-first-data--no-hardware-no-cloud):

```json
"ConfigProvider": {
  "JarFiles": [],
  "FactoryClassName": "com.amazonaws.sfc.config.CustomConfigProvider"
}
```

Keep the empty `JarFiles` list: SFC ignores a `ConfigProvider` section without it. Then start SFC (the same command in
Windows PowerShell):

```shell
sfcx -config simulator.json -info
```

To build your own provider, copy this folder, for example to `examples/my-config-provider`, and give the package and
the class your own names: when SFC runs from the uberjar, a class with the name of one in the uberjar is never loaded
from `JarFiles`. Build it from the repository root:

**Linux / macOS**

```shell
./gradlew :examples:my-config-provider:build
```

**Windows (PowerShell)**

```powershell
.\gradlew.bat :examples:my-config-provider:build
```

Then set `"JarFiles": ["examples/my-config-provider/build/libs"]` and your class in `FactoryClassName`, and start SFC
from the repository root; relative paths resolve against the directory SFC is started from. More in
[Loading extensions](../../docs/sfc-extending.md#loading-extensions).

Docs used: [Custom configuration handlers](../../docs/sfc-extending.md#custom-configuration-handlers) · [ConfigProvider](../../docs/core/sfc-configuration.md#configprovider) · [Loading extensions](../../docs/sfc-extending.md#loading-extensions) · [All examples](../../docs/examples/README.md)
