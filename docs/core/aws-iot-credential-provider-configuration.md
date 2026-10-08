## AwsIotCredentialProviderClientConfiguration

[SFC Configuration](./sfc-configuration.md) > [AwsIotCredentialProviderClientConfiguration](./sfc-configuration.md#awsiotcredentialproviderclients)

An AWS IoT Credentials Provider Client configuration is used  to obtain temporary credentials used when AWS service API calls using X.509 certificates. AWS service targets, the [SecretsManager](./secrets-manager-configuration.md) section and the `CloudWatch` section of the [AWS CloudWatch metrics writer](../metrics/aws-cloudwatch.md) refer to a client by its name in their CredentialProviderClient property, e.g. `"CredentialProviderClient": "AwsIotClient"`. If  AWS IoT  Greengrass  is deployed on the system,  alternatively this [configuration](https://docs.aws.amazon.com/greengrass/v2/developerguide/device-auth.html) can be referenced even when SFC is not deployed as a Greengrass component.

For more info see [Session credentials for targets accessing AWS Service](../sfc-aws-service-credentials.md)

**Examples:** [in-process-slmp-s3](../../examples/in-process-slmp-s3/README.md) defines its client in [credential-providers.json](../../examples/in-process-slmp-s3/credential-providers.json) · [greengrass-in-process](../../examples/greengrass-in-process/README.md) and [greengrass-ipc](../../examples/greengrass-ipc/README.md) use [GreenGrassDeploymentPath](#greengrassdeploymentpath) · all: [examples catalog](../examples/README.md)

- [Schema](#schema)
- [Examples](#examples)


**Properties:**
- [CertificateFile](#certificatefile)
- [CertificatesAndKeysByFileReference](#certificatesandkeysbyfilereference)
- [ExpiryClockSkewSeconds](#expiryclockskewseconds)
- [GreenGrassDeploymentPath](#greengrassdeploymentpath)
- [IotCredentialEndpoint](#iotcredentialendpoint)
- [PrivateKeyFile](#privatekeyfile)
- [Proxy](#proxy)
- [RoleAlias](#rolealias)
- [RootCa](#rootca)
- [SkipCredentialsExpiryCheck](#skipcredentialsexpirycheck)
- [ThingName](#thingname)

---
### CertificateFile
The CertificateFile property specifies the file system path to the X.509 device certificate file. This certificate is used to authenticate the device with AWS IoT Core services. The certificate must be registered with AWS IoT Core and associated with appropriate policies for authentication and authorization.

**Type**: String

Required unless [GreenGrassDeploymentPath](#greengrassdeploymentpath) is set.

---
### CertificatesAndKeysByFileReference
The CertificatesAndKeysByFileReference property controls how certificates and keys are passed to SFC components running as IPC (Inter-Process Communication) services. When true, only the file paths are sent to IPC services, which read the files themselves, so the files must exist at those paths on the host running the service (the SFC core also checks that the paths exist). The paths are sent in the format of the core's OS, so a core on Windows sends backslash paths that a Linux or macOS service cannot open. When false (default), the core reads the files and sends their content.

**Type**: Boolean

Default is false

---
### ExpiryClockSkewSeconds
The ExpiryClockSkewSeconds property defines a buffer time (in seconds) added to the system clock when checking credential expiration. This helps prevent using expired credentials when system clocks are slightly out of sync. The credential provider will proactively fetch new credentials when the current time plus this skew value exceeds the credential expiration time. For example, with the default value of 300 seconds (5 minutes), new credentials will be requested 5 minutes before actual expiration.

**Type**: Int

Default = 300 seconds

---
### GreenGrassDeploymentPath
The GreenGrassDeploymentPath property specifies the root directory path of an AWS IoT Greengrass V2 deployment. When set, the credential provider will read configuration settings ( [IotCredentialEndpoint](#iotcredentialendpoint), [RoleAlias](#rolealias), [ThingName](#thingname), [CertificateFile](#certificatefile), [PrivateKeyFile](#privatekeyfile), [RootCa](#rootca), and [Proxy](#proxy)) from the Greengrass configuration file. Individual settings specified elsewhere will override those from the Greengrass configuration.

The typical root directory for Greengrass 2 deployment is /greengrass/v2 (Windows: `C:\greengrass\v2`, written as `"C:/greengrass/v2"` in JSON). The process running the core or target must have access to the file effectiveConfig.yaml in subdirectory config. Note that these directories and files have restricted access.

Note: This configuration can be used even when SFC is not deployed as a Greengrass component.

**Type**: String

---
### IotCredentialEndpoint
Endpoint for credential provider service

**Type**: String

Required unless [GreenGrassDeploymentPath](#greengrassdeploymentpath) is set.

Can be obtained with this AWS CLI command (the same in PowerShell):

```shell
aws iot describe-endpoint --endpoint-type iot:CredentialProvider --query endpointAddress --output text
```
Format is `<prefix>.credentials.iot.<region>.amazonaws.com`

---
### PrivateKeyFile
The PrivateKeyFile property specifies the file system path to the private key file associated with the device certificate. This private key is used in conjunction with the device certificate for authentication with AWS IoT Core services and must be kept secure. The private key file must correspond to the public key in the device certificate.

**Type**: String

Required unless [GreenGrassDeploymentPath](#greengrassdeploymentpath) is set.

---
### Proxy
Proxy configuration if the client is using a proxy server to access the internet.

**Type**: [ClientProxyConfiguration](./client-proxy-configuration.md)

Optional

Note: the proxy is currently not applied to the credentials-provider request.

---
### RoleAlias
The RoleAlias property specifies an alias that points to an IAM role. When requesting temporary credentials, this alias must be included to indicate which IAM role should be assumed. The AWS IoT credentials provider uses this role alias to obtain temporary security tokens from AWS Security Token Service (STS) that grant the permissions defined in the referenced IAM role.

**Type**: String

Required unless [GreenGrassDeploymentPath](#greengrassdeploymentpath) is set.

---
### RootCa
The RootCa property specifies the file system path to the root Certificate Authority (CA) certificate file. This certificate is used to verify the authenticity of the AWS IoT Core endpoint during TLS handshake. The root CA certificate establishes the chain of trust for secure communications with AWS IoT services

**Type**: String

Required unless [GreenGrassDeploymentPath](#greengrassdeploymentpath) is set.

---
### SkipCredentialsExpiryCheck
The SkipCredentialsExpiryCheck property allows bypassing the credential expiration verification on systems with unreliable clock time. When set to true, the credential provider will not validate the expiration time of credentials. This can be useful in environments where system time may be incorrect, but it comes with risks - API service calls may fail if the credentials have actually expired. The target implementation must handle such failures appropriately.

**Type**: Boolean

Default = false

---
### ThingName
The ThingName property specifies the AWS IoT thing name associated with the device certificate. This is the unique identifier for the device in AWS IoT Core that corresponds to the device certificate being used for authentication. The thing name is used to identify the device when requesting credentials from the AWS IoT credentials provider service.

**Type**: String

Required unless [GreenGrassDeploymentPath](#greengrassdeploymentpath) is set.

[^top](#awsiotcredentialproviderclientconfiguration)

## Schema



```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "ThingName": {
      "type": "string",
      "minLength": 1
    },
    "RoleAlias": {
      "type": "string",
      "minLength": 1
    },
    "CertificateFile": {
      "type": "string",
      "minLength": 1,
      "pattern": "^([A-Za-z]:)?[\\/\\\\](?:[^\\/\\\\\\n\\r\\t\\f\\v]+[\\/\\\\])*[^\\/\\\\\\n\\r\\t\\f\\v]*$",
      "description": "Path to certificate file. Can be either Windows style (C:\\path\\to\\cert.pem) or Unix style (/path/to/cert.pem)"
    },
    "PrivateKeyFile": {
      "type": "string",
      "minLength": 1,
      "pattern": "^([A-Za-z]:)?[\\/\\\\](?:[^\\/\\\\\\n\\r\\t\\f\\v]+[\\/\\\\])*[^\\/\\\\\\n\\r\\t\\f\\v]*$",
      "description": "Path to private key file. Can be either Windows style (C:\\path\\to\\key.pem) or Unix style (/path/to/key.pem)"
    },
    "RootCa": {
      "type": "string",
      "pattern": "^([A-Za-z]:)?[\\/\\\\](?:[^\\/\\\\\\n\\r\\t\\f\\v]+[\\/\\\\])*[^\\/\\\\\\n\\r\\t\\f\\v]*$",
      "description": "Path to root CA file. Can be either Windows style (C:\\path\\to\\root-ca.pem) or Unix style (/path/to/root-ca.pem)"
    },
    "IotCredentialEndpoint": {
      "type": "string",
      "minLength": 1,
      "pattern": "^[a-z0-9]+\\.credentials\\.iot\\.[a-z]{2}-[a-z]+-\\d{1}\\.amazonaws\\.com$",
      "description": "AWS IoT endpoint"
    },
    "SkipCredentialsExpiryCheck": {
      "type": "boolean",
      "default": false
    },
    "ExpiryClockSkewSeconds": {
      "type": "integer",
      "minimum": 0,
      "default": 300
    },
    "GreenGrassDeploymentPath": {
      "type": "string",
      "description": "Optional GreenGrass deployment path"
    },
    "Proxy": {
      "$ref": "#/definitions/ClientProxy",
      "description": "Optional proxy configuration"
    }
  },
  "allOf": [
    {
      "if": {
        "properties": {
          "GreenGrassDeploymentPath": {
            "not": {
              "type": "string"
            }
          }
        }
      },
      "then": {
        "required": [
          "ThingName",
          "RoleAlias",
          "CertificateFile",
          "PrivateKeyFile",
          "RootCa",
          "IotCredentialEndpoint"
        ]
      }
    }
  ]
}
```



## Examples



Configuration specifying all required properties:

```json
{
  "ThingName": "MyIoTThing",
  "RoleAlias": "GreengrassV2TokenExchangeRoleAlias",
  "CertificateFile": "/greengrass/v2/device.pem.crt",
  "PrivateKeyFile": "/greengrass/v2/private.pem.key",
  "RootCa": "/greengrass/v2/AmazonRootCA1.pem",
  "IotCredentialEndpoint": "c1alcfbzvfkjpi.credentials.iot.eu-west-1.amazonaws.com"
}
```

On Windows write these paths with forward slashes, e.g. `"C:/greengrass/v2/device.pem.crt"` (see the proxy example below); a single backslash is a JSON escape.

Configuration referring to a GreenGrass deployment configuration:

```json
{
  "AwsIotCredentialProviderClients": {
    "AwsIotClient": {
      "GreenGrassDeploymentPath": "/greengrass/v2"
    }
  }
}
```

On Windows: `"GreenGrassDeploymentPath": "C:/greengrass/v2"`.



Configuration using a proxy for internet access (see the note under [Proxy](#proxy)):

```json
{
  "ThingName": "MyIoTThing",
  "RoleAlias": "GreengrassV2TokenExchangeRoleAlias",
  "CertificateFile": "C:/greengrass/v2/device.pem.crt",
  "PrivateKeyFile": "C:/greengrass/v2/private.pem.key",
  "RootCa": "C:/greengrass/v2/AmazonRootCA1.pem",
  "IotCredentialEndpoint": "c1alcfbzvfkjpi.credentials.iot.eu-west-1.amazonaws.com",
  "Proxy": {
    "ProxyUrl": "http://proxy.example.com:8080",
    "ProxyUsername": "proxyuser",
    "ProxyPassword": "${PROXY_PASSWORD}",
    "NoProxyAddresses": "localhost,127.0.0.1,internal.example.com"
  }
}
```

[^top](#awsiotcredentialproviderclientconfiguration)
