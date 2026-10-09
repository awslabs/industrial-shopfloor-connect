# SFC Example in process configuration for Rockwell PCCC to Amazon S3

The file `in-process-pccc-s3.json` contains an example template for
reading data from a Rockwell controller using PCCC over EthernetIP and
sending the data to an S3 bucket.

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
`aws-s3-target` and `pccc` of the
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
for m in sfc-main debug-target aws-s3-target pccc; do
  curl -fsSL "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz" | tar -xzf - -C "$SFC_DEPLOYMENT_DIR"
done
"$SFC_DEPLOYMENT_DIR/sfc-main/bin/sfc-main" -config in-process-pccc-s3.json
```

**Windows (PowerShell)**

```powershell
$env:SFC_DEPLOYMENT_DIR = "C:/sfc"
New-Item -ItemType Directory -Force C:\sfc | Out-Null
foreach ($m in "sfc-main", "debug-target", "aws-s3-target", "pccc") {
    curl.exe -fsSL -o "C:\sfc\$m.tar.gz" "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz"
    tar -xf "C:\sfc\$m.tar.gz" -C C:\sfc
}
java -cp "C:\sfc\sfc-main\lib\*" com.amazonaws.sfc.MainController -config in-process-pccc-s3.json
```

On Windows start `sfc-main` with `java -cp` as shown, not with
`bin\sfc-main.bat` ([Platform support](../../docs/README.md#platform-support)).
With the uberjar from [sfcup](../../README.md#1-install), remove the
`JarFiles` entries and run `sfcx -config in-process-pccc-s3.json`.
&nbsp;  
&nbsp;


## Target section
```json
"Targets": [
  "#DebugTarget",
  "S3Target"
]
```

In order to write the data to both the S3 bucket as well as the console
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
the controller. In this template there is an example for every
data file type supported by the adapter except S (status). In order to change the name of
the value as it is included in the data which is sent to the targets,
include a setting "Name" for the channel. The address forms are explained in
[PCCC addressing](../../docs/adapters/pccc.md#pccc-addressing).

On the controller, the data files O0, I1, N7 and F8 must have 2 or more
elements, and the data files ST9, L10 and A11 must be created, each with at
least 2 elements. The channels that read O0 and I1 with a word offset or an
array length (`O0:0.1`, `O0:0,2`, `I1:0.1`) are affected by the known
limitation described there; disable a channel by putting a `#` in front
of its name.
&nbsp;  
&nbsp;  

## ProtocolAdapters section

```json
"ProtocolAdapters": {
  "PCCC": {
    "AdapterType": "PCCC",
    "Controllers": {
      "MicroLogix1400": {
        "Address": "<CONTROLLER IP ADDRESS>",
        "OptimizeReads": true

      }
    }
  }
}

```

-   \<CONTROLLER IP ADDRESS\>, IP address of the controller

This section configures the controller from which the data is read. The
default port 44818 is used which can be changed by Including a Port
setting specifying that value.

OptimizeReads is set to true to allow the adapter to combine reads from
the controller.

**Try it without hardware:** omni-plc-sim, the PLC simulator that
[uberjar-plc-sim-s3tables](../uberjar-plc-sim-s3tables/README.md) uses,
simulates a MicroLogix 1400 that holds every data file and element this
configuration reads. Start it as in [step 1](../uberjar-plc-sim-s3tables/README.md#1-start-the-plcs)
of that example, then set the controller `Address` to `127.0.0.1`.
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

Docs used: [PCCC adapter and addressing](../../docs/adapters/pccc.md#pccc-addressing) · [S3 target](../../docs/targets/aws-s3.md) · [Debug target](../../docs/targets/debug.md) · [AWS service credentials](../../docs/sfc-aws-service-credentials.md) · [In-process mode](../../docs/sfc-deployment.md#in-process) · [All examples](../../docs/examples/README.md)