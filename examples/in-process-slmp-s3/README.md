# SFC Example in process configuration for Mitsubishi/Melsec SLMP to Amazon S3

[Examples](../../docs/examples/README.md)

The file [`inproc-slmp-s3.json`](inproc-slmp-s3.json) contains an example template for
reading data from a Mitsubishi controller using SLMP and
sending the data to an S3 bucket.

The configuration is split over several files, which `inproc-slmp-s3.json`
includes with [`@file:` statements](../../docs/sfc-configuration.md#file-http-https-statements):

-   `slmp-channels.json`, the channels of the source
-   `structures.json`, the custom structured types of the SLMP adapter
-   `types.json`, the `AdapterTypes` and `TargetTypes`, selected with
    `@file:types.json@Adapters` and `@file:types.json@Targets`
    ([selective inclusions](../../docs/sfc-configuration.md#selective-inclusions))
-   `templates.json`, the template for the S3 target
    ([configuration templates](../../docs/sfc-configuration.md#configuration-templates))
-   `credential-providers.json`, the AWS IoT credential provider client

The same pipeline with the adapter and the targets as IPC services:
[ipc-slmp-s3](../ipc-slmp-s3/README.md).

In order to use the configuration, make the changes described below, and
use it as the value of the `-config` parameter when starting sfc-main, as
shown under [Deployment directory](#deployment-directory).

A debug target is included in the example to optionally write the output
to the console.
&nbsp;  
&nbsp;  

## Deployment directory

The `JarFiles` entries in `types.json` use the placeholder
`${SFC_DEPLOYMENT_DIR}`, which SFC replaces with the value of the
environment variable `SFC_DEPLOYMENT_DIR`. Point it at the directory into
which you unpack the module bundles `sfc-main`, `debug-target`,
`aws-s3-target` and `slmp` of the
[latest release](https://github.com/awslabs/industrial-shopfloor-connect/releases/latest)
(for another layout, change the `JarFiles` paths). `sfc-main` needs a
Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`).
More about this mode: [In-process](../../docs/sfc-deployment.md#in-process).

Unpack the bundles, set the variable and, once you have made the changes
described below, start `sfc-main` from this example's folder. It must be
started from there, because the `@file:` paths are relative to the
directory SFC is started from:

**Linux / macOS**

```shell
export SFC_DEPLOYMENT_DIR="$HOME/sfc"
mkdir -p "$SFC_DEPLOYMENT_DIR"
for m in sfc-main debug-target aws-s3-target slmp; do
  curl -fsSL "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz" | tar -xzf - -C "$SFC_DEPLOYMENT_DIR"
done
"$SFC_DEPLOYMENT_DIR/sfc-main/bin/sfc-main" -config inproc-slmp-s3.json
```

**Windows (PowerShell)**

```powershell
$env:SFC_DEPLOYMENT_DIR = "C:/sfc"
New-Item -ItemType Directory -Force C:\sfc | Out-Null
foreach ($m in "sfc-main", "debug-target", "aws-s3-target", "slmp") {
    curl.exe -fsSL -o "C:\sfc\$m.tar.gz" "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz"
    tar -xf "C:\sfc\$m.tar.gz" -C C:\sfc
}
java -cp "C:\sfc\sfc-main\lib\*" com.amazonaws.sfc.MainController -config inproc-slmp-s3.json
```

On Windows start `sfc-main` with `java -cp` as shown, not with
`bin\sfc-main.bat` ([Platform support](../../docs/README.md#platform-support)).
With the uberjar from [sfcup](../../README.md#1-install), remove the
`JarFiles` entries from `types.json` and run `sfcx -config inproc-slmp-s3.json`.
&nbsp;  
&nbsp;


## Target section
```json
"Targets": [
  "#DebugTarget",
  "S3Target"
]
```

In order to write the data to both the S3 bucket and the console
uncomment the DebugTarget by deleting the '#'.  
&nbsp;
&nbsp;  



## S3Target 

A template S3Target is used for the actual S3 target. This template is loaded by the "Templates"  section from
the file templates.json. In the "Targets" section this template is used for the actual S3 target, passing the name of the bucket, 
the region and a prefix as parameters.

```json
"Targets": {
    "S3Target": "$(S3Target, bucket=< YOUR BUCKET >,region=< YOUR REGION >,prefix=< YOUR PREFIX >)",
    "DebugTarget": {"TargetType": "DEBUG-TARGET"}
}
```
The used template is defined in the templates.json file as:

```json
{
  "S3Target": {
    "Active": true,
    "TargetType": "AWS-S3",
    "Region": "%region%",
    "BucketName": "%bucket%",
    "Interval": 60,
    "BufferSize": 1,
    "Prefix": "%prefix%",
    "CredentialProviderClient": "AwsIotClient",
    "Compression": "Zip"
  }
}
```




The `S3Target` is set up to write data to the specified bucket once every
minute or when the data volume is 1MB in size. Zip Compression is
enabled to reduce the size of the data which is sent to and stored in
the S3 bucket, remove the "Compression" line or set to "None" to disable
compression.

`CredentialProviderClient` specifies the credentials provider which is
used to give access to the used AWS service. For more information see
section AwsIotCredentialProviderClients below.
&nbsp;  
&nbsp;  


## Sources Section

In this section, the values are defined as channels, which are read from
the controller. The channels, loaded from the file slmp-channels.json, are
examples for word (D), double word, bit (X, Y), string, array and structure
reads; see the [SLMP adapter](../../docs/adapters/slmp.md) for all device codes and data types. In order to change the name of
the value as it is included in the data which is sent to the targets,
include a setting "Name" for the channel.
&nbsp;  
&nbsp;  

## ProtocolAdapters section

```json
"ProtocolAdapters": {
  "SLMP": {
    "AdapterType": "SLMP",
    "Controllers": {
      "SLMP-CONTROLLER": {
        "Address": "< IP ADDRESS OF CONTROLLER >"
      }
    },
    "Structures": "@file:structures.json"
  }
}
```

-   \< IP ADDRESS OF CONTROLLER \>, IP address of the controller

The default SLMP port 50000 is used, which can be changed by including a
`Port` setting for the controller.

**Try it without hardware:** omni-plc-sim, the PLC simulator that
[uberjar-plc-sim-s3tables](../uberjar-plc-sim-s3tables/README.md) uses,
also serves SLMP: a simulated MELSEC iQ-R CPU on port 40000 that has every
device this configuration reads. Build and start it as in
[step 1](../uberjar-plc-sim-s3tables/README.md#1-start-the-plcs) of that
example, but with `slmp` as its only argument, then set the controller
`Address` to `127.0.0.1` and add `"Port": 40000`.

The file structures.json is loaded for the SLMP adapter, which contains the custom structured types used for the channels that are using this adapter
([Structures](../../docs/adapters/slmp.md#structures)).


&nbsp;  
&nbsp;  


## AwsIotCredentialProviderClients

The credential provider clients for this example are loaded from the file
[credential-providers.json](credential-providers.json). Its client
`AwsIotClient` obtains temporary credentials for the S3 target from the
AWS IoT credentials provider, using the certificate of a Thing in AWS IoT.
Fill in `IotCredentialEndpoint`, `RoleAlias`, `ThingName`,
`CertificateFile`, `PrivateKeyFile` and `RootCa`. On a Greengrass V2 core
device you can instead remove the `#` from `GreenGrassDeploymentPath`, set
it to the Greengrass root folder (the file has `/greengrass/v2`) and delete
the other settings. The role that `RoleAlias` points to must
allow `s3:PutObject` on the bucket. On Windows write the file paths with
forward slashes, e.g. `"C:/sfc/certs/device.crt"`.

All settings:
[AwsIotCredentialProviderClients](../../docs/core/aws-iot-credential-provider-configuration.md).
To use the AWS SDK default credentials chain instead, delete the
`AwsIotCredentialProviderClients` line from `inproc-slmp-s3.json` and the
`CredentialProviderClient` line from `templates.json`; see
[AWS service credentials](../../docs/sfc-aws-service-credentials.md). For
production environments the temporary credentials of a credential provider
client are strongly recommended.

[^top](#sfc-example-in-process-configuration-for-mitsubishimelsec-slmp-to-amazon-s3)

Docs used: [SLMP adapter and structures](../../docs/adapters/slmp.md#structures) · [S3 target](../../docs/targets/aws-s3.md) · [Debug target](../../docs/targets/debug.md) · [configuration templates](../../docs/sfc-configuration.md#configuration-templates) · [including configuration sections](../../docs/sfc-configuration.md#including-configuration-sections) · [AWS IoT credential provider](../../docs/core/aws-iot-credential-provider-configuration.md) · [In-process mode](../../docs/sfc-deployment.md#in-process) · [All examples](../../docs/examples/README.md)