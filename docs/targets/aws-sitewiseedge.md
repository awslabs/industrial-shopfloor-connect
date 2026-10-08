
# AWS SiteWise Edge Target

The AWS IoT [SiteWise Edge](https://aws.amazon.com/iot-sitewise/sitewise-edge/) target adapter for Shop Floor Connectivity (SFC) enables data transfer from industrial equipment to AWS IoT SiteWise Edge gateways running on-premises.

## Deploy this target

`TargetType` is `AWS-SITEWISEEDGE-TARGET` in every deployment mode. In the uberjar and in-process modes the `TargetTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode). All types and classes: [Target types and classes](../sfc-running-targets.md#target-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"TargetTypes": {
  "AWS-SITEWISEEDGE-TARGET": { "FactoryClassName": "com.amazonaws.sfc.awssitewiseedge.SiteWiseEdgeTargetWriter" }
}
```

**In-process** - module bundle `aws-sitewiseedge-target` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"TargetTypes": {
  "AWS-SITEWISEEDGE-TARGET": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/aws-sitewiseedge-target/lib"],
    "FactoryClassName": "com.amazonaws.sfc.awssitewiseedge.SiteWiseEdgeTargetWriter"
  }
}
```

**IPC** - no `TargetTypes`; the target runs as its own service:

```json
"Targets": {
  "SiteWiseEdgeTarget": {
    "TargetType": "AWS-SITEWISEEDGE-TARGET",
    "TargetServer": "SiteWiseEdgeServer"
  }
},
"TargetServers": {
  "SiteWiseEdgeServer": { "Address": "localhost", "Port": 50001 }
}
```

Start the service before SFC, on the port of its `TargetServers` entry:

**Linux / macOS**

```shell
aws-sitewiseedge-target/bin/aws-sitewiseedge-target -port 50001
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\aws-sitewiseedge-target\lib\*" com.amazonaws.sfc.awssitewiseedge.SiteWiseEdgeTargetService -port 50001
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.awssitewiseedge.SiteWiseEdgeTargetService -port 50001` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.awssitewiseedge.SiteWiseEdgeTargetService -port 50001`).

**Examples:** in-process: [in-process-opcua-sitewiseedge](../../examples/in-process-opcua-sitewiseedge/README.md) · all: [examples catalog](../examples/README.md)

## SiteWiseEdgeTargetConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [Targets](../core/sfc-configuration.md#targets) >  [Target](../core/target-configuration.md) 

The `AWS-SITEWISEEDGE-TARGET` is a specific type of target configuration in SFC that allows you to connect and send data to an MQTT topic consumed by the AWS IoT SiteWise Edge service. The `Targets` configuration element can contain entries of this type, and the `TargetType` of these entries must be set to `"AWS-SITEWISEEDGE-TARGET"`.
This type extends the type  [TargetConfiguration](../core/target-configuration.md) with specific configuration data for this adapter.
This target adapter follows the Time Quality Value (TQV) schema for ingesting data into SiteWise Edge. For a better understanding of the TQV schema, please refer to the [Ingest data using the AWS IoT SiteWise API](https://docs.aws.amazon.com/iot-sitewise/latest/userguide/ingest-api.html) documentation.

**Prerequisite:** every schedule that feeds this target must set [`"TimestampLevel"`](../core/schedule-configuration.md#timestamplevel) to `"Channel"` or `"Both"`. Each TQV value needs a channel timestamp; without one the values of that source are not sent and the target logs "Error getting asset for source".

- [Schema](#sitewiseedgetargetconfiguration-schema)
- [Examples](#sitewiseedgetargetconfiguration-examples)


**Properties:**
- [BatchCount](#batchcount)
- [BatchInterval](#batchinterval)
- [BatchSize](#batchsize)
- [Certificate](#certificate)
- [ClientName](#clientname)
- [ConnectRetries](#connectretries)
- [ConnectTimeout](#connecttimeout)
- [EndPoint](#endpoint)
- [Password](#password)
- [Port](#port)
- [PrivateKey](#privatekey)
- [PublishTimeout](#publishtimeout)
- [RootCA](#rootca)
- [SslServerCertificate](#sslservercertificate)
- [TopicName](#topicname)
- [Username](#username)
- [VerifyHostname](#verifyhostname)
- [WaitAfterConnectError](#waitafterconnecterror)

---
### BatchCount
Number of TQV messages to buffer per channel before sending data as a batch to the SiteWise Edge MQTT broker.

**Type**: Int

Batching is per topic and needs both BatchCount and BatchSize. A topic is published when it holds BatchCount values or BatchSize KB; BatchInterval publishes whatever is left. With only one of the two set, or only BatchInterval, every value is published immediately.

---
### BatchInterval
Interval in milliseconds after which all messages are sent to the SiteWise Edge MQTT Broker, even when the BatchSize or BatchCount limit is not reached.

**Type**: Int

Batching: see [BatchCount](#batchcount).


---
### BatchSize
Channel TQV Payload size in KB of messages to batch before sending data as a batch to the SiteWise Edge MQTT broker.

**Type**: Int

Batching: see [BatchCount](#batchcount).
The size is calculated on the uncompressed payload of the messages.

---
### Certificate
Path to client certificate file. Used if broker used certificate authentication

**Type**: String

---
### ClientName
Client name to provide when connecting to the SiteWise Edge MQTT broker. When running on Greengrass core, this should be the name of the IoT Thing which is providing the certificates.

**Type**: String

Required.

Length Constraints: Minimum length of 1. Maximum length of 128.

Pattern: [a-zA-Z0-9:_-]+

---
### ConnectRetries
Number of retries to connect to MQTT broker

**Type**: Int

Default is 10

---
### ConnectTimeout
Timeout for connecting to the broker in seconds

**Type**: Int

Default is 10 seconds. Known limitation: the configured value is currently not applied; the timeout is always 10 seconds.

---
### EndPoint
SiteWise Edge MQTT broker endpoint address

**Type**: String

Required. Use `tcp://<host>` for plain MQTT or `ssl://<host>` for TLS with a client certificate, which requires [RootCA](#rootca), [Certificate](#certificate) and [PrivateKey](#privatekey). The client connects to this URL: without a port in it, the default port of the scheme is used (1883 for `tcp://`, 8883 for `ssl://`), and a port can be added as `tcp://<host>:<port>`. Do not include a port with `ssl://`.


---
### Password
Password if broker is using username and password authentication

**Type**: String

Username and password should not be included as clear text in the configuration. It is strongly recommended to use placeholders and use the SFC integration with the [AWS secrets manager](../core/secrets-manager-configuration.md).

---
### Port
SiteWise Edge MQTT broker port

**Type**: Integer

Required. Set it to the broker port. The MQTT connection itself uses the port in [EndPoint](#endpoint), or the default port of its scheme; Port is used to fetch the server certificate for `ssl://` connections. Commonly port numbers are

- 1883 for `tcp://`
- 8883 for `ssl://`

---
### PrivateKey
Path to client private key file

**Type**: String

---
### PublishTimeout
Timeout in seconds for publishing

**Type**: Integer

Default is 10 seconds. Known limitation: the configured value is currently not applied; the timeout is always 10 seconds.

---
### RootCA
Path to root certificate file. The Root CA file in an MQTT client is used for server certificate verification when establishing a secure connection with the broker (using TLS/SSL)

**Type**: String

---
### SslServerCertificate
Path to server certificate file to verify the identity of the broker.

**Type**: String

If no certificate file is specified it is obtained from the server.
Used for `ssl://` connections.

---
### TopicName
Name of the MQTT topic to which SiteWise Edge will subscribe for ingesting data. You may use a combination of %source%, %target%, and %channel% variables.

**Type**: String

Default: %channel%

Must contain %channel%. The rendered value is both the MQTT topic and the property alias in the TQV payload, so the SiteWise asset property that receives the values must have this alias; with the default %channel%, the alias is the channel name. Values are sent with quality GOOD. The [in-process-opcua-sitewiseedge](../../examples/in-process-opcua-sitewiseedge/README.md) example creates an asset whose property aliases match the channel names.

---
### Username
Username if broker is using username and password authentication

**Type**: String

Username and password should not be included as clear text in the configuration. It is strongly recommended to use placeholders and use the SFC integration with the [AWS secrets manager](../core/secrets-manager-configuration.md).

---
### VerifyHostname
Verify the server hostname from the provided certificates. Set this to `false` when connecting to SiteWise Edge running on Greengrass. IoT self-signed certificates do not provide the hostname.

**Type**: Boolean

Default is true

---
### WaitAfterConnectError
Period in seconds to wait before trying to connect after a connection failure

**Type**: Int

Default is 10 seconds

### SiteWiseEdgeTargetConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "SiteWiseEdgeTargetConfiguration",
  "type": "object",
  "allOf": [
    {
      "$ref": "#/definitions/TargetConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "BatchCount": {
          "type": "integer",
          "description": "Number of messages to batch"
        },
        "BatchInterval": {
          "type": "integer",
          "description": "Interval between batch processing in milliseconds"
        },
        "BatchSize": {
          "type": "integer",
          "description": "Size of the batch in KB"
        },
        "Certificate": {
          "type": "string",
          "description": "Client certificate for authentication"
        },
        "ClientName": {
          "type": "string",
          "description": "Name of the client"
        },
        "ConnectRetries": {
          "type": "integer",
          "description": "Number of connection retry attempts"
        },
        "ConnectTimeout": {
          "type": "integer",
          "description": "Connection timeout in seconds"
        },
        "EndPoint": {
          "type": "string",
          "description": "Endpoint URL"
        },
        "Password": {
          "type": "string",
          "description": "Password for authentication"
        },
        "Port": {
          "type": "integer",
          "description": "Port number"
        },
        "PrivateKey": {
          "type": "string",
          "description": "Private key for authentication"
        },
        "PublishTimeout": {
          "type": "integer",
          "description": "Timeout for publish operations in seconds"
        },
        "RootCA": {
          "type": "string",
          "description": "Root CA certificate"
        },
        "SslServerCertificate": {
          "type": "string",
          "description": "SSL server certificate"
        },
        "TopicName": {
          "type": "string",
          "description": "Name of the topic"
        },
        "Username": {
          "type": "string",
          "description": "Username for authentication"
        },
        "VerifyHostname": {
          "type": "boolean",
          "description": "Whether to verify hostname in SSL certificate"
        },
        "WaitAfterConnectError": {
          "type": "integer",
          "description": "Wait time after connection error in seconds"
        }
      },
      "required": ["ClientName", "EndPoint", "Port"]
    }
  ]
}

```

### SiteWiseEdgeTargetConfiguration Examples

```json
{
  "Active": true,
  "TargetType": "AWS-SITEWISEEDGE-TARGET",
  "TopicName": "%channel%",
  "ClientName": "${CLIENT_ID}",
  "EndPoint": "ssl://${GATEWAY_HOSTNAME}",
  "Port": 8883,
  "RootCA": "${GATEWAY_CA_FILE}",
  "Certificate": "${CLIENT_CERTIFICATE_FILE}",
  "PrivateKey": "${CLIENT_KEY_FILE}",
  "VerifyHostname": false,
  "BatchSize": 1000,
  "BatchInterval": 5000,
  "BatchCount": 10
}
```

The example reads the gateway host name, the client name and the certificate files from environment variables. Set them in the terminal that starts SFC:

**Linux / macOS**

```shell
export GATEWAY_HOSTNAME="<gateway host name>"
export CLIENT_ID="<client name>"
export GATEWAY_CA_FILE="/sfc/certs/gateway-ca.pem"
export CLIENT_CERTIFICATE_FILE="/sfc/certs/client-cert.pem"
export CLIENT_KEY_FILE="/sfc/certs/client-key.pem"
```

**Windows (PowerShell)**

```powershell
$env:GATEWAY_HOSTNAME = "<gateway host name>"
$env:CLIENT_ID = "<client name>"
$env:GATEWAY_CA_FILE = "C:/sfc/certs/gateway-ca.pem"
$env:CLIENT_CERTIFICATE_FILE = "C:/sfc/certs/client-cert.pem"
$env:CLIENT_KEY_FILE = "C:/sfc/certs/client-key.pem"
```

[^top](#aws-sitewise-edge-target)

