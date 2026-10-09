# Running SFC targets

- [Target types and classes](#target-types-and-classes)
- [Running targets as an IPC Service](#running-targets-as-an-ipc-service)
- [Running targets in-process](#running-targets-in-process)

## Target types and classes

Every target has a fixed type code. `TargetType` must be set to that code in every deployment mode, and in the uberjar
and in-process modes the `TargetTypes` key is the same code. The module is the name of the target's release bundle
(`<module>.tar.gz`), of its `JarFiles` directory (`${SFC_DEPLOYMENT_DIR}/<module>/lib`) and of its IPC launcher
(`<module>/bin/<module>`). How the three modes use these values:
[Configure a component in each mode](./sfc-deployment.md#configuration-in-each-mode).

| Target                                                     | TargetType                | Module                        | FactoryClassName                                               | IPC service class                                               |
|------------------------------------------------------------|---------------------------|-------------------------------|----------------------------------------------------------------|-----------------------------------------------------------------|
| [AWS IoT Core](./targets/aws-iot-core.md)                  | `AWS-IOT-CORE`            | `aws-iot-core-target`         | `com.amazonaws.sfc.awsiotcore.AwsIotCoreTargetWriter`          | `com.amazonaws.sfc.awsiotcore.AwsIotCoreTargetService`          |
| [AWS Kinesis Firehose](./targets/aws-kinesis-firehose.md)  | `AWS-FIREHOSE`            | `aws-kinesis-firehose-target` | `com.amazonaws.sfc.awsfirehose.AwsKinesisFirehoseTargetWriter` | `com.amazonaws.sfc.awsfirehose.AwsKinesisFirehoseTargetService` |
| [AWS Kinesis](./targets/aws-kinesis.md)                    | `AWS-KINESIS`             | `aws-kinesis-target`          | `com.amazonaws.sfc.awskinesis.AwsKinesisTargetWriter`          | `com.amazonaws.sfc.awskinesis.AwsKinesisTargetService`          |
| [AWS Lambda](./targets/aws-lambda.md)                      | `AWS-LAMBDA`              | `aws-lambda-target`           | `com.amazonaws.sfc.awslambda.AwsLambdaTargetWriter`            | `com.amazonaws.sfc.awslambda.AwsLambdaTargetService`            |
| [AWS MSK](./targets/aws-msk.md)                            | `AWS-MSK`                 | `aws-msk-target`              | `com.amazonaws.sfc.awsmsk.AwsMskTargetWriter`                  | `com.amazonaws.sfc.awsmsk.AwsMskTargetService`                  |
| [AWS S3](./targets/aws-s3.md)                              | `AWS-S3`                  | `aws-s3-target`               | `com.amazonaws.sfc.awss3.AwsS3TargetWriter`                    | `com.amazonaws.sfc.awss3.AwsS3TargetService`                    |
| [AWS S3 Tables](./targets/aws-s3-tables.md)                | `AWS-S3-TABLES`           | `aws-s3-tables-target`        | `com.amazonaws.sfc.awss3tables.AwsS3TablesTargetWriter`        | `com.amazonaws.sfc.awss3tables.AwsS3TablesTargetService`        |
| [AWS SiteWise](./targets/aws-sitewise.md)                  | `AWS-SITEWISE`            | `aws-sitewise-target`         | `com.amazonaws.sfc.awssitewise.AwsSiteWiseTargetWriter`        | `com.amazonaws.sfc.awssitewise.AwsSitewiseTargetService`        |
| [AWS SiteWise Edge](./targets/aws-sitewiseedge.md)         | `AWS-SITEWISEEDGE-TARGET` | `aws-sitewiseedge-target`     | `com.amazonaws.sfc.awssitewiseedge.SiteWiseEdgeTargetWriter`   | `com.amazonaws.sfc.awssitewiseedge.SiteWiseEdgeTargetService`   |
| [AWS SNS](./targets/aws-sns.md)                            | `AWS-SNS`                 | `aws-sns-target`              | `com.amazonaws.sfc.awssns.AwsSnsTargetWriter`                  | `com.amazonaws.sfc.awssns.AwsSnsTargetService`                  |
| [AWS SQS](./targets/aws-sqs.md)                            | `AWS-SQS`                 | `aws-sqs-target`              | `com.amazonaws.sfc.awssqs.AwsSqsTargetWriter`                  | `com.amazonaws.sfc.awssqs.AwsSqsTargetService`                  |
| [Debug](./targets/debug.md)                                | `DEBUG-TARGET`            | `debug-target`                | `com.amazonaws.sfc.debugtarget.DebugTargetWriter`              | `com.amazonaws.sfc.debugtarget.DebugTargetService`              |
| [File](./targets/file.md)                                  | `FILE-TARGET`             | `file-target`                 | `com.amazonaws.sfc.filetarget.FileTargetWriter`                | `com.amazonaws.sfc.filetarget.FileTargetService`                |
| [MQTT](./targets/mqtt.md)                                  | `MQTT-TARGET`             | `mqtt-target`                 | `com.amazonaws.sfc.mqtt.MqttTargetWriter`                      | `com.amazonaws.sfc.mqtt.MqttTargetService`                      |
| [NATS](./targets/nats.md)                                  | `NATS-TARGET`             | `nats-target`                 | `com.amazonaws.sfc.natstarget.NatsTargetWriter`                | `com.amazonaws.sfc.natstarget.NatsTargetService`                |
| [OPC UA](./targets/opcua.md)                               | `OPCUA-TARGET`            | `opcua-target`                | `com.amazonaws.sfc.opcuatarget.OpcuaTargetWriter`              | `com.amazonaws.sfc.opcuatarget.OpcuaTargetService`              |
| [OPC UA Writer](./targets/opcua-writer.md)                 | `OPCUA-WRITER-TARGET`     | `opcua-writer-target`         | `com.amazonaws.sfc.opcuawritetarget.OpcuaTargetWriter`         | `com.amazonaws.sfc.opcuawritetarget.OpcuaWriterTargetService`   |
| [Router](./targets/router.md)                              | `ROUTER`                  | `router-target`               | `com.amazonaws.sfc.router.RouterTargetWriter`                  | `com.amazonaws.sfc.router.AwsRouterTargetService`               |
| [Store and forward](./targets/store-and-forward-target.md) | `STORE-FORWARD`           | `store-forward-target`        | `com.amazonaws.sfc.storeforward.StoreForwardTargetWriter`      | `com.amazonaws.sfc.storeforward.AwsStoreForwardTargetService`   |

The [AWS CloudWatch metrics writer](./metrics/aws-cloudwatch.md) is not a target and has no type code; it is configured
under `Metrics.Writer`. Its module is `aws-cloudwatch-metrics`, its FactoryClassName
`com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriter` and its IPC service class
`com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriterService`.

## Running targets as an IPC Service

Targets have a service wrapper that enables these targets to be executed as an IPC Service process. For each target, a
tar file (`<module>.tar.gz`) is generated by the build process that includes the application script files to start the
service, as well as all required library files. The script files are named after the module, not the target type
(`<module>/bin/<module>` *and* `<module>/bin/<module>.bat`, e.g. `aws-s3-target/bin/aws-s3-target` for `AWS-S3`), and the
libraries are in `<module>/lib/*.jar`. The module and the IPC service class of every target are listed in
[Target types and classes](#target-types-and-classes).

Start the service before SFC, on the port of its `TargetServers` entry, e.g. for the debug target:

**Linux / macOS**

```shell
tar -xzf debug-target.tar.gz
debug-target/bin/debug-target -port 50001
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force C:\sfc | Out-Null
tar -xf debug-target.tar.gz -C C:\sfc
java -cp "C:\sfc\debug-target\lib\*" com.amazonaws.sfc.debugtarget.DebugTargetService -port 50001
```

On Windows start target services with `java -cp` and the bundle's `lib\*`, not with `bin\<module>.bat`; see
[Platform support](./README.md#platform-support).

Any target service can also be started from the uberjar, which contains all of them. From an sfcup install:
`java -cp "$HOME/.sfc/current/lib/*" <IPC service class> -port 50001` (Windows:
`java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" <IPC service class> -port 50001`).

In the SFC configuration an IPC target keeps its `TargetType` and names its server in `TargetServer`. The server is
defined under `TargetServers`, and no `TargetTypes` entry is needed:

```json
"Targets": {
  "DebugTarget": {
    "TargetType": "DEBUG-TARGET",
    "TargetServer": "DebugTargetServer"
  }
},
"TargetServers": {
  "DebugTargetServer": { "Address": "localhost", "Port": 50001 }
}
```

A service listens only on the address its host name resolves to, or on that of the interface given with `-interface`,
which is not necessarily `127.0.0.1`. In `Address` use that address, or `localhost`, which SFC also resolves to the
address of the host name. All server settings: [ServerConfiguration](./core/server-configuration.md).

The applications have the following command line parameters in common.

| Parameter   | Description                                                                                                                                                                                                                                                                                                                                                                                          |
|-------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| -config     | Name of an SFC configuration file. The service listens on the `Port` of the `TargetServers` entry that its target names in `TargetServer`; missing `-cert` and `-key` values are also taken from that entry. The configuration of the target itself always comes from the SFC core, which sends an initialization request with it to the service on this port.                                       |
| -connection | Connection type: PlainText, ServerSideTLS or MutualTLS. Target services currently accept the option but always use PlainText, see the known limitations below.                                                                                                                                                                                                                                       |
| -cert       | Server certificate file to secure IPC (gRPC) traffic for connection types ServerSideTLS and MutualTLS                                                                                                                                                                                                                                                                                                |
| -key        | Server private key file to secure IPC (gRPC) traffic for connection types ServerSideTLS and MutualTLS                                                                                                                                                                                                                                                                                                |
| -ca         | CA certificate file to secure IPC (gRPC) traffic for connection type MutualTLS                                                                                                                                                                                                                                                                                                                       |
| -interface  | Name or display name of the network interface whose IPv4 address the service listens on (e.g., en0). Default: the address the host name resolves to.                                                                                                                                                                                                                                                |
| -envport    | The name of the environment variable that contains the port number for the service to listen on for requests.                                                                                                                                                                                                                                                                                        |
| -error      | Set log output level to error level. (Error message only)                                                                                                                                                                                                                                                                                                                                            |
| -h, -help   | Shows command line parameter help.                                                                                                                                                                                                                                                                                                                                                                   |
| -info       | Set log output level to info level. (Info, warning and error messages)                                                                                                                                                                                                                                                                                                                               |
| -nocolor    | Disable color coded output to console.                                                                                                                                                                                                                                                                                                                                                               |
| -port       | port number for the service to listen on for requests.                                                                                                                                                                                                                                                                                                                                               |
| -target     | Key of the `Targets` entry this service runs. Needed with `-config` when the file contains more than one active target; when it is set, the service accepts only the configuration of this target from the SFC core.                                                                                                                                                                              |
| -trace      | Set log output level to most detailed trace level (Info, warning, error, and detailed trace messages)                                                                                                                                                                                                                                                                                                |
| -warning    | Set log output level to warning level. (Error and warning messages)                                                                                                                                                                                                                                                                                                                                  |

Give exactly one of `-port`, `-envport` or `-config`: they are mutually exclusive, and a service started with two of them
stops with a command line error. With `-config` the port of the target's server is used. As a configuration can contain
multiple targets the following methods are used to determine the target.

- The value of the -target command line parameter
- If the configuration file contains a single active target then that target is used

Put `-config` before the other parameters, e.g. `debug-target/bin/debug-target -config sfc.json -target DebugTarget -info`;
a parameter placed in front of `-config` currently hides it.

**Known limitations**

- Target services always listen in plain text. They accept `-connection`, `-cert`, `-key` and `-ca` (with `-config`,
  missing `-cert` and `-key` values are read from `ServerCertificate` and `ServerPrivateKey` of the target's
  `TargetServers` entry), but do not use them. Keep `ConnectionType` at `PlainText`, the default, for `TargetServers`
  entries; only adapter services support ServerSideTLS and MutualTLS, see
  [Securing Network Traffic between SFC components](./sfc-securing-component-traffic.md).
- A top-level `ElementNames` mapping is not passed to target services; they write the default element names.

**Examples:** [OPC-UA to MSK](../examples/ipc-opcua-msk/README.md), [ADS to S3](../examples/ipc-ads-s3/README.md) and
[SLMP to S3](../examples/ipc-slmp-s3/README.md) run their targets as IPC services. All targets: [Target Adapters](./targets/README.md).
All examples: [examples catalog](./examples/README.md).


## Running targets in-process

To run targets in the same process as the SFC core, they need to be implemented for the same JDK as used for the core.
To make it possible to add a new target without making changes to the SFC code, there are no links in the core to the
libraries that implement the target. In the configuration of an in-process target type, the pathnames of the jar files
that contain the classes that implement the target need to be explicitly configured. When the SFC core creates an
instance of the target, it loads the configured jar files and uses a static factory method to create the actual
instance. The name of the factory class, which could be the actual target class itself, needs to be configured as well.

The jar files are part of the target deployment and can be found in the lib directory of the deployment package. To
specify the path to the jar files it is recommended to use a placeholder, instead of hard-coding, the directory where
the adapter, and targets, are deployed and set an environment variable for this directory.

**Example configurations for in-process targets configuration with environment variable placeholders:**

- Used environment variable is `SFC_DEPLOYMENT_DIR`: Directory in which the deployment packages are unpacked, with a
  subdirectory, named after its module, for each target.
- Configuration is using the debug, AWS IoT Core and MQTT targets

**Linux / macOS**

```shell
export SFC_DEPLOYMENT_DIR=/sfc
```

**Windows (PowerShell)**

```powershell
$env:SFC_DEPLOYMENT_DIR = "C:/sfc"
```

```json
"TargetTypes": {
  "DEBUG-TARGET": {
    "JarFiles": [
      "${SFC_DEPLOYMENT_DIR}/debug-target/lib"
    ],
    "FactoryClassName": "com.amazonaws.sfc.debugtarget.DebugTargetWriter"
  },
  "AWS-IOT-CORE": {
    "JarFiles": [
      "${SFC_DEPLOYMENT_DIR}/aws-iot-core-target/lib"
    ],
    "FactoryClassName": "com.amazonaws.sfc.awsiotcore.AwsIotCoreTargetWriter"
  },
  "MQTT-TARGET": {
    "JarFiles": [
      "${SFC_DEPLOYMENT_DIR}/mqtt-target/lib"
    ],
    "FactoryClassName": "com.amazonaws.sfc.mqtt.MqttTargetWriter"
  }
}
```

The uberjar already contains every target, so when SFC runs from the uberjar the same entries name only the
`FactoryClassName`; see [Configure a component in each mode](./sfc-deployment.md#configuration-in-each-mode).

**Examples:** [Simulator to S3 Tables](../examples/in-process-sim-s3tables/README.md) and
[ADS to S3](../examples/in-process-ads-s3/README.md).
All examples: [examples catalog](./examples/README.md).
