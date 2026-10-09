# SFC Example in process configuration for OPCUA to AWS MSK

The file `in-process-opcua-msk.json` contains an example template for
reading data from an OPCUA server and sending the data to an AWS MSK topic. Both the adapter 
and targets are configured to run in the sfc-main process. 

> **Known limitation:** in-process, this pipeline does not deliver data today. When `sfc-main` loads the MSK target
> from its `JarFiles`, the target's IAM authentication classes are loaded from the libraries of `sfc-main`, which do
> not contain the Kafka client, so the first record fails with a `NoClassDefFoundError` and nothing is written to the
> topic. Run the same pipeline over IPC with [ipc-opcua-msk](../ipc-opcua-msk/README.md), or run this configuration
> from the uberjar as described under [Deployment directory](#deployment-directory).

The AWS MSK target is a target adapter optimized to write data to AWS Managed Kafka, using
AWS_MSK_IAM for authorization and authentication, for which it can use the SFC functionality to
use X.509 certificates to obtain the credentials to access the service.

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
`aws-msk-target` and `opcua` of the
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
for m in sfc-main debug-target aws-msk-target opcua; do
  curl -fsSL "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz" | tar -xzf - -C "$SFC_DEPLOYMENT_DIR"
done
"$SFC_DEPLOYMENT_DIR/sfc-main/bin/sfc-main" -config in-process-opcua-msk.json
```

**Windows (PowerShell)**

```powershell
$env:SFC_DEPLOYMENT_DIR = "C:/sfc"
New-Item -ItemType Directory -Force C:\sfc | Out-Null
foreach ($m in "sfc-main", "debug-target", "aws-msk-target", "opcua") {
    curl.exe -fsSL -o "C:\sfc\$m.tar.gz" "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz"
    tar -xf "C:\sfc\$m.tar.gz" -C C:\sfc
}
java -cp "C:\sfc\sfc-main\lib\*" com.amazonaws.sfc.MainController -config in-process-opcua-msk.json
```

On Windows start `sfc-main` with `java -cp` as shown, not with
`bin\sfc-main.bat` ([Platform support](../../docs/README.md#platform-support)).
With the uberjar from [sfcup](../../README.md#1-install), remove the
`JarFiles` entries and run `sfcx -config in-process-opcua-msk.json`; the
uberjar contains the Kafka client, so the known limitation above does not
apply there.
&nbsp;  

## Target section
```json
"Targets": [
  "#DebugTarget",
  "MskTarget"
]
```

In order to write the data to both the MSK topic and the console
uncomment the DebugTarget by deleting the '#'.  
&nbsp;
&nbsp;  


## MSK target section

```json

"MskTarget": {
    "CredentialProviderClient": "AwsIotClient",
    "TargetType": "AWS-MSK",
    "BootstrapBrokers": [
        "< HOSTNAME-1 >:9198",
        "< HOSTNAME-2 >:9198",
        "< HOSTNAME-3 >:9198"
    ],
    "TopicName": "< TOPIC >",
    "Key": "< KEY >",
    "Interval": 1000,
    "Compression": "gzip",
    "Serialization": "json",
    "Acknowledgements": "all"
}


```
&nbsp;
-   < HOSTNAME-1 > ... < HOSTNAME-3 >, host names for the MSK brokers

-   < TOPIC >, name of the MSK topic. Note that the role that is used by the referred CredentialProviderClient, or the credentials provided by the default credentials chain, must allow the required permission to write data to this topic

-   < KEY >, optional key for the written records

    &nbsp;
-   `Interval` is the interval in milliseconds in which the target flushes the producer
-   `Compression` is set to gzip
-   `Serialization` is set to JSON (other option is protobuf)
-   `Acknowledgements` is set to "all" (other options are "leader" and "none")
-  `CredentialProviderClient` specifies the credentials provider which is
  used to give access to the used AWS service. For more information see
  section AwsIotCredentialProviderClients below. If this element is not set then
  the default credentials chain is used. (https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/credentials-chain.html)
  Note that the used role/credentials must allow writing to the configured topic.

Port 9198 is the port of an MSK cluster's public endpoints with IAM
authentication; `aws kafka get-bootstrap-brokers --cluster-arn <CLUSTER ARN>`
lists them as `BootstrapBrokerStringPublicSaslIam`. The topic must exist,
unless the cluster creates topics automatically. The IAM permissions,
including `kafka-cluster:WriteDataIdempotently` for `Acknowledgements`
"all", are listed in the [AWS MSK target](../../docs/targets/aws-msk.md#awsmsktargetconfiguration)
documentation.

See the [AWS MSK target](../../docs/targets/aws-msk.md) for all available settings and values of the AWS MSK target.
&nbsp;
## Sources section

```json
"Sources": {
    "OPCUA-SOURCE": {
      "Name": "OPCUA-SOURCE",
      "ProtocolAdapter": "OPC-UA",
      "AdapterOpcuaServer": "OPCUA-SERVER",
      "Description": "OPCUA local server",
      "SourceReadingMode": "Subscription",
      "Channels": {
        "LevelAlarm": {
          "Name": "LevelAlarm",
          "NodeId": "ns=6;s=MyLevel.Alarm",
          "EventType": "ExclusiveLevelAlarmType"
        },
        "ServerStatus": {
          "Name": "ServerStatus",
          "NodeId": "ns=0;i=2256"
        },
        "SimulationCounter": {
          "Name": "Counter",
          "NodeId": "ns=3;i=1001"
        }
      }
    }
}
```

The sources section configures an OPCUA source (the snippet shows its first channels). It is set up to use the
protocol adapter `"OPC-UA"` (adapter type `"OPCUA"`) to read in 
subscription mode from the server `"OPCUA-SERVER"` defined in that adapter. The nodes/events from which to read 
data from are defined in the channels for this source. These channels contain the NodeId and an optional name to explicitly set the name of the value in the output data.
The `LevelAlarm` channel reads alarm events, see
[OPC UA alarm and event types](../../docs/adapters/opcua.md#opcua-alarm-and-event-types).

## ProtocolAdapters section

```json
"ProtocolAdapters": {
  "OPC-UA": {
    "AdapterType": "OPCUA",
    "OpcuaServers": {
      "OPCUA-SERVER": {
        "Address": "opc.tcp://localhost",
        "Path": "OPCUA/SimulationServer",
        "Port": 53530
      }
    }
  }
}
```

This section contains a single OPCUA adapter from which the data is read. It is set up to read from a local OPCUA 
simulation server, a Prosys OPC UA Simulation Server at `opc.tcp://localhost:53530/OPCUA/SimulationServer`, whose
nodes the channels read; for another server change `Address`, `Path` and `Port` and the NodeIds of the channels.
The protocol adapter ("OPC-UA") and the server ("OPCUA-SERVER") are referred to by the source ("OPCUA-SOURCE").
&nbsp;
## TargetTypes section

```json
 "TargetTypes": {
    "DEBUG-TARGET": {
      "JarFiles": [
        "${SFC_DEPLOYMENT_DIR}/debug-target/lib"
      ],
      "FactoryClassName": "com.amazonaws.sfc.debugtarget.DebugTargetWriter"
    },
    "AWS-MSK": {
      "JarFiles": [
        "${SFC_DEPLOYMENT_DIR}/aws-msk-target/lib"
      ],
      "FactoryClassName": "com.amazonaws.sfc.awsmsk.AwsMskTargetWriter"
    }
  }
```


This section configured the target types loaded by the SFC main process. The `JarFiles` setting includes the location where the 
jar files which implement the target, are located. The `FactoryClassName` is used by SFC to create instances of the target.
The names `DEBUG-TARGET` and `AWS-MSK` are used in the `TargetType` setting of the targets.

```json
"AdapterTypes": {
    "OPCUA": {
      "JarFiles": [
        "${SFC_DEPLOYMENT_DIR}/opcua/lib"
      ],
      "FactoryClassName": "com.amazonaws.sfc.opcua.OpcuaAdapter"
    }
  }
```

This section configured the adapters types loaded by the SFC main process. The `JarFiles` setting includes the location where the
jar files which implement the adapter, are located. The `FactoryClassName` is used by SFC to create instances of the adapters.
The name `OPCUA` is used in the `AdapterType` setting of the `OPC-UA` protocol adapter.

## AwsIotCredentialProviderClients

The client `AwsIotClient` in this section obtains temporary credentials for
the MSK target from the AWS IoT credentials provider, using the certificate
of a Thing in AWS IoT. Fill in `IotCredentialEndpoint`, `RoleAlias`,
`ThingName`, `CertificateFile`, `PrivateKeyFile` and `RootCa`. On a
Greengrass V2 core device you can instead remove the `#` from
`GreenGrassDeploymentPath`, set it to the Greengrass root folder, e.g.
`/greengrass/v2`, and delete the other settings. The role that
`RoleAlias` points to must allow the MSK permissions named above. On
Windows write the file paths with forward slashes, e.g.
`"C:/sfc/certs/device.crt"`.

All settings:
[AwsIotCredentialProviderClients](../../docs/core/aws-iot-credential-provider-configuration.md).
To use the AWS SDK default credentials chain instead, delete this section
and the target's `CredentialProviderClient`; see
[AWS service credentials](../../docs/sfc-aws-service-credentials.md). For
production environments the temporary credentials of a credential provider
client are strongly recommended.

Docs used: [OPC UA adapter: alarm and event types](../../docs/adapters/opcua.md#opcua-alarm-and-event-types) · [AWS MSK target](../../docs/targets/aws-msk.md) · [Debug target](../../docs/targets/debug.md) · [AWS service credentials](../../docs/sfc-aws-service-credentials.md) · [In-process mode](../../docs/sfc-deployment.md#in-process) · [All examples](../../docs/examples/README.md)