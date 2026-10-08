# SFC Example custom config provider for YAML

This is an example of a custom config provider allowing the use of YAML SFC configuration files.

The initial SFC configuration file passed to SFC ([config.json](./config.json)) only contains the configuration for the
custom provider and the name of the actual YAML configuration file.

```json
{ 
    "AWSVersion": "2022-04-02",
    "Name": "Configuration using custom YAML configurations",
    "ConfigProvider": {
        "JarFiles": ["${SFC_DEPLOYMENT_DIR}/yaml-custom-config-provider/lib"],
        "FactoryClassName": "com.amazonaws.sfc.config.YamlConfigProvider"
    },
    "YamlConfigFile" : "examples/yaml-custom-config-provider/config.yaml"
}
```

SFC will load the custom config provider which will read the configuration from the specified YAML file, convert it to
JSON and pass it to SFC-Core. The provider will also detect updates to the YAML config file.

[config.yaml](./config.yaml) reads an OPC-UA server and writes to AWS IoT Core, Amazon S3 and the console. Both files
are in-process configurations: the provider, the adapter and the targets are loaded from the module bundles in the
directory that `SFC_DEPLOYMENT_DIR` names. The provider is also part of the uberjar.

## Before you run

Replace these values in config.yaml:

- `Address: opc.tcp://sfc-server` and `Path: OPCUA/SimulationServer`: your OPC-UA server (the adapter's default port is
  53530). The node IDs under `Channels` are those of the Prosys OPC UA Simulation Server.
- `TopicName`, `Region` and `BucketName`: your AWS IoT Core topic, AWS Region and S3 bucket.
- `AwsIotCredentialProviderClients`: the `IotCredentialEndpoint`, `RoleAlias` and `ThingName` of your AWS IoT thing,
  and the paths of its certificate, private key and root CA in `CertificateFile`, `PrivateKeyFile` and `RootCa`; see
  [AWS IoT credential provider](../../docs/core/aws-iot-credential-provider-configuration.md).

On Windows, write paths in config.yaml with forward slashes, e.g. `CertificateFile: "C:/sfc/cert/certificate.crt"`; in
a double-quoted YAML string a backslash starts an escape sequence.

## Run it

The `YamlConfigFile` path in config.json is relative to the root of this repository, so start SFC there.

**Uberjar**: installed by [sfcup](../../README.md#1-install). Change the `JarFiles` entry in config.json to
`"JarFiles": []` (SFC ignores a `ConfigProvider` section without the key) and delete the `JarFiles` entries in
config.yaml. Then start SFC (the same command in Windows PowerShell):

```shell
sfcx -config examples/yaml-custom-config-provider/config.json -info
```

**In-process**: unpack the module bundles `sfc-main`, `yaml-custom-config-provider`, `opcua`, `aws-iot-core-target`,
`aws-s3-target` and `debug-target` of the
[latest release](https://github.com/awslabs/industrial-shopfloor-connect/releases/latest) into one directory, point
`SFC_DEPLOYMENT_DIR` at it and start `sfc-main`, which needs a Java 17 (or newer) runtime (Windows:
`winget install EclipseAdoptium.Temurin.17.JDK`). More about this mode:
[In-process](../../docs/sfc-deployment.md#in-process).

**Linux / macOS**

```shell
export SFC_DEPLOYMENT_DIR="$HOME/sfc"
mkdir -p "$SFC_DEPLOYMENT_DIR"
for m in sfc-main yaml-custom-config-provider opcua aws-iot-core-target aws-s3-target debug-target; do
  curl -fsSL "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz" | tar -xzf - -C "$SFC_DEPLOYMENT_DIR"
done
"$SFC_DEPLOYMENT_DIR/sfc-main/bin/sfc-main" -config examples/yaml-custom-config-provider/config.json -info
```

**Windows (PowerShell)**

Give `SFC_DEPLOYMENT_DIR` forward slashes: SFC inserts the value into the JSON text as it is, so a backslash breaks
the JSON.
Start `sfc-main` with `java -cp`, not with `bin\sfc-main.bat` ([Platform support](../../docs/README.md#platform-support)):

```powershell
$env:SFC_DEPLOYMENT_DIR = "C:/sfc"
New-Item -ItemType Directory -Force C:\sfc | Out-Null
foreach ($m in "sfc-main", "yaml-custom-config-provider", "opcua", "aws-iot-core-target", "aws-s3-target", "debug-target") {
    curl.exe -fsSL -o "C:\sfc\$m.tar.gz" "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz"
    tar -xf "C:\sfc\$m.tar.gz" -C C:\sfc
}
java -cp "C:\sfc\sfc-main\lib\*" com.amazonaws.sfc.MainController -config examples/yaml-custom-config-provider/config.json -info
```

The provider logs `Converting YAML from <path>/config.yaml to JSON` and `Sending initial configuration to SFC-Core`.
After you save a change to config.yaml it logs `YAML config file updated` and `Sending updated configuration to
SFC-Core`. Stop SFC with `Ctrl-C`.

Docs used: [OPC-UA adapter](../../docs/adapters/opcua.md) · [AWS IoT Core target](../../docs/targets/aws-iot-core.md) · [AWS S3 target](../../docs/targets/aws-s3.md) · [Debug target](../../docs/targets/debug.md) · [AWS IoT credential provider](../../docs/core/aws-iot-credential-provider-configuration.md) · [ConfigProvider](../../docs/core/sfc-configuration.md#configprovider) · [Custom configuration handlers](../../docs/sfc-extending.md#custom-configuration-handlers) · [All examples](../../docs/examples/README.md)
