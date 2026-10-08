# Securing Network Traffic between SFC components

- [PlainText](#plaintext)
- [ServerSideTLS](#serversidetls)
- [MutualTLS](#mutualtls)
- [Example](#example)
- [Generating keys and certificates](#generating-keys-and-certificates)

In IPC deployments the gRPC traffic between the SFC core and protocol adapter services can be secured using encryption
(when adapters and targets run in-process, as with the uberjar, there is no network traffic between components). The
following options can be used:

> **Known limitation:** target services and the metrics writer service currently accept PlainText connections only. They
> accept the `-connection`, `-cert`, `-key` and `-ca` parameters but do not use them, so only protocol adapter services
> support ServerSideTLS and MutualTLS. Keep PlainText for `TargetServers` entries and the `MetricsServer` (see
> [Running targets as an IPC service](./sfc-running-targets.md#running-targets-as-an-ipc-service)).

## PlainText

The network traffic between SFC components is not encrypted.

## ServerSideTLS

The network traffic is encrypted with TLS; the service proves its identity with its X.509 server certificate. The
service process needs to be started using the -key and -cert parameters specifying the files containing servers private
key and server certificate. The -connection type parameter must be set to ServerSideTLS. In the SFC configuration the
[ConnectionType](./core/server-configuration.md#connectiontype) of the [server entry](./core/server-configuration.md)
in `AdapterServers` must be set to ServerSideTLS.

The value used for the connection type parameter used for the service and the configured ConnectionType must match.

Set [ServerCertificate](./core/server-configuration.md#servercertificate) in the server entry to the file containing the
server certificate. Without it, the SFC core trusts whatever certificate the service presents.

Note that the address which is configured to communicate with the service must be present as DNS name or IP address as
one of the Alternative Subject Names in the server certificate.

## MutualTLS

The network traffic is encrypted with TLS, and the service and the client are meant to prove their identity to each
other with their X.509 certificates. The service process needs to be started using the -key, -cert and -ca parameters
specifying the files containing servers private key and server and CA certificates. The -connection type parameter must
be set to MutualTLS. In the SFC configuration the ConnectionType in the server entry for the server must be set to
MutualTLS. The ClientPrivateKey, ClientCertificate and CaCertificate must be set to the files containing the clients
private key, client certificate and CA certificate.

The value used for the connection type parameter used for the service and the configured ConnectionType must match.

The address which is configured to communicate with the service must be present as DNS name or IP address as one of the
Alternative Subject Names in the server certificate.

> **Known limitation:** the service currently does not request or verify the client certificate, so MutualTLS
> authenticates the server only, and the Alternative Subject Names of the client certificate are not checked.

## Example

The OPC UA adapter as an IPC service with ServerSideTLS, using the certificates from
[Generating keys and certificates](#generating-keys-and-certificates) in a `certs` folder of the directory the service
and SFC are started from. In the SFC configuration, the adapter's `AdapterServer` refers to this server entry:

```json
"AdapterServers": {
  "OpcuaServer": {
    "Address": "10.0.0.5",
    "Port": 50000,
    "ConnectionType": "ServerSideTLS",
    "ServerCertificate": "certs/server-cert.pem"
  }
}
```

Set `Address` to the address the service listens on, which it logs when it starts (`listening on <address>:<port>`);
the server certificate must contain that address. Relative paths are resolved against the directory SFC is started
from; on Windows write absolute paths with forward slashes (`"C:/sfc/certs/server-cert.pem"`).

Start the service before SFC:

**Linux / macOS**

```shell
opcua/bin/opcua -port 50000 -connection ServerSideTLS -cert certs/server-cert.pem -key certs/server-key.pem
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\opcua\lib\*" com.amazonaws.sfc.opcua.OpcuaProtocolService -port 50000 -connection ServerSideTLS -cert certs\server-cert.pem -key certs\server-key.pem
```

From an sfcup install, start the same service from the uberjar with the same options:
`java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.opcua.OpcuaProtocolService` (Windows:
`java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.opcua.OpcuaProtocolService`).
Why Windows uses `java -cp` instead of `bin\opcua.bat`: [Platform support](./README.md#platform-support).

For MutualTLS, start the service with `-connection MutualTLS` and add `-ca certs/ca-cert.pem` (Windows:
`-ca certs\ca-cert.pem`). In the server entry set `"ConnectionType": "MutualTLS"` and replace `ServerCertificate` with
the client files:

```json
"ClientCertificate": "certs/client-cert.pem",
"ClientPrivateKey": "certs/client-key.pem",
"CaCertificate": "certs/ca-cert.pem"
```

Check the service log after starting it. Its start message reports `connection type is ServerSideTLS` (or `MutualTLS`)
even when TLS could not be set up: an `Error setting up TLS for ServerSideTLS` message before it means that the service
could not use its certificate or key and accepts PlainText connections instead.

## Generating keys and certificates

For test environments, the scripts in [examples/test-certificates](../examples/test-certificates/README.md) create the
keys and certificates for ServerSideTLS and MutualTLS connections: `ca-cert.pem`, `server-cert.pem`/`server-key.pem`
and `client-cert.pem`/`client-key.pem`. Run them in an empty directory: they first delete the `*.pem`, `*.srl` and
`*.cnf` files in the current directory.

*NOTE*:

- The script is provided to generate self-signed certificates for test purposed only and should not be used in
  production environments.
- For convenience the script includes the IP addresses of all available network interfaces, and the hostname (plus
  localhost) of the system on which the script is executed, as subject alternative names (IP addresses and DNS names)
  of the generated certificates. This assumes a test setup where both the SFC core and service are executed on the
  same system. When the SFC core and SFC services run on different systems the script must be executed on both of the
  systems and the relevant certificates must be used on that system as key and certificate parameters for the server,
  or configuration values used by the SFC core.
- In production environments the IP addresses and DNS names should be included in the certificate to the expected client
  and service addresses for that environment.

From the root of a source checkout of this repository:

**Linux / macOS**

The script needs `openssl`, and `ifconfig` for the IP addresses:

```shell
mkdir -p certs
cd certs
bash ../examples/test-certificates/generate-test-certififcates.sh
```

**Windows (PowerShell)**

The script needs `openssl.exe` on the `PATH`; Git for Windows includes one in `C:\Program Files\Git\usr\bin`, which the
first line adds to the `PATH` of the current session. `-ExecutionPolicy Bypass` is needed because the default execution
policy of Windows 10 and 11 blocks `.ps1` files:

```powershell
$env:Path += ";C:\Program Files\Git\usr\bin"
New-Item -ItemType Directory -Force certs | Out-Null
Set-Location certs
powershell -NoProfile -ExecutionPolicy Bypass -File ..\examples\test-certificates\generate-test-certificates.ps1
```
