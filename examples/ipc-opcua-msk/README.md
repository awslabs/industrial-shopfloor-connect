# SFC Example IPC configuration for OPCUA to AWS MSK

The file ipc-opcua-msk.json file contains an example template for reading data from an OPCUA server and sending the 
data to an AWS MSK topic.

The AWS MSK target is a target adapter optimized to write data to AWS Managed Kafka, using
AWS_MSK_IAM for authorization and authentication, for which it can use the SFC functionality to
use X.509 certificates to obtain the credentials to access the service.

This configuration uses a deployment where each module runs as a service in an individual process and communicate using a stream over a TCP/IP connection. These processes can run on the same system or on different systems. Use cases for this type of deployment are:

-   Distributing the load of multiple adapters or targets over multiple systems

-   Run just the adapters on edge devices with limited capacity

-   Distribute components in different networks, e.g., adapters in the OT network, sfc-core in network and targets which need internet connectivity in the IT network or DMZ.

In order to use the configuration, make the changes described below, and use it as the value of the -config parameter when starting sfc-main.

A debug target is included in the example to optionally write the output to the console.

## Prerequisites

-   Java 17 or newer on every host that runs a module (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`).
-   A Prosys OPC UA Simulation Server at `opc.tcp://localhost:53530/OPCUA/SimulationServer`, whose node IDs the
    channels read.
-   An Amazon MSK cluster with IAM access control and public access (brokers on port 9198), a topic, and AWS
    credentials that may write to it: the default AWS credentials chain, or the
    [AwsIotCredentialProviderClients](#awsiotcredentialproviderclients) section.

## Deployment and starting the service modules

Deploy the sfc-main, OPCUA adapter, MSK target and optionally the debug target: unpack the module bundles `sfc-main`,
`opcua`, `aws-msk-target` and `debug-target`, for example into `~/sfc` (Windows: `C:\sfc`), with the commands under
[In-process](../../docs/sfc-deployment.md#in-process) and this list of modules. When the services run on other
systems, unpack there the bundles of the services each system runs.

Each module has a subdirectory called bin with a start script named after the module, `bin/<module>` for Linux and
macOS and `bin\<module>.bat` for Windows. On Windows start the modules with `java -cp` instead, as shown below; the
`.bat` launchers fail from longer folder paths, see [Platform support](../../docs/README.md#platform-support).

It’s recommended to first start the OPCUA protocol adapter and the MSK target and optionally the Debug target and specify the port number used by the module using the -port parameter.

Then start the sfc-main module and use the -config parameter to specify the name of the used config file. The port numbers in this configuration file for the adapter and target services should match with the port numbers used to start these services.

When the adapter and target services are started the services will listen on the specified port for the configuration for that service. After the sfc-main process is started, it will send the specific configuration data for each service to the configured address and port for that service. When this configuration data is received by the protocol or target service it will initialize adapters will start reading data and streaming it to the sfc-main process, and targets will receive the data from sfc-main and sending it to their destinations. When updates are made to the configuration file used by sfc-main, it will automatically load the new configuration and distribute the new configuration to the adapter. A running adapter service may keep its previous configuration though; restart it to apply a change (see the known limitations under [Adapters as IPC services](../../docs/sfc-running-adapters.md#running-the-jvm-protocol-adapters-as-an-ipc-service)).

Startup commands. When running from the console use a terminal session for every service, or run the services as
Docker containers. Start sfc-main in the folder of this example:

**Linux / macOS**

```shell
~/sfc/opcua/bin/opcua -port 50000
~/sfc/debug-target/bin/debug-target -port 50001
~/sfc/aws-msk-target/bin/aws-msk-target -port 50002
~/sfc/sfc-main/bin/sfc-main -config ipc-opcua-msk.json
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\opcua\lib\*" com.amazonaws.sfc.opcua.OpcuaProtocolService -port 50000
java -cp "C:\sfc\debug-target\lib\*" com.amazonaws.sfc.debugtarget.DebugTargetService -port 50001
java -cp "C:\sfc\aws-msk-target\lib\*" com.amazonaws.sfc.awsmsk.AwsMskTargetService -port 50002
java -cp "C:\sfc\sfc-main\lib\*" com.amazonaws.sfc.MainController -config ipc-opcua-msk.json
```

From an sfcup install, start the same services from the uberjar, which contains all of them, e.g.
`java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.opcua.OpcuaProtocolService -port 50000` (Windows:
`java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.opcua.OpcuaProtocolService -port 50000`)
with the service classes above, and the core with `sfcx -config ipc-opcua-msk.json`.

> **Windows:** a service that sfc-main reaches from another system needs an inbound Windows Defender Firewall rule for
> its port, see [Platform support](../../docs/README.md#platform-support).

By default the traffic between sfc-main and the services is plain text. To encrypt the adapter traffic with TLS see
[Securing Network Traffic between SFC components](../../docs/sfc-securing-component-traffic.md); target services
currently listen in plain text only.

&nbsp;  


**Starting the OPCUA adapter service**

```bash
$ opcua/bin/opcua -port 50000

2024-02-15 17:35:01.739 INFO  - Created instance of service IpcAdapterService
2024-02-15 17:35:01.739 INFO  - Running service instance
2024-02-15 17:35:02.326 INFO  - IPC protocol service started, listening on 192.168.1.65:50000, connection type is PlainText
```
&nbsp;
**Starting the MSK Target service**
```bash
$ aws-msk-target/bin/aws-msk-target -port 50002

2024-02-15 17:37:33.227 INFO  - Created instance of service IpcTargetServer
2024-02-15 17:37:33.228 INFO  - Running service instance
2024-02-15 17:37:33.655 INFO  - Target IPC service started, listening on  192.168.1.65:50002, connection type is PlainText

```
&nbsp;
**Starting the (optional) Debug target service**

```bash
$ debug-target/bin/debug-target -port 50001

2024-02-15 17:38:34.61  INFO  - Created instance of service IpcTargetServer
2024-02-15 17:38:34.62  INFO  - Running service instance
2024-02-15 17:38:34.494 INFO  - Target IPC service started, listening on  192.168.1.65:50001, connection type is PlainText
```
&nbsp;
**Starting the sfc-main service**

```bash
sfc-main/bin/sfc-main -config "ipc-opcua-msk.json"

2024-02-15 17:41:54.51  INFO  - Creating configuration provider of type ConfigProvider
2024-02-15 17:41:54.62  INFO  - Waiting for configuration
2024-02-15 17:41:54.65  INFO  - Sending initial configuration from file "ipc-opcua-msk.json"
2024-02-15 17:41:54.577 INFO  - Received configuration data from config provider
2024-02-15 17:41:54.578 INFO  - Waiting for configuration
2024-02-15 17:41:54.579 INFO  - Creating and starting new service instance
2024-02-15 17:41:54.744 INFO  - Created instance of service MainControllerService
2024-02-15 17:41:54.744 INFO  - Running service instance
2024-02-15 17:41:54.748 INFO  - Creating an IPC process writer for target "DebugTarget", for server "DebugTargetServer" on server DebugTargetServer
2024-02-15 17:41:54.751 INFO  - Creating an IPC process writer for target "MskTarget", for server "MskTargetServer" on server MskTargetServer
2024-02-15 17:41:54.752 INFO  - Creating client to connect to IPC service localhost:50002 using connection type PlainText
2024-02-15 17:41:54.752 INFO  - Creating client to connect to IPC service localhost:50001 using connection type PlainText
2024-02-15 17:41:54.756 INFO  - No adapter or target metrics are collected
2024-02-15 17:41:54.757 INFO  - Initializing IPC source adapter service on localhost:50000
2024-02-15 17:41:54.757 INFO  - Creating client to connect to IPC service localhost:50000 using connection type PlainText
2024-02-15 17:41:54.861 INFO  - Initializing IPC target service  for  "DebugTarget" on server localhost:50001
2024-02-15 17:41:54.861 INFO  - Initializing IPC target service  for  "MskTarget" on server localhost:50002
2024-02-15 17:41:54.866 INFO  - Sending configuration "{ ...EDITED... }" to target "DebugTarget"
2024-02-15 17:41:54.880 INFO  - Sending configuration "{ ...EDITED... }" to target "MskTarget"
2024-02-15 17:41:54.934 INFO  - IPC server for target "DebugTarget" initialized
2024-02-15 17:41:54.934 INFO  - IPC server for target "MskTarget" initialized
2024-02-15 17:41:55.749 INFO  - IPC source service adapter for server localhost:50000 initialized
```

## Configuring the Protocol Adapter as a service

To communicate with the protocol adapter as a service add the “AdapterServer” item to the configuration for the adapter. The value must be set to a server in the “AdapterServers” section of the configuration.
```json
"ProtocolAdapters": {  
    "OPC-UA": {  
        "AdapterType": "OPCUA",
        "AdapterServer": "OpcuaAdapterServer"
    }
}
```

In the AdapterServers section the address (localhost or address of other system) and port number of the server are specified. The sfc-core will use these to communicate with the adapter service.

**IMPORTANT: The port number specified in the configuration must match with the port number specified with the -port parameter used to start the adapter service.**

```json
 "AdapterServers": {  
     "OpcuaAdapterServer": {  
         "Address": "localhost",  
         "Port": 50000  
     }  
 }
```

## Configuring the targets as a service

To communicate with the targets as a service add the “TargetServer” item to the configuration for the target. The value must be set to a server in the “TargetServers” section of the configuration.

```json
"MskTarget": {
    "TargetServer": "MskTargetServer",
    "TargetType": "AWS-MSK"
}
```

In the TargetServers section the address (localhost or address of other system) and port number of the server are specified. The sfc-core will use these to communicate with the target service.

IMPORTANT: The port numbers specified in the configuration must match with the port numbers specified with the -port parameters used to start the target services.

```json
"TargetServers": {  
    "DebugTargetServer": {  
        "Address": "localhost",  
        "Port": 50001  
    },  
    "MskTargetServer": {  
        "Address": "localhost",  
        "Port": 50002  
    }  
}
```


## Target section
```json
"Targets": [
  "#DebugTarget",
  "MskTarget"
]
```

These are the targets of the schedule. In order to write the data to both the MSK topic and the console
uncomment the DebugTarget by deleting the '#', and start the debug target service.  

## MSK target section

```json

"MskTarget": {
    "Active": true,
    "TargetServer": "MskTargetServer",
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

-   < HOSTNAME-1 > to < HOSTNAME-3 >, host names for the MSK brokers

-   < TOPIC >, name of the MSK topic. Note that the role that is used by the referred CredentialProviderClient, or the credentials provided by the default credentials chain, must allow the required permission to write data to this topic

-   < KEY >, optional key for the written records

    &nbsp;
-   `Interval` makes the target flush the producer every 1000 ms. Keep it set: without it every written record logs
    an error, although the data is delivered (see [Interval](../../docs/targets/aws-msk.md#interval)).
-   `Compression` is set to gzip
-   `Serialization` is set to JSON (other option is protobuf)
-   `Acknowledgements` is set to "all" (other options are "leader" and "none")
-  `CredentialProviderClient` is not set, so the default credentials chain is used
   (https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/credentials-chain.html). To obtain the
   credentials with X.509 certificates instead, add the section AwsIotCredentialProviderClients below and set
   `"CredentialProviderClient": "AwsIotClient"` in the target.
   Note that the used role/credentials must allow writing to the configured topic.

See the [AWS MSK target](../../docs/targets/aws-msk.md) documentation for all available settings and values.
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

The sources section configures an OPCUA source (the configuration file has more channels). It is set up to use the OPC-UA adapter (`"OPC-UA"`) to read in
subscription mode from the server `"OPCUA-SERVER"` defined in that adapter. The nodes/events from which to read
data from are defined in the channels for this source. These channels contain the NodeId and an optional name to explicitly set the name of the value in the output data.
## ProtocolAdapters section

```json
"ProtocolAdapters": {
  "OPC-UA": {
    "AdapterType": "OPCUA",
    "AdapterServer": "OpcuaAdapterServer",
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
simulation server. The type of the source ("OPC-UA") and the actual server ("OPCUA-SERVER") are referred by the OPCUA source ("OPCUA-SOURCE").
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
    "GreenGrassDeploymentPath": "< GREENGRASS DEPLOYMENT DIR >/v2"
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

Docs used: [OPC UA adapter](../../docs/adapters/opcua.md#opcua-alarm-and-event-types) · [AWS MSK target](../../docs/targets/aws-msk.md) · [Debug target](../../docs/targets/debug.md) · [IPC mode](../../docs/sfc-deployment.md#ipc) · [Adapters as IPC services](../../docs/sfc-running-adapters.md#running-the-jvm-protocol-adapters-as-an-ipc-service) · [Targets as IPC services](../../docs/sfc-running-targets.md#running-targets-as-an-ipc-service) · [Server configuration](../../docs/core/server-configuration.md) · [All examples](../../docs/examples/README.md)
