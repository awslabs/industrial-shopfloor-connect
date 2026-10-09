# Writing test cases

This is the reference for the end-to-end suite: the harness in `ci/e2e/lib` and the cases in
`ci/e2e/cases`. For what the CI system is, how to deploy it and how a run works, see
[ci/README.md](../README.md).

## Code map

```
ci/
├── README.md                the CI overview: what it is, deploy, how a run works
├── start-build.sh           package the working tree → S3, make sure the CI image exists, start the build
├── wait-build.sh            follow a build; stops it on Ctrl-C or when the GitHub job is cancelled
├── cdk/                     the AWS test backend, one stack
│   ├── bin/app.ts           context: githubRepo, oidcProviderArn, mskIngressCidrs
│   ├── lib/sfc-it-stack.ts  destinations, fixtures, CodeBuild projects, CI role, janitor
│   ├── lib/buildspec.ts     what the test build runs
│   ├── image/Dockerfile     the build image (built in AWS, no local Docker needed)
│   ├── lambda/              janitor.py (teardown), evidence.py (observer for the Lambda target), msk_public.py
│   └── test/stack.test.ts   synth-time regression tests of the stack
├── omni-plc-sim/            the PLC simulator (Rust): S7, ADS, PCCC, SLMP and Modbus TCP, built in AWS
├── e2e/                     the suite
│   ├── run.py               entry point (lib/runner.py)
│   ├── cases/<group>/<area>.json   the cases, one file per area
│   ├── lib/                 the harness, below
│   ├── counterparts/        local stand-ins: tcpgate, silent, http_fake, opcua_server, modbus_server, aws_wire_stub, publish
│   ├── selftest/            harness unit tests, the deployment-rule check over every case, the janitor's scoping
│   └── untestable.json      what cannot be tested here, listed in every report
└── e2e-support/             :ci:e2e-support - E2eMetricsWriter and E2eLineFormatter, loaded into SFC by the cases
```

| Harness module (`ci/e2e/lib/`) | Responsibility |
|---|---|
| `runner.py` | Case discovery, the life of one unit, lanes, gates, collection, verdicts, report writing |
| `deploy.py` | Turns a case into a process plan per mode. `check()` enforces the deployment rules. |
| `sfcproc.py` | Starting and stopping processes, IPC readiness, `PortGuard` for the fixed IPC ports |
| `sinks/` | Read-back, one module per destination kind |
| `services.py` | Counterparts, with ports the runner allocates |
| `steps.py` | The timeline: waits and actions |
| `asserts.py` | Assertion kinds |
| `metrics.py` | SFC's own metrics, as E2eMetricsWriter wrote them |
| `report.py`, `evidence.py` | REPORT.md and junit.xml; the incremental upload to S3 |
| `cleanup.py`, `kafka_admin.py`, `pki.py`, `stackenv.py`, `artifacts.py` | Per-run AWS cleanup, MSK topics, the run's certificates, stack values, unpacked tarballs |

## Cases

Cases live in **one file per area**: `ci/e2e/cases/<group>/<area>.json` holds `{"cases": [...]}`. The
groups are `core`, `adapters`, `targets`, `aws` and `crosscutting`.

A case holds its SFC configuration once per mode it runs in, each in **that deployment's own style**,
exactly as in `examples/`. The runner merges the mode's section into `config` (an RFC 7386 merge patch)
and runs the result unchanged. A case runs in exactly the modes it has a section for.

```json
{
  "id": "AWS-SQS-01", "title": "...", "intent": "why it matters, how it proves it, how it fails",
  "tier": "aws", "priority": "P0", "pins": ["targets/aws-sqs-target/.../AwsSqsTargetWriter.kt:218"],
  "sinks": {"main": {"kind": "sqs"}}, "records": 6, "timeoutSeconds": 90,
  "assert": [{"kind": "channelValueRun", "source": "sim", "channel": "ctr"}],
  "config":    {"Schedules": [...], "Sources": {...}, "Targets": {...}, "Metadata": {"marker": "${SFC_E2E_MARKER}", "...": "..."}},
  "uberjar":   {"TargetTypes": {"AWS-SQS": {"FactoryClassName": "com.amazonaws.sfc.awssqs.AwsSqsTargetWriter"}}},
  "inprocess": {"TargetTypes": {"AWS-SQS": {"FactoryClassName": "...", "JarFiles": ["${SFC_DEPLOYMENT_DIR}/aws-sqs-target/lib"]}}},
  "ipc":       {"Targets": {"Sqs": {"TargetServer": "SqsServer"}},
                "TargetServers": {"SqsServer": {"Address": "${SFC_E2E_IPC_HOST}", "Port": 50001}}},
  "ipcServices": {"SqsServer": {"module": "aws-sqs-target"}}
}
```

### The deployment rules

`lib/deploy.py:check` enforces these rules, and the selftests run it over every case.

| Section | Style | Like |
|---|---|---|
| `config` | What all modes share: schedules, sources, adapter and target settings, metadata | |
| `uberjar` | `AdapterTypes`/`TargetTypes` with `FactoryClassName` only; no `JarFiles`, no servers | `examples/uberjar-*` |
| `inprocess` | The same, plus `"JarFiles": ["${SFC_DEPLOYMENT_DIR}/<module>/lib"]` for every `FactoryClassName` | `examples/in-process-*` |
| `ipc` | No types. `"AdapterServer"`/`"TargetServer"` on each adapter and target. `AdapterServers`/`TargetServers` entries `{"Address": "${SFC_E2E_IPC_HOST}", "Port": 50000}`, with fixed ports from 50000: adapter servers first, then targets. | `examples/ipc-*` |

**Inside a process.** The metrics writer, a `Formatter`, `LogWriter` or `ConfigProvider` always run
inside a process. So in in-process and IPC mode they carry `JarFiles` too.

**IPC.**
- `ipcServices` names the module that serves each server:
  `{"<Server>": {"module": "simulator", "args": [...]}}`.
- `args` takes the documented service options, for example `-connection ServerSideTLS -cert ... -key ...`.
  Put the matching `ConnectionType` and certificate keys on the server entry.

**Uberjar extras.** `uberjarClasspath: ["<glob>.jar" | "module:<tarball>"]` adds extension jars to `-cp`.

**Fixtures.** `files: {"<path>": "<text>"}` holds included configs, templates, SQL and counterpart
specs. They are written into `${SFC_E2E_CASE_DIR}`.

**The marker.** `config.Metadata` carries `{runId, case, mode, marker}` as placeholders. Every record
then has `$.metadata.marker`, and sinks on shared destinations keep only their own case run's records.
Where a record cannot carry metadata, put the marker into a data value:
- SiteWise: the `label` property;
- S3 Tables: the `label` column;
- Kafka with protobuf: a header.

**Metrics.** Use `com.amazonaws.sfc.e2e.E2eMetricsWriter` as the metrics writer, with
`"JarFiles": ["${SFC_E2E_SUPPORT_JAR}"]` in in-process and IPC.

### Values the run provides

These are `${...}` placeholders. SFC substitutes them itself, and sink specs get them expanded too.

| Placeholder | Value |
|---|---|
| `${SFC_E2E_MARKER}`, `${SFC_E2E_RUN_ID}`, `${SFC_E2E_CASE}`, `${SFC_E2E_MODE}` | this case run's identity; the marker is `<run>_<case>_<ip\|ipc\|uj>` |
| `${SFC_DEPLOYMENT_DIR}`, `${SFC_E2E_SUPPORT_JAR}`, `${SFC_E2E_REPO}` | unpacked tarballs; the e2e-support jar; the repository root |
| `${SFC_E2E_IPC_HOST}` | the address the IPC services listen on |
| `${SFC_E2E_SINK}`, `${SFC_E2E_SINK_<NAME>}`, `${SFC_E2E_DIR_<NAME>}` | file-sink directories; extra `dirs` |
| `${SFC_E2E_<SERVICE>_PORT}`, `${SFC_E2E_DEAD_PORT}` | a counterpart's port; a port nothing listens on |
| `${SFC_E2E_PKI}` | the run's CA, server, client and rogue certificates, with PKCS#8 keys |
| `${SFC_E2E_CASE_DIR}` | the case's fixture directory |
| exported by sinks | `${SFC_E2E_SQS_QUEUE_URL}` (the run's own queue), `${SFC_E2E_S3_PREFIX}`, `${SFC_E2E_KAFKA_BOOTSTRAP}`, `${SFC_E2E_KAFKA_TOPIC}`, `${SFC_E2E_IOT_TOPIC_ROOT}`, `${SFC_E2E_IOT_TOPIC}` |
| stack values | `${SFC_E2E_BUCKET}`, `${SFC_E2E_REGION}`, `${SFC_E2E_SNS_TOPIC_ARN}`, `${SFC_E2E_KINESIS_STREAM}`, `${SFC_E2E_FIREHOSE_STREAM}`, `${SFC_E2E_LAMBDA_FUNCTION}`, `${SFC_E2E_S3T_*}`, `${SFC_E2E_SW_*}`, ...; the full list is the stack's `E2eEnvironment` output |

### Case keys

| Key | Meaning |
|---|---|
| `id`, `title`, `intent`, `pins` | The id is unique. The intent says why the behaviour matters, how the case proves it and how it fails. The pins are the `file:line` the case is grounded in. |
| `tier` | `core` (nothing external), `local-infra` (counterparts), `aws` (the stack) |
| `priority` | `P0` (push must never lose it), `P1` (push), `P2` (full only) |
| `records`, `gate`, `gates` | `records: N` is short for one gate of N records in sink `main`. A gate is `{"sink", "records", "timeoutSeconds", "orExit"}`. |
| `sinks`, `services`, `steps`, `dirs`, `env`, `requires` | Read-back, counterparts, the timeline, extra directories and environment, and the binaries or `python:<module>` the case needs |
| `assert`, `knownDefect` | Assertions, evaluated after collection; a defect pin |
| `allowWriteErrors` | `true`, or a list of targets allowed to report `WriteError` |
| `expectStartupFailure` | SFC must exit on its own; assert on `exitCode` and the logs |
| `failFast` | Log texts that fail a gate at once. The default is component construction errors; use `[]` when the case expects them. |
| `cliLogLevel`, `cliArgs`, `cliNoConfig`, `cliColor` | The sfc-main command line. The CLI log level overrides `LogLevel` in the config. |
| `timeoutSeconds`, `modeParity`, `offlineSeconds`, `offlineExpectWrite` | Gate and wait default (60 s); inclusion in the cross-mode comparison; the `--offline-aws` smoke |

### Sinks: where the delivered records are read back

| Kind | Spec | Reads |
|---|---|---|
| `file` | `{}` | The directory a file target writes (`${SFC_E2E_SINK}`); JSON, gzip, zip; in write order |
| `debug` | `{"target": "Dbg"}` | The debug target's records, from the log of the process that hosts it |
| `sqs` | `{}` | The case run's own queue `sfc-it-<marker>`: created before SFC starts, read to the end after it stops, then deleted |
| `sns` | `{}` | The stack topic's raw-delivery queue, filtered by marker, drained after the stop |
| `iot` | `{}` or `{"retainedTopic": "sfc/it/<marker>/data"}` | The topic rule's queue (publish under `${SFC_E2E_IOT_TOPIC_ROOT}`), or the retained message |
| `s3` | `{}` | The run's own prefix `${SFC_E2E_S3_PREFIX}` |
| `kinesis` | `{}` | The shared stream from just before the case started, filtered by marker |
| `firehose`, `lambda` | `{}` | The delivered objects; for Lambda, what the evidence function received |
| `s3tables` | `{"table": "sim_a"}`; `namespace`/`bucket` may contain `<marker>`, `<run>`, `<mode>` | A pyiceberg scan where `label = marker` |
| `sitewise` | `{"aliasPrefix": "${SFC_E2E_SW_ALIAS_A1}"}` or `{"assetName": "sfc-it-<marker>-..."}`; `"completeRows": true` counts only rows with every property visible | Property history by asset and property id, joined by timestamp, filtered by `label` |
| `kafka` | `{"format": "json" \| "raw" \| "headers"}` | The case's own MSK topic, read to its end offset; `headers` for binary (protobuf) values |
| `mqtt`, `nats` | `{"service": "broker", "topic": "sfc/#"}`, `{"service": "nats", "subject": ">"}` | A subscriber connected before SFC starts |
| `opcua`, `opcua-writes` | `{"port": "SFC_E2E_OPCUA_PORT", "nodes": {...}}`, `{"service": "opcua"}` | Polls the server opcua-target serves; what opcua-writer-target wrote |
| `aws-stub`, `aws-stub-requests`, `jsonl` | `{"service": "stub"}`, `{"service": "rest", "file": "requests.jsonl"}` | What the wire stub accepted, or every request with its attempt number; any counterpart's JSON-lines log |

Every sink takes `"anyMarker": true` to turn marker filtering off.

### Services: counterparts

The runner allocates every service's ports and exports them as `SFC_E2E_<NAME>_PORT`.

| Kind | Args | Notes |
|---|---|---|
| `mosquitto` | `tls: "server"\|"mutual"` | TLS port `SFC_E2E_<NAME>_TLS_PORT`, using the run PKI |
| `nats` | `extra: [...]` | nats-server arguments |
| `tcpgate` | `to: <service>` or `toPort` | A forwarder for deterministic outages: `gate-close` drops and refuses connections, `gate-open` restores them |
| `silent` | — | Accepts and never answers, for timeouts |
| `http` | `scenario: file.json` | A scripted REST server; logs `requests.jsonl` |
| `opcua-server` | `spec: file.json` | An asyncua server with counters, writable nodes and events; logs `writes.jsonl` |
| `plc-sim` | `protocol: s7\|ads\|pccc\|slmp\|modbus`, `profile`, `config: sim.toml` | omni-plc-sim: a simulated PLC with static tags of every type and fast-changing signals; every request goes to `events.jsonl`, readable with a `jsonl` sink. Maps: `omni-plc-sim --print-map <protocol>` |
| `modbus`, `snmpd` | `spec: file.json`, `conf: file` | A pymodbus server with a fixed register map; a net-snmp agent on UDP |
| `postgres` | `sql: file.sql` | One cluster per run and one database per case run (`SFC_E2E_<NAME>_DB`, user and password `sfc_e2e`) |
| `aws-wire-stub` | `spec: file.json` | The SQS and Firehose wire protocols, with scripted throttling, 5xx, partial failure and delay |
| `sfc` | `config: file.json` | A second SFC (uberjar) as a counterpart |
| `command` | `argv: [...]`, `readyLog`, `listens` | Anything else; `python` and `${COUNTERPARTS}` expand |

### Steps: a timeline while SFC runs

```json
"steps": [
  {"wait": {"sink": "main", "records": 5}},
  {"do": "gate-close", "service": "gate"},
  {"do": "mark", "name": "closed"},
  {"wait": {"files": {"dir": "buffer", "min": 3}}},
  {"do": "gate-open", "service": "gate"},
  {"wait": {"any": [{"sink": "main", "records": 20}, {"log": "some text", "count": 3}]}}
]
```

- **Waits** are on conditions: `sink`/`records` (with `where`), `files`, `log` (with a count and a
  process), `metric` (source, name, op, value), `exit`, and `any` of these.
  - `seconds` exists only as a settle step, and it must carry a `comment` saying why no condition works.
- **Actions:**
  - `start`, `stop` and `restart` a service;
  - `gate-close`, `gate-open`;
  - `sigterm`, `sigkill`;
  - `restart-sfc`;
  - `mark`;
  - `update-config` (a live reload);
  - `write-file`;
  - `run` (a command run to completion).

### Assertions

Every record assertion takes `sink`, `where: {"path": value}` and `comment`.

| Group | Kinds |
|---|---|
| Records | `recordCount`, `everyRecord` (`equals`/`in`/`regex`/`type`), `keysAbsent`, `keyOrder`, `keySet`, `deepEquals`, `pathsEqual`, `distinct`, `noDuplicates`, `serialSet` (two sinks), `cycle`, `tsDelta`, `valueSet` |
| Channels | `channelSequence` (ordered transports only), `channelValueRun` (a contiguous set in any order), `channelValueSet`, `channelValueIn`, `channelNumericRange` |
| Logs and exit | `logContains`, `logAbsent`, `logCount`, `logRegex`, `exitCode`. They cover every SFC process on both streams; narrow them with `process` and `stream`. |
| Metrics | `metric` (`op`, `value`), `metricRatio`, `metricAbsent` |
| Files | `rawContains`, `rawAbsent`, `fileNameRegex`, `fileCount`, `fileRecordCount`, `zipEntries`, `dirFiles`, `xmlPath` |
| Timeline | `markDelta` |

Two rules keep assertions honest:
- **Count, don't time.** The simulator is deterministic in its number of reads, and gates count records.
- **Order only where the transport keeps it.** Files, the debug target, one MQTT topic and a Kafka
  partition keep order. Queues, SNS, Firehose and Lambda do not, so use `channelValueRun` there.

### Known defects: pin, don't fix

When SFC is wrong today:
- `assertCorrect` holds the correct behaviour;
- `assertCurrent` holds today's behaviour;
- `summary` says what is wrong, and `ref` says where.

```json
"knownDefect": {
  "ref": "core/sfc-core/src/main/kotlin/com/amazonaws/sfc/transformations/Log2.kt:21",
  "summary": "Log2 applies ln() to every non-Float input",
  "assertCurrent": [{"kind": "channelValueSet", "source": "sim", "channel": "eight", "values": [2.0794415416798357], "tolerance": 1e-12}],
  "assertCorrect": [{"kind": "channelValueSet", "source": "sim", "channel": "eight", "values": [3.0], "tolerance": 1e-12}]
}
```

- The default run asserts `assertCurrent`, so the suite stays green.
- `--known-defects assert-correct` must make every pinned case fail. That proves each pin discriminates.
- When the defect is fixed, the case goes red. Then fold `assertCorrect` into `assert`.
- Pin only what you have confirmed in the code, and cite the line.
- A timeline that must serve both outcomes uses an `any` wait.

### Checklist

1. Ground the case: put the `file:line` of the behaviour in `pins`.
2. Make it deterministic: drive it with simulator counters or a counterpart with fixed data, and use
   per-record buffering (`BufferSize`/`BatchSize`/`BufferCount` 1, or the target's equivalent).
3. Give it every mode it can run in. The build's selftests (step [13] in ci/README.md) reject a configuration that breaks
   the deployment rules.
4. For a negative or defect case, break the expectation once and watch it fail.
