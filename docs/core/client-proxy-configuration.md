

## ClientProxyConfiguration

[SFC Configuration](./sfc-configuration.md) > [AwsIotCredentialProviderClients](./sfc-configuration.md#awsiotcredentialproviderclients) > [Proxy](./aws-iot-credential-provider-configuration.md#proxy)

[REST adapter](../adapters/rest.md) > [RestServers](../adapters/rest.md#restservers) > [Proxy](../adapters/rest.md#proxy)

The ClientProxyConfiguration class defines settings for client-level proxy connections, including the proxy server URL, optional authentication credentials (username/password), and addresses that can bypass the proxy (NoProxyAddresses). It provides a structured way to configure how client connections are routed through a proxy server in the SFC system.

- [Schema](#schema)
- [Examples](#examples)

**Properties:**

- [NoProxyAddresses](#noproxyaddresses)
- [ProxyPassword](#proxypassword)
- [ProxyUrl](#proxyurl)
- [ProxyUsername](#proxyusername)

  

---
### NoProxyAddresses
The NoProxyAddresses property accepts a comma-separated list of addresses that should bypass the proxy server. These addresses will be accessed directly without going through the configured proxy. This optional string property allows you to specify exceptions to proxy routing, such as local or internal network addresses.

The REST adapter ignores NoProxyAddresses, see [ProxyUrl](#proxyurl).

**Type**: String

---
### ProxyPassword
The ProxyPassword property specifies the password for proxy server authentication. This optional string property should be used in conjunction with ProxyUsername when the proxy server requires authentication credentials.

**Type**: String

Optional

---
### ProxyUrl
The ProxyUrl property specifies the URL address of the proxy server that will handle client connections. This required string property defines the endpoint where proxy requests should be directed.

Format `http://host:port`, e.g. `http://proxy.example.com:8080`. The REST adapter uses it as an HTTP proxy, sends ProxyUsername and ProxyPassword as basic proxy authentication only when both are set, and ignores NoProxyAddresses. For [AwsIotCredentialProviderClients](./aws-iot-credential-provider-configuration.md#proxy) the proxy is currently not applied to the credentials-provider request.

**Type**: String

---
### ProxyUsername
The ProxyUsername property specifies the username for proxy server authentication. This optional string property should be used together with ProxyPassword when the proxy server requires authentication credentials.

**Type**: String

[^top](#clientproxyconfiguration)



## Schema:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "ProxyUrl": {
      "type": "string",
      "minLength": 1,
      "description": "Proxy server URL, e.g. http://proxy.example.com:8080"
    },
    "ProxyUsername": {
      "type": "string",
      "description": "Optional proxy authentication username"
    },
    "ProxyPassword": {
      "type": "string",
      "description": "Optional proxy authentication password"
    },
    "NoProxyAddresses": {
      "type": "string",
      "description": "Optional comma-separated list of hosts that should bypass the proxy",
      "examples": [
        "localhost,127.0.0.1",
        "internal.example.com,*.local,10.0.0.*"
      ]
    }
  },
  "required": [
    "ProxyUrl"
  ],
  "additionalProperties": false,
  "allOf": [
    {
      "if": {
        "required": [
          "ProxyUsername"
        ]
      },
      "then": {
        "required": [
          "ProxyPassword"
        ]
      }
    },
    {
      "if": {
        "required": [
          "ProxyPassword"
        ]
      },
      "then": {
        "required": [
          "ProxyUsername"
        ]
      }
    }
  ]
}
```

## Examples

Basic configuration (only required fields):

```json
{
  "ProxyUrl": "http://proxy.example.com:8080"
}
```



With authentication:

```json
{
  "ProxyUrl": "http://proxy.example.com:8080",
  "ProxyUsername": "${proxyuser}",
  "ProxyPassword": "${proxypass}"
}
```

With non-proxy addresses:

```json
{
  "ProxyUrl": "http://proxy.example.com:8080",
  "NoProxyAddresses": "localhost,127.0.0.1,*.internal.example.com"
}
```



Complete configuration, all fields:

```json
{
  "ProxyUrl": "http://proxy.example.com:8080",
  "ProxyUsername": "${proxyuser}",
  "ProxyPassword": "${proxypass}",
  "NoProxyAddresses": "localhost,127.0.0.1,*.internal.example.com,10.0.0.*"
}

```

[^top](#clientproxyconfiguration)
