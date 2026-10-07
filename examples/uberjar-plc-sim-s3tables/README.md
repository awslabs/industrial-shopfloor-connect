# Uberjar: three simulated PLCs to a file and S3 Tables

SFC reads a Siemens S7-1500, a Beckhoff TwinCAT 3 and an Allen-Bradley MicroLogix 1400 every 100 ms. It
prints the values to the console and writes them to local JSON files and to an Apache Iceberg table in
Amazon S3 Tables. The three PLCs are
[`omni-plc-sim`](../../ci/omni-plc-sim/README.md), one process that serves S7, ADS and PCCC with live
signals, so no hardware is needed.

```
omni-plc-sim (S7, ADS, PCCC)  →  SFC uberjar  →  console (debug target)
                                              →  out/*.json
                                              →  S3 Tables: sfc-industrial-data-bucket / sfc / plc_signals
```

Everything is in one file, [`plc-sim-to-s3tables.json`](./plc-sim-to-s3tables.json).

## Prerequisites

- A Rust toolchain ([rustup](https://rustup.rs)), to build the simulator.
- A Java 17 (or newer) runtime.
- AWS credentials with the S3 Tables permissions the
  [target documentation](../../docs/targets/aws-s3-tables.md#awss3tablestargetconfiguration) lists.
  `AutoCreate` is on, so the first write creates the table bucket, the namespace and the table.

## 1. Start the PLCs

```shell
cd ci/omni-plc-sim
cargo build --release
target/release/omni-plc-sim --serve s7=10102 ads pccc
```

ADS and PCCC listen on their standard ports, 48898 and 44818. S7 listens on 10102, because ports below
1024 need root on Linux. Leave it running.

## 2. Install SFC

Install SFC as in the [Quickstart](../../README.md#1-install). On Linux and macOS:

```shell
curl -fsSL https://raw.githubusercontent.com/awslabs/industrial-shopfloor-connect/main/sfcup.sh | bash
```

That puts `sfc`, the released uberjar with every adapter and target, on your `PATH`.

## 3. Run SFC

In a second shell:

```shell
cd examples/uberjar-plc-sim-s3tables
export AWS_REGION=us-west-2
sfc -config plc-sim-to-s3tables.json -info
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

The S3 Tables target writes every 10 seconds. After the first write the table exists:

```shell
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET_ARN="arn:aws:s3tables:${AWS_REGION}:${ACCOUNT}:bucket/sfc-industrial-data-bucket"
aws s3tables list-tables --table-bucket-arn "$BUCKET_ARN" --namespace sfc
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
- **Uberjar style:** every adapter and target is named by its `FactoryClassName` alone, with no
  `JarFiles`.
- **More tags:** `omni-plc-sim --print-map <s7|ads|pccc>` lists every tag a PLC holds, with the address
  syntax SFC accepts.

## Clean up

Stop SFC and the simulator with Ctrl+C, then delete the table:

```shell
aws s3tables delete-table --table-bucket-arn "$BUCKET_ARN" --namespace sfc --name plc_signals
```

The bucket and the namespace are shared with `in-process-sim-s3tables`. Remove them, and the explorer, as
its [clean-up section](../in-process-sim-s3tables/README.md#clean-up) describes.
