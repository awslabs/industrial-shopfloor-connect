# Sign SFC Config

Example application for signing an SFC configuration.
See [Securing the configuration](../../docs/sfc-configuration.md#securing-the-configuration) for details.

## Use it

The application is part of the uberjar installed by [sfcup](../../README.md#1-install); its main class is
`com.amazonaws.sfc.SignConfigKt`. It takes an RSA private key (PEM), the configuration file (`sfc.json` below) and the
name of the signed file to write (`sfc.signed.json`), adds a `ConfigSignature` entry and prints
`Signed configuration file written to <path>`. Start SFC with `-verify` and the matching public key: it does not process
a configuration whose signature is missing or does not match.

**Linux / macOS**

```shell
openssl genrsa -out sfc-sign.key 2048
openssl rsa -in sfc-sign.key -pubout -out sfc-sign.pub
java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.SignConfigKt sfc-sign.key sfc.json sfc.signed.json
sfcx -config sfc.signed.json -verify sfc-sign.pub
```

**Windows (PowerShell)**

OpenSSL is not part of Windows; Git for Windows (`winget install Git.Git`) includes `openssl.exe` in
`C:\Program Files\Git\usr\bin`, which the first line adds to the `PATH` of the current session:

```powershell
$env:Path += ";C:\Program Files\Git\usr\bin"
openssl genrsa -out sfc-sign.key 2048
openssl rsa -in sfc-sign.key -pubout -out sfc-sign.pub
java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.SignConfigKt sfc-sign.key sfc.json sfc.signed.json
sfcx -config sfc.signed.json -verify sfc-sign.pub
```

Keep the private key off the hosts that run SFC; they need only the public key. Start the application with `java -cp`
as shown: the `bin/sign-sfc-config` launcher that a source build of this module creates names a class that does not
exist (`com.amazonaws.sfc.SignConfig`) and fails.

Docs used: [Securing the configuration](../../docs/sfc-configuration.md#securing-the-configuration) · [Running the SFC core process](../../docs/sfc-running-core-process.md) (`-verify`) · [All examples](../../docs/examples/README.md)
