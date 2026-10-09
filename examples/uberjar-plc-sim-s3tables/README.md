# Uberjar: three simulated PLCs to a file and S3 Tables

SFC reads a Siemens S7-1500, a Beckhoff TwinCAT 3 and an Allen-Bradley MicroLogix 1400 every 100 ms. It
prints the values to the console and writes them to local JSON files and to an Apache Iceberg table in
Amazon S3 Tables. The three PLCs are
[`omni-plc-sim`](../../ci/omni-plc-sim/README.md), one process that serves S7, ADS and PCCC with live
signals, so no hardware is needed. It is a test simulator, not a reference for real PLCs.

```
omni-plc-sim (S7, ADS, PCCC)  →  SFC uberjar  →  console (debug target)
                                              →  out/*.json
                                              →  S3 Tables: sfc-industrial-data-bucket / sfc / plc_signals
```

Everything is in one file, [`plc-sim-to-s3tables.json`](./plc-sim-to-s3tables.json).

## Prerequisites

- A clone of this repository, from whose root steps 1 and 3 start:
  `git clone https://github.com/awslabs/industrial-shopfloor-connect.git`.
- A Rust toolchain, 1.98 or newer ([rustup](https://rustup.rs)), to build the simulator.
- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`).
- AWS credentials with the S3 Tables permissions the
  [target documentation](../../docs/targets/aws-s3-tables.md#awss3tablestargetconfiguration) lists, plus
  `s3tables:DeleteTable` for the clean-up, and the AWS CLI v2 for steps 4 and Clean up (Windows:
  `winget install Amazon.AWSCLI`). `AutoCreate` is on, so the target creates the table bucket, the namespace and
  the table when it starts, if they are missing.

## 1. Start the PLCs

**Linux / macOS**

```shell
cd ci/omni-plc-sim
cargo build --release
target/release/omni-plc-sim --serve s7=10102 ads pccc
```

**Windows (PowerShell)**

```powershell
cd ci\omni-plc-sim
cargo build --release
.\target\release\omni-plc-sim.exe --serve s7=10102 ads pccc
```

It prints `omni-plc-sim <protocol> listening on <address> (profile <name>)` for each PLC, then
`omni-plc-sim ready`. ADS and PCCC listen on their standard ports, 48898 and 44818. S7 listens on 10102,
because ports below 1024 need root on Linux; keep 10102 on every OS, because the config uses it. Leave it
running.

If port 48898 is already in use, for example by a local TwinCAT installation, serve ADS on another port
(`--serve ads=48899`) and set `"Port": 48899` under `ProtocolAdapters.ADS.Devices.PLC`.

## 2. Install SFC

Install SFC as in the [Quickstart](../../README.md#1-install):

**Linux / macOS**

```shell
curl -fsSL https://raw.githubusercontent.com/awslabs/industrial-shopfloor-connect/main/sfcup.sh | bash
```

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/awslabs/industrial-shopfloor-connect/main/sfcup.ps1 | iex
```

That puts `sfcx`, the command that runs the released uberjar with every adapter and target, on your
`PATH`. Open the second shell of step 3 after the install, so that it finds the command (Linux and macOS:
or run `. "$HOME/.sfc/env"` in it).

## 3. Run SFC

In a second shell, from the repository root:

**Linux / macOS**

```shell
cd examples/uberjar-plc-sim-s3tables
export AWS_REGION=us-west-2
sfcx -config plc-sim-to-s3tables.json -info
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-plc-sim-s3tables
$env:AWS_REGION = "us-west-2"
sfcx -config plc-sim-to-s3tables.json -info
```

The debug target prints every record to the console, so you see the values right away. Remove
`"DebugTarget"` from the schedule's `Targets` once that gets too chatty.

To try it without AWS, remove `"S3Tables"` from the schedule's `Targets`. Keep `AWS_REGION` set, because
the config still names it.

## 4. Look at the data

`out/` gets a JSON file every few seconds, under `out/<year>/<month>/<day>/<hour>/<minute>/`. One record:

```json
{
  "schedule": "PLCs",
  "serial": "a7d7ba71-72ef-4602-8cdc-175a0af17647",
  "timestamp": "2026-10-07T11:07:47.946143Z",
  "sources": {
    "ads":  { "values": { "int": { "value": -12345 }, "string": { "value": "SFC-SIM" },
                          "sine": { "value": -100.0 }, "sawtooth": { "value": 0.0 } } },
    "pccc": { "values": { "int": { "value": -12345 }, "string": { "value": "SFC-SIM" },
                          "sine": { "value": -98.22872 }, "triangle": { "value": 76.0 } } },
    "s7":   { "values": { "int": { "value": -12345 }, "string": { "value": "SFC-SIM" },
                          "sine": { "value": -95.10565 }, "cosine": { "value": -30.9017 } } }
  }
}
```

The S3 Tables target writes every 10 seconds. After the first write the table exists. Check it in a third
shell, as SFC keeps the second one busy:

**Linux / macOS**

```shell
export AWS_REGION=us-west-2
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET_ARN="arn:aws:s3tables:${AWS_REGION}:${ACCOUNT}:bucket/sfc-industrial-data-bucket"
aws s3tables list-tables --table-bucket-arn "$BUCKET_ARN" --namespace sfc
```

**Windows (PowerShell)**

```powershell
$env:AWS_REGION = "us-west-2"
$ACCOUNT = aws sts get-caller-identity --query Account --output text
$BUCKET_ARN = "arn:aws:s3tables:${env:AWS_REGION}:${ACCOUNT}:bucket/sfc-industrial-data-bucket"
aws s3tables list-tables --table-bucket-arn $BUCKET_ARN --namespace sfc
```

## 5. Explore it

Once rows arrive, chart them with the **Iceberg timeseries explorer** of the
[`in-process-sim-s3tables`](../in-process-sim-s3tables/README.md#the-web-app-in-cdk) example. Deploy it as
its [`cdk/README.md`](../in-process-sim-s3tables/cdk/README.md) describes, sign in, and pick bucket
`sfc-industrial-data-bucket`, namespace `sfc` and table `plc_signals`. That bucket is the explorer's
default, so it needs no extra settings.

![The six signals of sfc.plc_signals in the Iceberg timeseries explorer](./plcsim-iceberg-explorer.png)

## What the config reads

| Channel | S7 (`s7`) | ADS (`ads`) | PCCC (`pccc`) | Value |
|---|---|---|---|---|
| `int` | `%DB1.DBW4:INT` | `GVL_Static.nInt` | `N7:0` | −12345 |
| `string` | `%DB1:84:STRING(16)` | `GVL_Static.sString` | `ST9:0` | "SFC-SIM" |
| `sine` | `%DB100.DBD12:REAL` | `GVL_Dynamic.fSine` | `F8:10` | 100 · sin, 1 Hz |
| second signal | `cosine`, `%DB100.DBD16:REAL` | `sawtooth`, `GVL_Dynamic.fSawtooth` | `triangle`, `F8:17` | 1 Hz, 2 Hz, 2 Hz |

- **Columns:** the table `plc_signals` has `event_time` and the six signals as float columns. Each
  column's `ValueQuery`, such as `@.sources.s7.values.sine.value`, picks its value from the record above.
- **[Uberjar style](../../docs/sfc-deployment.md#uberjar):** every adapter and target is named by its
  `FactoryClassName` alone, with no `JarFiles`.
- **ADS:** `TargetAmsNetId` 192.168.100.10.1.1 and `TargetAmsPort` 851 are the simulated TwinCAT runtime.
  The simulator checks no routes, so any `SourceAmsNetId` and `SourceAmsPort` work.
- **More tags:** `target/release/omni-plc-sim --print-map <s7|ads|pccc>`, run in `ci/omni-plc-sim`
  (Windows: `.\target\release\omni-plc-sim.exe --print-map <s7|ads|pccc>`), lists every tag a PLC holds, with
  the address syntax SFC accepts.

## Clean up

Stop SFC and the simulator with Ctrl+C, then delete the table, in the shell of step 4 (the same command in
PowerShell):

```shell
aws s3tables delete-table --table-bucket-arn "$BUCKET_ARN" --namespace sfc --name plc_signals
```

The bucket and the namespace are shared with `in-process-sim-s3tables`. Remove them, and the explorer, as
its [clean-up section](../in-process-sim-s3tables/README.md#clean-up) describes.

Docs used: [S7 adapter](../../docs/adapters/s7.md) · [ADS adapter](../../docs/adapters/ads.md) · [PCCC adapter](../../docs/adapters/pccc.md) · [Debug target](../../docs/targets/debug.md) · [File target](../../docs/targets/file.md) · [S3 Tables target](../../docs/targets/aws-s3-tables.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [Output data format](../../docs/sfc-data-format.md#output-data-format) · [All examples](../../docs/examples/README.md)
