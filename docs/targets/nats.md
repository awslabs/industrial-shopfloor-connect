# NATS Target



The NATS target adapter enables Shop Floor Connectivity (SFC) to publish data to subjects on a [NATS](https://nats.io/) server. The adapter provides configurable options for connection management, subject naming, and message delivery guarantees.

## Deploy this target

`TargetType` is `NATS-TARGET` in every deployment mode. In the uberjar and in-process modes the `TargetTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode). All types and classes: [Target types and classes](../sfc-running-targets.md#target-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"TargetTypes": {
  "NATS-TARGET": { "FactoryClassName": "com.amazonaws.sfc.natstarget.NatsTargetWriter" }
}
```

**In-process** - module bundle `nats-target` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"TargetTypes": {
  "NATS-TARGET": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/nats-target/lib"],
    "FactoryClassName": "com.amazonaws.sfc.natstarget.NatsTargetWriter"
  }
}
```

**IPC** - no `TargetTypes`; the target runs as its own service:

```json
"Targets": {
  "NatsTarget": {
    "TargetType": "NATS-TARGET",
    "TargetServer": "NatsTargetServer"
  }
},
"TargetServers": {
  "NatsTargetServer": { "Address": "localhost", "Port": 50001 }
}
```

Start the service before SFC, on the port of its `TargetServers` entry:

**Linux / macOS**

```shell
nats-target/bin/nats-target -port 50001
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\nats-target\lib\*" com.amazonaws.sfc.natstarget.NatsTargetService -port 50001
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.natstarget.NatsTargetService -port 50001` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.natstarget.NatsTargetService -port 50001`).

**Examples:** none yet - start from [Quickstart step 2](../../README.md#2-first-data--no-hardware-no-cloud) and swap in this component. All: [examples catalog](../examples/README.md)



**Configuration:**

- [NatsTargetConfiguration](#natstargetconfiguration)
- [NatsServerConfiguration](#natsserverconfiguration)

  

## NatsTargetConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [Targets](../core/sfc-configuration.md#targets) >  [Target](../core/target-configuration.md) 

NatsTargetConfiguration extends the type  TargetConfiguration with specific configuration data for connecting to and sending to a NATS subject. The Targets configuration element can contain entries of this type; the TargetType of these entries must be set to **"NATS-TARGET"**.

- [Schema](#natstargetconfiguration-schema)
- [Examples](#natstargetconfiguration-examples)

**Properties:**
- [AlternateSubjectName](#alternatesubjectname)
- [BatchCount](#batchcount)
- [BatchInterval](#batchinterval)
- [BatchSize](#batchsize)
- [Compression](#compression)
- [Formatter](#formatter)
- [MaxPayloadSize](#maxpayloadsize)
- [NatsServer](#natsserver)
- [PublishTimeout](#publishtimeout)
- [SubjectName](#subjectname)
- [Template](#template)
- [WarnAlternateSubjectName](#warnalternatesubjectname)

---
### AlternateSubjectName
An alternative subject name or template to use when the primary [SubjectName](#subjectname) contains unmapped placeholder variables that cannot be resolved. This serves as a fallback publishing destination when dynamic topic name construction fails. The same placeholders are available for this template as for the [SubjectName](#subjectname)

**Type**: String

---
### BatchCount
The maximum number of messages to accumulate in the buffer before triggering a batch publish to the NATS subject. When this count is reached, all buffered messages are sent as an array in a single NATS message.

Batching is triggered when any configured threshold (BatchCount, [BatchSize](#batchsize), or [BatchInterval](#batchinterval)) is reached

**Type**: Int

---
### BatchInterval

The maximum time in milliseconds to hold messages in the buffer before publishing them as a batch to the NATS subject, regardless of whether [BatchSize](#batchsize) or [BatchCount](#batchcount) limits have been reached.

Batching is triggered when any configured threshold ([BatchCount](#batchcount), [BatchSize](#batchsize), or BatchInterval) is reached

**Type**: Int

---

### BatchSize

The maximum total size in kilobytes of uncompressed message payloads to accumulate before triggering a batch publish to the NATS subject. When this size threshold is reached, all buffered messages are sent as an array in a single NATS message.

Batching is triggered when any configured threshold ([BatchCount](#batchcount), BatchSize, or [BatchInterval](#batchinterval)) is reached

**Type**: Int

---
### Compression
The compression algorithm to be applied to NATS message payloads before publishing.

Compressing messages can reduce bandwidth usage and transmission time.

**Type:** String

Possible values:

- "None" (Default)
- "Zip"
- "GZip"

---

### Formatter

Configuration allows for custom formatting of data written by a target. A [custom formatter](../sfc-extending.md#custom-formatters), implemented as a JVM class, converts a sequence of target data messages into a specific format and returns the formatted data as an array of bytes.

Formatter and [Template](#template) are mutually exclusive; setting both is a configuration error.

**Type:** [InProcessConfiguration](../core/in-process-configuration.md)

---
### MaxPayloadSize

The maximum size in kilobytes allowed for a single NATS message payload.

- When compression is enabled, the original uncompressed payload size may exceed this limit
- For batched messages without compression, reaching this size limit will trigger sending the batch
- Used as a threshold for batch publishing when batching is enabled

**Type**: Int


---
### NatsServer
Configuration settings for the NATS server connection.

Defines the connection parameters and settings for the NATS server where data will be published.

**Type**: [NatsServerConfiguration](#natsserverconfiguration)



---
### PublishTimeout

The maximum time in seconds to wait for a message to be published to the NATS server before timing out.

**Type**: Int

Default is 10 seconds. A configured value currently has no effect.

---
### SubjectName
The primary NATS subject name or subject name template for publishing messages.

**Type**: String

A template can be used for the subject name to render the actual topic name using placeholders. In this template, 
besides placeholders for environment variables (${name}), the following placeholders are available:

- %schedule%
- %target%
- %source%
- %channel%

To utilize the metadata values at the source or channel level of the target data, the name of the metadata value can be utilized with a '%' prefix and postfix.

Value placeholders can be employed to incorporate additional topic levels or grouping values to a specific subject.

Template examples:

- plant1-**%source%** : Values from each source will be published to a subject for that source
- plant1-**%line%**   : Values from all sources will be grouped by the value of the %line% metadata and published to a subject for that value

In case a placeholder is not resolved, when a value for a used placeholder is part of the data,
then an alternative topic name can be configured by setting the name of that topic to the [AlternateSubjectName](#alternatesubjectname) setting.

Note that the use of placeholders to send data to specific topics will result in additional publish calls to the server.

---

### Template

Specifies the file path to an [Apache velocity](https://velocity.apache.org/)  template used for  [transforming the output data](../sfc-target-templates.md) target output data. This optional setting enables custom formatting of data before it is sent to the target. Available context variables include:

- $schedule
- $sources
- $metadata
- $serial
- $timestamp
- names specified in ElementNames configuration
- $tab (for inserting tab characters)

Pathname to file containing an [Apache velocity](https://velocity.apache.org/) template that can be applied to [transform the output data](../sfc-target-templates.md) of the target.

The following [Velocity tools](https://velocity.apache.org/tools/3.1/tools-summary.html) can be used in the transformation template:

- $date
- $collection
- $context
- $math
- $number

Additional epoch timestamp values can be added to the data used for the transformation by setting the [TemplateEpochTimestamp](../core/target-configuration.md#templateepochtimestamp) property to true,

For targets where the data does not require specific output format, the data is serialized as [JSON data](../sfc-data-format.md#sfc-output-data-schemas).

Template and a custom [formatter](#formatter) are mutually exclusive; setting both for a target is a configuration error.

**Type**: String

---
### WarnAlternateSubjectName
Controls whether a warning is logged when placeholders in the [SubjectName](#subjectname) cannot be resolved and there is no usable [AlternateSubjectName](#alternatesubjectname) (none is configured, or it has unresolved placeholders as well).

**Type**: Boolean

Default is true

---



### NatsTargetConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "NatsTargetConfiguration",
  "type": "object",
  "allOf": [
    {
      "$ref": "#/definitions/TargetConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "AlternateSubjectName": {
          "type": "string",
          "description": "Alternate subject name when primary subject is unavailable"
        },
        "BatchCount": {
          "type": "integer",
          "description": "Number of messages to batch before publishing"
        },
        "BatchInterval": {
          "type": "integer",
          "description": "Interval in milliseconds between batch publishes"
        },
        "BatchSize": {
          "type": "integer",
          "description": "Maximum size of batched messages in KB"
        },
        "Compression": {
          "type": "string",
          "description": "Type of message compression",
          "enum": ["None", "Zip", "GZip"],
          "default": "None"
        },
        "MaxPayloadSize": {
          "type": "integer",
          "description": "Maximum size of message payload in KB"
        },
        "NatsServer": {
          "$ref": "#/definitions/NatsServerConfiguration",
          "description": "NATS server configuration"
        },
        "PublishTimeout": {
          "type": "integer",
          "description": "Timeout for publish operations in seconds"
        },
        "SubjectName": {
          "type": "string",
          "description": "Primary subject name for publishing"
        },
        "WarnAlternateSubjectName": {
          "type": "boolean",
          "description": "Whether to warn when a subject name cannot be resolved",
          "default": true
        }
      },
      "required": ["NatsServer", "SubjectName"]
    }
  ]
}

```

### NatsTargetConfiguration Examples

To try the target, replace the `DebugTarget` of [Quickstart step 2](../../README.md#2-first-data--no-hardware-no-cloud) with this entry (also in the schedule's `Targets`) and add the uberjar `TargetTypes` entry from [Deploy this target](#deploy-this-target). It publishes every record to the subject `sfc.demo` of a NATS server on the same host, for example `nats-server` on port 4222:

```json
"Targets": {
  "NatsTarget": {
    "TargetType": "NATS-TARGET",
    "SubjectName": "sfc.demo",
    "NatsServer": {
      "Url": "nats://127.0.0.1:4222"
    }
  }
}
```

Example 1 - Basic Configuration:

```json
{
  "TargetType" : "NATS-TARGET",
  "SubjectName": "sensors.data",
  "NatsServer": {
    "Url": "nats://nats.example.com:4222",
    "ConnectRetries": 5,
    "WaitAfterConnectError": 10
  },
  "Compression": "None"
}
```

Batched Publishing Configuration:

```json
{
  "TargetType" : "NATS-TARGET",
  "SubjectName": "metrics.production",
  "BatchCount": 100,
  "BatchSize": 128,
  "BatchInterval": 1000,
  "NatsServer": {
    "Url": "nats://nats.example.com:4222"
  }
}
```



Dynamic subject names based on target- and metadata values. NATS separates subject tokens with `.`, so build the levels with dots:

```json
{
  "TargetType" : "NATS-TARGET",
  "SubjectName": "data.%location%.%line%.%source%",
  "AlternateSubjectName": "data.sensors",
  "WarnAlternateSubjectName": true,
  "BatchCount": 100,
  "BatchSize": 128,
  "BatchInterval": 1000,
  "NatsServer": {
    "Url": "nats://nats.example.com:4222"
  }
}
```



[^top](#nats-target)

## NatsServerConfiguration

[NatsTarget](#natstargetconfiguration) > [NatsServer](#natsserver)

Configuration class that defines the connection parameters for a NATS server, including server URL, authentication credentials, and connection settings. It provides the necessary settings to establish and maintain a connection to a NATS message server.


- [Schema](#natsserverconfiguration-schema)
- [Examples](#natsserverconfiguration-examples)

**Properties:**
- [ConnectRetries](#connectretries)
- [CredentialsFile](#credentialsfile)
- [NKeyFile](#nkeyfile)
- [Password](#password)
- [Tls](#tls)
- [Token](#token)
- [Url](#url)
- [Username](#username)
- [WaitAfterConnectError](#waitafterconnecterror)

---
### ConnectRetries
The maximum number of connection attempts to make when trying to establish a connection with the NATS server.

**Type**: Integer


Default = 3


---
### CredentialsFile
Specifies the location of a credentials file containing a user JWT token and NKey private seed for secure authentication, used to authenticate and authorize client connections to the NATS server.


**Type**: String


https://docs.nats.io/using-nats/developer/connecting/creds


---
### NKeyFile
Specifies the location of a file containing an Ed25519-based NKey for secure authentication.
Enables public-key-based authentication between the client and NATS server using the NKey system.

**Type**: String


https://docs.nats.io/using-nats/developer/connecting/nkey



---
### Password
The password credential for authenticating with the NATS server when using username/password authentication.

[Username](#username) and password should not be included as clear text in the configuration. It is strongly recommended to use placeholders and use the SFC integration with the [AWS secrets manager](../core/secrets-manager-configuration.md).

**Type**: String


https://docs.nats.io/using-nats/developer/connecting/userpass

If a Password is configured then the [Username](#username) must be configured as well.


---
### Tls
TLS configuration settings for secure communication with the NATS server.

From the [NATS docs](https://docs.nats.io/using-nats/developer/connecting/tls): *While authentication limits which clients can connect, TLS can be used to encrypt traffic between client/server and check the server's identity. Additionally - in the most secure version of TLS with NATS - the server can be configured to verify the client's identity, thus authenticating it. When started in TLS mode, a nats-server will require all clients to connect with TLS. Moreover, if configured to connect with TLS, client libraries will fail to connect to a server without TLS.*

**Type**: TlsConfiguration, an object with these keys:

- `Certificate`: path to the client certificate file
- `PrivateKey`: path to the private key file of the client certificate
- `RootCA`: path to the CA certificate file used to verify the server
- `SslServerCertificate`: optional, path to a server certificate file that is trusted in addition to `RootCA`

`Certificate` and `PrivateKey` are required when `Tls` is set. The target trusts only `RootCA` and `SslServerCertificate`, not the Java default CAs, so set at least one of them.


https://docs.nats.io/using-nats/developer/connecting/tls


---
### Token
Token for basic NATS authentication.

Random token authentication functions like a password for simple setups. However, for larger systems, more secure authentication methods should be used since tokens rely solely on secrecy. 

Tokens should not be included as clear text in the configuration. It is strongly recommended to use placeholders and use the SFC integration with the [AWS secrets manager](../core/secrets-manager-configuration.md).

**Type**: String


https://docs.nats.io/using-nats/developer/connecting/token


---
### Url
Server URL(s) for connecting to the NATS server.

One or more comma-separated URLs with the scheme `nats://`, `tls://` or `ws://`. If the scheme is "tls:" then
the "Tls" property for the server **could** also be set to specify the required key and certificates - for establishing `mTLS` secured auth.



**Type**: String

---
### Username
The username credential for authenticating with the NATS server when using username/password authentication.

Username and [password](#password) should not be included as clear text in the configuration. It is strongly recommended to use placeholders and use the SFC integration with the [AWS secrets manager](../core/secrets-manager-configuration.md).

**Type**: String


https://docs.nats.io/using-nats/developer/connecting/userpass

If a Username is configured then the [Password](#password) must be configured as well.


---
### WaitAfterConnectError
Time delay in seconds before retrying after a failed connection attempt to the NATS server.

**Type**: Integer


Default = 10

### NatsServerConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "NatsServerConfiguration",
  "type": "object",
  "properties": {
    "ConnectRetries": {
      "type": "integer",
      "description": "Number of connection retry attempts"
    },
    "CredentialsFile": {
      "type": "string", 
      "description": "Path to NATS credentials file"
    },
    "NKeyFile": {
      "type": "string",
      "description": "Path to NATS NKey file"
    },
    "Password": {
      "type": "string",
      "description": "Password for authentication"
    },
    "Tls": {
      "$ref": "#/definitions/TlsConfiguration",
      "description": "TLS configuration settings"
    },
    "Token": {
      "type": "string",
      "description": "Authentication token"
    },
    "Url": {
      "type": "string",
      "description": "NATS server URL"
    },
    "Username": {
      "type": "string",
      "description": "Username for authentication"
    },
    "WaitAfterConnectError": {
      "type": "integer",
      "description": "Wait time in seconds after a connection error, minimum 1"
    }
  },
  "required": ["Url"]
}

```

### NatsServerConfiguration Examples

Basic Configuration:

```json
{
  "Url": "nats://localhost:4222",
  "Username": "${user}",
  "Password": "${password}",
  "ConnectRetries": 3,
  "WaitAfterConnectError": 5
}
```



Secure Configuration with TLS:

```json
{
  "Url": "nats://nats.example.com:4222",
  "Tls": {
    "Certificate": "/path/to/client-cert.pem",
    "PrivateKey": "/path/to/private-key.pem",
    "RootCA": "/path/to/root-ca.pem"
  },
  "ConnectRetries": 5,
  "WaitAfterConnectError": 10
}
```



Token-Based Authentication:

```json
{
  "Url": "nats://nats-server:4222",
  "Token": "${token}",
  "ConnectRetries": 3,
  "WaitAfterConnectError": 3
}
```



Credentials File Configuration. Set only one of `NKeyFile` or `CredentialsFile`; with both, only the credentials file is used:

```json
{
  "Url": "nats://prod.nats.com:4222",
  "CredentialsFile": "/path/to/credentials.creds"
}
```



[^top](#nats-target)

