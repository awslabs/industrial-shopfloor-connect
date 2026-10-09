# Running the SFC core process

The main class for running the SFC core process is `com.amazonaws.sfc.MainController`. It is started with one of two
launchers, which take the same command-line arguments:

- `sfcx`, the uberjar launcher installed by [sfcup](../README.md#1-install). The uberjar is described in
  [Single file deployments](./sfc-deployment.md#single-file-deployments).
- `sfc-main/bin/sfc-main`, from the per-module bundle `sfc-main.tar.gz`, a release asset. A source build
  (`./gradlew build`) collects it, with all other bundles, in `build/distribution/`. The sfc-main.tar.gz file contains
  script files (**bin/sfc-main** and **bin/sfc-main.bat**) to launch the application, and all required libraries
  (`lib/*.jar`).

Both need a Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`).

**Linux / macOS**

```shell
sfcx -config example.json                     # uberjar, installed by sfcup
sfc-main/bin/sfc-main -config example.json    # per-module bundle
```

**Windows (PowerShell)**

```powershell
sfcx -config example.json                                                                 # uberjar, installed by sfcup
java -cp "C:\sfc\sfc-main\lib\*" com.amazonaws.sfc.MainController -config example.json   # per-module bundle
```

On Windows start the per-module core with `java -cp` and the bundle's `lib\*` (here unpacked in `C:\sfc`), not with
`bin\sfc-main.bat`; see [Platform support](./README.md#platform-support).

`sfcx` and `sfc-main` have the following command-line arguments:

| Parameter   | Description                                                                                                                                   |
|-------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| -config     | Name of SFC configuration file.                                                                                                               |
| -verify     | Pathname of file containing the public key to verify the digital signature of the configuration passed to the sfc core by the config handler. |
| -h, -help   | Shows command line parameter help.                                                                                                            |
| -error      | Set log output level to error level. (Error message only)                                                                                     |
| -info       | Set log output level to info level. (Info, warning and error messages)                                                                        |
| -nocolor    | Disable color coded output to console. (Console output is never color coded on Windows.)                                                      |
| -trace      | Set log output level to most detailed trace level (Info, warning, error, and detailed trace messages)                                         |
| -warning    | Set log output level to warning level. (Error and warning messages)                                                                           |

Put `-config` and `-verify` before the other arguments, e.g. `sfcx -config example.json -info`; an argument placed in
front of them currently hides them.

## Additional functionality to specify the config via environment variables

If you don't specify the `-config` parameter SFC will check the environment variable `SFC_CONFIG` if it exists and holds
a json configuration. This helps in environment where even default configuration is not passed as a file (e.g. in an AWS
IoT Greengrass component). To verify the signature of a configuration passed this way, set `SFC_CONFIG_VERIFY` to the
text of the public key (the PEM content, not a file name), the counterpart of `-verify`.

**Linux / macOS**

```shell
SFC_CONFIG="$(cat example.json)" sfcx -info
```

**Windows (PowerShell)**

```powershell
$env:SFC_CONFIG = Get-Content -Raw example.json
sfcx -info
```

## Running the process from a single jar file

The uberjar, its launchers and how its configuration differs are described in
[Single file deployments](./sfc-deployment.md#single-file-deployments): components inside the uberjar are named by their
`FactoryClassName` alone, and only `ConfigProvider` and `LogWriter` sections keep an empty `"JarFiles": []`.
