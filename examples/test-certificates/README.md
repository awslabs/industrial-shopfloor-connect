# Generate Self-Signed Certificates

Scripts for generating self-signed certificates for TLS between SFC components (IPC). Use for testing only.

Both scripts create the same files in the current directory: a test CA (`ca-cert.pem`, `ca-key.pem`) and a server and
a client certificate signed by it (`server-cert.pem`, `server-key.pem`, `client-cert.pem`, `client-key.pem`), valid for
365 days, plus the signing requests (`*-req.pem`), `*-ext.cnf` and `ca-cert.srl`. The subject alternative names are the
host name, `localhost`, the IPv4 addresses of the host, `127.0.0.1` and `0.0.0.0`, so the certificates suit a test with
the SFC core and the services on the host that ran the script. The subject is `C=US`, `ST=WA`, `L=SEATTLE`, `O=AWS`,
`OU=AIP` (edit these values at the top of the script to change them), with the host name followed by `-CA`, `-SERVER`
or `-CLIENT` as `CN`.

Each script first deletes every `*.pem`, `*.srl` and `*.cnf` file in the current directory, so run it in an empty one.

## Use it

Both scripts need `openssl`. From this folder:

**Linux / macOS**

[`generate-test-certififcates.sh`](./generate-test-certififcates.sh) needs bash, and `ifconfig` for the IP addresses
(without it, only `127.0.0.1` and `0.0.0.0` are added):

```shell
mkdir -p certs
cd certs
bash ../generate-test-certififcates.sh
```

**Windows (PowerShell)**

[`generate-test-certificates.ps1`](./generate-test-certificates.ps1) runs in Windows PowerShell 5.1. OpenSSL is not part
of Windows; Git for Windows (`winget install Git.Git`) includes `openssl.exe` in `C:\Program Files\Git\usr\bin`, which
the first line adds to the `PATH` of the current session. `-ExecutionPolicy Bypass` is needed because the default
execution policy of Windows 10 and 11 blocks `.ps1` files:

```powershell
$env:Path += ";C:\Program Files\Git\usr\bin"
New-Item -ItemType Directory -Force certs | Out-Null
Set-Location certs
powershell -NoProfile -ExecutionPolicy Bypass -File ..\generate-test-certificates.ps1
```

For ServerSideTLS, start the protocol adapter service with
`-connection ServerSideTLS -cert server-cert.pem -key server-key.pem`, and set `"ConnectionType": "ServerSideTLS"` and
`"ServerCertificate"` (the path of `server-cert.pem`) in its server entry in `AdapterServers`. For MutualTLS, start the
service with `-connection MutualTLS` and add `-ca ca-cert.pem`; the server entry then has
`"ConnectionType": "MutualTLS"` and the paths of `client-cert.pem`, `client-key.pem` and `ca-cert.pem` in
`"ClientCertificate"`, `"ClientPrivateKey"` and `"CaCertificate"`. Relative paths resolve against the directory the
service or SFC is started from. The current limits, and a full [example](../../docs/sfc-securing-component-traffic.md#example),
are on [Securing network traffic between SFC components](../../docs/sfc-securing-component-traffic.md).

Docs used: [Generating keys and certificates](../../docs/sfc-securing-component-traffic.md#generating-keys-and-certificates) · [Server configuration](../../docs/core/server-configuration.md) · [All examples](../../docs/examples/README.md)
