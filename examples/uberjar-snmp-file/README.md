# Uberjar: SNMP to files

Reads 8 OIDs from a net-snmp agent with SNMPv2c GET every 200 ms and writes the reads as JSON files.

The configuration is the e2e test case [`ADP-SNMP-PILOT`](../../ci/e2e/cases/adapters/snmp.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.
- `snmpd` from [Net-SNMP](http://www.net-snmp.org/), on the same machine: the configuration reads the agent on `127.0.0.1`.

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-snmp-file
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-snmp-file
.\create.ps1
```

This writes `snmp-to-file.json` and `snmpd.conf`: the case's configuration with its uberjar section, without the CI-only `Metadata` and `Metrics` sections. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

## 2. Start the SNMP agent

In a second shell, in this folder:

```shell
snmpd -f -Lo -C -c snmpd.conf udp:127.0.0.1:1161
```

## 3. Run SFC

Back in the first shell, in this folder:

**Linux / macOS**

```shell
mkdir -p out
export SFC_E2E_SINK=out SFC_E2E_AGENT_PORT=1161
sfcx -config snmp-to-file.json -info
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force out | Out-Null
$env:SFC_E2E_SINK = "out"; $env:SFC_E2E_AGENT_PORT = "1161"
sfcx -config snmp-to-file.json -info
```

SFC writes the reads as JSON files into `out/<year>/<month>/<day>/<hour>/<minute>/`. Stop it with `Ctrl-C`.

Docs used: [SNMP adapter](../../docs/adapters/snmp.md) · [File target](../../docs/targets/file.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
