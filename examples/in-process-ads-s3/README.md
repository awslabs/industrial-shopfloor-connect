# SFC Example in process configuration for Beckhoff ADS to Amazon S3

The file `in-process-ads-s3.json` contains an example template for
reading data from a Beckhoff controller using ADS over TCP/IP and
sending the data to an S3 bucket.

The main.tmc program file is included to declare the variables which are read from the device.

The same pipeline with the adapter and the targets as IPC services:
[ipc-ads-s3](../ipc-ads-s3/README.md).


In order to use the configuration, make the changes described below, and
use it as the value of the `-config` parameter when starting sfc-main, as
shown under [Deployment directory](#deployment-directory).

A debug target is included in the example to optionally write the output
to the console.
&nbsp;  
&nbsp;  

## Deployment directory

The `JarFiles` entries of the configuration use the placeholder
`${SFC_DEPLOYMENT_DIR}`, which SFC replaces with the value of the
environment variable `SFC_DEPLOYMENT_DIR`. Point it at the directory into
which you unpack the module bundles `sfc-main`, `debug-target`,
`aws-s3-target` and `ads` of the
[latest release](https://github.com/awslabs/industrial-shopfloor-connect/releases/latest)
(for another layout, change the `JarFiles` paths). `sfc-main` needs a
Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`).
More about this mode: [In-process](../../docs/sfc-deployment.md#in-process).

Unpack the bundles, set the variable and, once you have made the changes
described below, start `sfc-main` from this example's folder:

**Linux / macOS**

```shell
export SFC_DEPLOYMENT_DIR="$HOME/sfc"
mkdir -p "$SFC_DEPLOYMENT_DIR"
for m in sfc-main debug-target aws-s3-target ads; do
  curl -fsSL "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz" | tar -xzf - -C "$SFC_DEPLOYMENT_DIR"
done
"$SFC_DEPLOYMENT_DIR/sfc-main/bin/sfc-main" -config in-process-ads-s3.json
```

**Windows (PowerShell)**

```powershell
$env:SFC_DEPLOYMENT_DIR = "C:/sfc"
New-Item -ItemType Directory -Force C:\sfc | Out-Null
foreach ($m in "sfc-main", "debug-target", "aws-s3-target", "ads") {
    curl.exe -fsSL -o "C:\sfc\$m.tar.gz" "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz"
    tar -xf "C:\sfc\$m.tar.gz" -C C:\sfc
}
java -cp "C:\sfc\sfc-main\lib\*" com.amazonaws.sfc.MainController -config in-process-ads-s3.json
```

On Windows start `sfc-main` with `java -cp` as shown, not with
`bin\sfc-main.bat` ([Platform support](../../docs/README.md#platform-support)).
With the uberjar from [sfcup](../../README.md#1-install), remove the
`JarFiles` entries and run `sfcx -config in-process-ads-s3.json`.
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



## S3Target section

```json
"S3Target": {
  "Active": true,
  "TargetType": "AWS-S3",
  "Region": "< YOUR-REGION >",
  "BucketName": "< YOUR-BUCKET-NAME >",
  "Interval": 60,
  "BufferSize": 1,
  "Prefix": "< OPTIONAL PREFIX TO USE IN BUCKET >",
  "CredentialProviderClient": "AwsIotClient",
  "Compression": "Zip"
}

```

-   < YOUR-REGION >, your region e.g., eu-west-1

-   < YOUR-BUCKET-NAME >, bucket name to store data

-   < OPTIONAL PREFIX TO USE IN BUCKET >, Optional prefix for data in
    the bucket

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
the controller. In this template there is a channel for every variable
declared in main.tmc, plus TwinCAT system symbols. In order to change the name of
the value as it is included in the data which is sent to the targets,
include a setting "Name" for the channel.

Set `SourceAmsNetId` and `SourceAmsPort` to the AMS address of SFC: for a
client the NetId is typically the IP address of the SFC host followed by
`.1.1`; the port only has to be set, this example uses `32905`. Set
`TargetAmsNetId` to the AMS NetId of the PLC and `TargetAmsPort` to the AMS
port of its PLC runtime (`851` for the first TwinCAT 3 runtime). To
authorize SFC as a client, add its `SourceAmsNetId` as an AMS route under
SYSTEM > Routes on the TwinCAT target. Details:
[AdsSourceConfiguration](../../docs/adapters/ads.md#adssourceconfiguration).
&nbsp;  
&nbsp;  

## ProtocolAdapters section

```json
"ProtocolAdapters": {
    "ADS": {
        "AdapterType": "ADS",
        "Devices": {
            "CX8190": {
                "Address": "<DEVICE IP ADDRESS>"
            }
        }
    }
}
```

-   \<DEVICE IP ADDRESS\>, IP address of the controller

This section configures the controller from which the data is read. The
default port 48898 is used which can be changed by Including a Port
setting specifying that value.

**Try it without hardware:** omni-plc-sim, the PLC simulator that
[uberjar-plc-sim-s3tables](../uberjar-plc-sim-s3tables/README.md) uses,
simulates a TwinCAT 3 runtime that serves every symbol this configuration
reads. Start it as in [step 1](../uberjar-plc-sim-s3tables/README.md#1-start-the-plcs)
of that example, then set `Address` to `127.0.0.1`, `TargetAmsNetId` to
`192.168.100.10.1.1` and `TargetAmsPort` to `851`.
&nbsp;  
&nbsp;  


## AwsIotCredentialProviderClients

The client `AwsIotClient` in this section obtains temporary credentials for
the S3 target from the AWS IoT credentials provider, using the certificate
of a Thing in AWS IoT. Fill in `IotCredentialEndpoint`, `RoleAlias`,
`ThingName`, `CertificateFile`, `PrivateKeyFile` and `RootCa`. On a
Greengrass V2 core device you can instead remove the `#` from
`GreenGrassDeploymentPath`, set it to the Greengrass root folder, e.g.
`/greengrass/v2`, and delete the other settings. The role that
`RoleAlias` points to must allow `s3:PutObject` on the bucket. On Windows
write the file paths with forward slashes, e.g. `"C:/sfc/certs/device.crt"`.

All settings:
[AwsIotCredentialProviderClients](../../docs/core/aws-iot-credential-provider-configuration.md).
To use the AWS SDK default credentials chain instead, delete this section
and the target's `CredentialProviderClient`; see
[AWS service credentials](../../docs/sfc-aws-service-credentials.md). For
production environments the temporary credentials of a credential provider
client are strongly recommended.

Docs used: [ADS adapter](../../docs/adapters/ads.md) · [S3 target](../../docs/targets/aws-s3.md) · [Debug target](../../docs/targets/debug.md) · [AWS service credentials](../../docs/sfc-aws-service-credentials.md) · [In-process mode](../../docs/sfc-deployment.md#in-process) · [All examples](../../docs/examples/README.md)