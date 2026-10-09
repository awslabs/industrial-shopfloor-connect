# SFC Example IPC configuration for Beckhoff ADS to Amazon S3

The file ipc-ads-s3.json file contains an example template for reading data from a Beckhoff device using ADS over TCP/IP and sending the data to an S3 bucket. The main.tmc program file is included to declare the variables which are read from the device.

This configuration uses a deployment where each module runs as a service in an individual process and communicate using a stream over a TCP/IP connection. These processes can run on the same system or on different systems. Use cases for this type of deployment are:

-   Distributing the load of multiple adapters or targets over multiple systems

-   Run just the adapters on edge devices with limited capacity

-   Distribute components in different networks, e.g., adapters in the OT network, sfc-core in network and targets which need internet connectivity in the IT network or DMZ.

In order to use the configuration, make the changes described below, and use it as the value of the -config parameter when starting sfc-main.

A debug target is included in the example to optionally write the output to the console.

## Prerequisites

-   Java 17 or newer on every host that runs a module (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`).
-   A Beckhoff controller running the program in `main.tmc`, reachable over ADS/TCP. No device? `omni-plc-sim`, the
    simulator of the [PLC simulator example](../uberjar-plc-sim-s3tables/README.md#1-start-the-plcs), serves this
    program: build it as described there, start it in `ci/omni-plc-sim` with
    `target/release/omni-plc-sim ads --profile ads=tc3-cx8190` (Windows:
    `.\target\release\omni-plc-sim.exe ads --profile ads=tc3-cx8190`), and set the device `Address` to `127.0.0.1`
    and `TargetAmsNetId` to `5.80.201.232.1.1`.
-   An S3 bucket, and AWS credentials that may write to it: an AWS IoT thing with a role alias for the
    [AwsIotCredentialProviderClients](#awsiotcredentialproviderclients) section, or the default AWS credentials chain.

## Deployment and starting the service modules

Deploy the sfc-main, ADS adapter, S3 target and optionally the debug target: unpack the module bundles `sfc-main`,
`ads`, `aws-s3-target` and `debug-target`, for example into `~/sfc` (Windows: `C:\sfc`), with the commands under
[In-process](../../docs/sfc-deployment.md#in-process) and this list of modules. When the services run on other
systems, unpack there the bundles of the services each system runs.

Each module has a subdirectory called bin with a start script named after the module, `bin/<module>` for Linux and
macOS and `bin\<module>.bat` for Windows. On Windows start the modules with `java -cp` instead, as shown below; the
`.bat` launchers fail from longer folder paths, see [Platform support](../../docs/README.md#platform-support).

It’s recommended to first start the ADS protocol adapter and the S3 target and optionally the Debug target and specify the port number used by the module using the -port parameter.

Then start the sfc-main module and use the -config parameter to specify the name of the used config file. The port numbers in this configuration file for the adapter and target services should match with the port numbers used to start these services.

When the adapter and target services are started the services will listen on the specified port for the configuration for that service. After the sfc-main process is started, it will send the specific configuration data for each service to the configured address and port for that service. When this configuration data is received by the protocol or target service it will initialize adapters will start reading data and streaming it to the sfc-main process, and targets will receive the data from sfc-main and sending it to their destinations. When updates are made to the configuration file used by sfc-main, it will automatically load the new configuration and distribute the new configuration to the adapter. A running adapter service may keep its previous configuration though; restart it to apply a change (see the known limitations under [Adapters as IPC services](../../docs/sfc-running-adapters.md#running-the-jvm-protocol-adapters-as-an-ipc-service)).

Startup commands. When running from the console use a terminal session for every service, or run the services as
Docker containers. Start sfc-main in the folder of this example:

**Linux / macOS**

```shell
~/sfc/ads/bin/ads -port 50001
~/sfc/aws-s3-target/bin/aws-s3-target -port 50002
~/sfc/debug-target/bin/debug-target -port 50003
~/sfc/sfc-main/bin/sfc-main -config ipc-ads-s3.json
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\ads\lib\*" com.amazonaws.sfc.ads.AdsProtocolService -port 50001
java -cp "C:\sfc\aws-s3-target\lib\*" com.amazonaws.sfc.awss3.AwsS3TargetService -port 50002
java -cp "C:\sfc\debug-target\lib\*" com.amazonaws.sfc.debugtarget.DebugTargetService -port 50003
java -cp "C:\sfc\sfc-main\lib\*" com.amazonaws.sfc.MainController -config ipc-ads-s3.json
```

From an sfcup install, start the same services from the uberjar, which contains all of them, e.g.
`java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.ads.AdsProtocolService -port 50001` (Windows:
`java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.ads.AdsProtocolService -port 50001`)
with the service classes above, and the core with `sfcx -config ipc-ads-s3.json`.

> **Windows:** a service that sfc-main reaches from another system needs an inbound Windows Defender Firewall rule for
> its port, see [Platform support](../../docs/README.md#platform-support).

By default the traffic between sfc-main and the services is plain text. To encrypt the adapter traffic with TLS see
[Securing Network Traffic between SFC components](../../docs/sfc-securing-component-traffic.md); target services
currently listen in plain text only.

&nbsp;  


**Starting the ADS adapter service**

```bash
$ ads/bin/ads -port 50001

2023-11-10 17:03:17.814 INFO - Created instance of service IpcAdapterService
2023-11-10 17:03:17.815 INFO - Running service instance
2023-11-10 17:03:18.264 INFO - IPC protocol service started, listening on 192.168.1.65:50001, connection type is PlainText
```
&nbsp;
**Starting the S3 Target service**
```bash
$ aws-s3-target/bin/aws-s3-target -port 50002
2023-11-10 17:05:40.811 INFO - Created instance of service IpcTargetServer
2023-11-10 17:05:40.812 INFO - Running service instance
2023-11-10 17:05:41.417 INFO - Target IPC service started, listening on 192.168.1.65:50002, connection type is PlainText
```
&nbsp;
**Starting the (optional) Debug target service**

```bash
$ debug-target/bin/debug-target -port 50003

2023-11-10 17:08:00.866 INFO - Created instance of service IpcTargetServer
2023-11-10 17:08:00.867 INFO - Running service instance
2023-11-10 17:08:01.307 INFO - Target IPC service started, listening on 192.168.1.65:50003, connection type is PlainText
```
&nbsp;
**Starting the sfc-main service**

```bash
$ sfc-main/bin/sfc-main -config ipc-ads-s3/ipc-ads-s3.json
2023-11-10 17:22:48.230 INFO - Creating configuration provider of type ConfigProvider
2023-11-10 17:22:48.246 INFO - Waiting for configuration
2023-11-10 17:22:48.251 INFO - Sending initial configuration from file "ipc-ads-s3.json"
2023-11-10 17:22:48.816 INFO - Received configuration data from config provider
2023-11-10 17:22:48.819 INFO - Waiting for configuration
2023-11-10 17:22:48.819 INFO - Creating and starting new service instance
2023-11-10 17:22:49.03 INFO - Created instance of service MainControllerService
2023-11-10 17:22:49.03 INFO - Running service instance
2023-11-10 17:22:49.08 INFO - Creating an IPC process writer for target "DebugTarget", for server "DebugTargetServer" on server DebugTargetServer
2023-11-10 17:22:49.12 INFO - Creating an IPC process writer for target "S3Target", for server "S3TargetServer" on server S3TargetServer
2023-11-10 17:22:49.13 INFO - Creating client to connect to IPC service localhost:50002 using connection type PlainText
2023-11-10 17:22:49.13 INFO - Creating client to connect to IPC service localhost:50003 using connection type PlainText
2023-11-10 17:22:49.18 INFO - No adapter or target metrics are collected
2023-11-10 17:22:49.19 INFO - Initializing IPC source adapter service on localhost:50001
2023-11-10 17:22:49.19 INFO - Creating client to connect to IPC service localhost:50001 using connection type PlainText
2023-11-10 17:22:49.150 INFO - Initializing IPC target service for "DebugTarget" on server localhost:50003
2023-11-10 17:22:49.151 INFO - Initializing IPC target service for "S3Target" on server localhost:50002
2023-11-10 17:22:49.154 INFO - Sending configuration “{ EDITED }" to target "DebugTarget"
2023-11-10 17:22:49.169 INFO - Sending configuration “{ EDITED }" to target "S3Target"
2023-11-10 17:22:49.226 INFO - IPC server for target "S3Target" initialized
2023-11-10 17:22:49.226 INFO - IPC server for target "DebugTarget" initialized
2023-11-10 17:22:49.440 INFO - IPC source service adapter for server localhost:50001 initialized
```

## Configuring the Protocol Adapter as a service

To communicate with the protocol adapter as a service add the “AdapterServer” item to the configuration for the adapter. The value must be set to a server in the “AdapterServers” section of the configuration.
```json
"ProtocolAdapters": {  
    "ADS": {  
        "AdapterType": "ADS",
        "AdapterServer": "AdsAdapterServer"
    }
}
```

In the AdapterServers section the address (localhost or address of other system) and port number of the server are specified. The sfc-core will use these to communicate with the adapter service.

**IMPORTANT: The port number specified in the configuration must match with the port number specified with the -port parameter used to start the adapter service.**

```json
 "AdapterServers": {  
     "AdsAdapterServer": {  
         "Address": "localhost",  
         "Port": 50001  
     }  
 }
```

## Configuring the targets as a service

To communicate with the targets as a service add the “TargetServer” item to the configuration for the target. The value must be set to a server in the “TargetServers” section of the configuration.

```json
"S3Target": {
    "TargetServer": "S3TargetServer",
    "TargetType": "AWS-S3"
}
```

In the TargetServers section the address (localhost or address of other system) and port number of the server are specified. The sfc-core will use these to communicate with the target service.

IMPORTANT: The port numbers specified in the configuration must match with the port numbers specified with the -port parameters used to start the target services.

```json
"TargetServers": {  
    "S3TargetServer": {  
        "Address": "localhost",  
        "Port": 50002  
    },  
    "DebugTargetServer": {  
        "Address": "localhost",  
        "Port": 50003  
    }  
}
```

In order to write the data to both the S3 bucket and the console, remove the '#' from "#DebugTarget" in the schedule's
`Targets` and ensure the debug target service (server `DebugTargetServer`) is started.

## S3Target section

```json
"S3Target": {
    "TargetServer": "S3TargetServer",  
    "Active": true,  
    "TargetType": "AWS-S3",  
    "Region": "<YOUR-REGION>",  
    "BucketName": "<YOUR-BUCKET-NAME>",  
    "Interval": 60,  
    "BufferSize": 1,  
    "Prefix": "<OPTIONAL PREFIX TO USE IN BUCKET>",  
    "CredentialProviderClient": "AwsIotClient",  
    "Compression": "Zip"  
}
```

-   `<YOUR-REGION>`, your region e.g., eu-west-1
-   `<YOUR-BUCKET-NAME>`, bucket name to store data
-    < OPTIONAL PREFIX TO USE IN BUCKET>, Optional prefix for data in
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
the device. In this template there is an example for every
data type supported by the adapter, declared as a variable/symbol in the MAIN section. 
It also includes symbols for system variables and constants set by the device.

In order to change the name of
the value as it is included in the data which is sent to the targets,
include a setting "Name" for the channel.

The source also addresses the device in the ADS network: set `SourceAmsNetId` to the AMS NetId of SFC and
`TargetAmsNetId` to that of the device. SFC only requires that `SourceAmsPort` is set (32905 is set), and
`TargetAmsPort` 851 is the first TwinCAT 3 PLC runtime. See the [ADS adapter](../../docs/adapters/ads.md) for all settings.
&nbsp;  
&nbsp;

## ProtocolAdapters section

```json
  "ProtocolAdapters":{
      "ADS":{
          "AdapterType":"ADS",
          "AdapterServer":"AdsAdapterServer",
          "Devices":{
              "CX8190":{
                  "Address":"<IP ADDRESS OF BECKHOFF DEVICE>", 
                  "Port":48898
              }
          }
      }
}

```


-   `<IP ADDRESS OF BECKHOFF DEVICE>`, IP address of the device

This section configures the device from which the data is read. The
default port 48898 is used which can be changed by Including a Port
setting specifying that value.

&nbsp;  
&nbsp;


## AwsIotCredentialProviderClients

This section configures one or more clients which can be referred to by
targets which need access to AWS services.

A credential provider will make use of the AWS IoT Credentials service
to obtain temporary credentials. This process is described at
<https://aws.amazon.com/blogs/security/how-to-eliminate-the-need-for-hardcoded-aws-credentials-in-devices-by-using-the-aws-iot-credentials-provider/>

The resources used in the configuration can easily be setup by creating
a Thing in the AWS IoT service. The role that `RoleAlias` points to, must
give access to the services used by the target which uses the client.

```json
"AwsIotCredentialProviderClients" : {
  "AwsIotClient": {
    "IotCredentialEndpoint": "<ID>.credentials.iot.<YOUR REGION>.amazonaws.com",
    "RoleAlias": "< ROLE EXCHANGE ALIAS >",
    "ThingName": "< THING NAME > ",
    "CertificateFile": "< PATH TO DEVICE CERTIFICATE .crt FILE >",
    "PrivateKeyFile": "< PATH TO PRIVATE KEY .key FILE >",
    "RootCa": "< PATH TO ROOT CERTIFICATE .pem FILE >"
  }
}
```

On Windows write these paths with forward slashes, e.g. `"CertificateFile": "C:/sfc/certs/device.crt"`; a single
backslash starts a JSON escape sequence.


If there is a GreenGrass V2 deployment on the same machine, instead of
all settings a setting named GreenGrassDeploymentPath can be used to
point to that deployment. SFC will use the GreenGrass V2 configurations
setting. Specific setting can be overridden by setting a value for that
setting, which will replace the value from the GreenGrass V2
Configuration. Note that although SFC can be deployed as a GreenGrass
component, it can also run as a standalone process or in a docker
container and still use a GreenGrass configuration.
&nbsp;  
&nbsp;


```json
"AwsIotCredentialProviderClients": {
  "AwsIotClient": {
    "GreenGrassDeploymentPath": "<GREENGRASS DEPLOYMENT DIR>/v2"
  }
}
```

The Greengrass V2 deployment directory is `/greengrass/v2` on Linux by default (Windows: `"C:/greengrass/v2"`).

When the AWS service credentials are provided using one of the options
in the AWS SDK credentials provider chain
(<https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/credentials-chain.html>)
AwsIotCredentialProviderClients and any references in the targets can be
deleted. Using the temporary credentials provided through a configured
AwsIotCredentialProviderClient for production environment is strongly
recommended.

Docs used: [ADS adapter](../../docs/adapters/ads.md) · [S3 target](../../docs/targets/aws-s3.md) · [Debug target](../../docs/targets/debug.md) · [IPC mode](../../docs/sfc-deployment.md#ipc) · [Adapters as IPC services](../../docs/sfc-running-adapters.md#running-the-jvm-protocol-adapters-as-an-ipc-service) · [Targets as IPC services](../../docs/sfc-running-targets.md#running-targets-as-an-ipc-service) · [Server configuration](../../docs/core/server-configuration.md) · [AWS IoT credential provider](../../docs/core/aws-iot-credential-provider-configuration.md) · [All examples](../../docs/examples/README.md)
