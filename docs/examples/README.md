# Examples

Every example in [`examples/`](../../examples). The **Mode** column links to the
[deployment mode](../sfc-deployment.md#choose-a-deployment-mode) each one uses:

- **[in-process][m-inproc]** — adapters and targets run inside the `sfc-main` JVM, loaded from the
  `JarFiles` paths in the configuration
- **[IPC][m-ipc]** — they run as separate gRPC services; see
  [running adapters](../sfc-running-adapters.md) and [running targets](../sfc-running-targets.md)
- **[uberjar][m-uberjar]** — in-process from one jar that already contains every adapter and target,
  installed by [sfcup](../../README.md#1-install), so `AdapterTypes` and `TargetTypes` entries name
  their `FactoryClassName` only, with no `JarFiles`. The exception is `ConfigProvider` and
  `LogWriter`: SFC ignores them without the key, so give them `"JarFiles": []`. Components you build
  yourself keep their `JarFiles`.

Debug is listed where the example's schedule names a [Debug target][debug]. In many examples it is
commented out there (`"#DebugTarget"`); remove the `#` to print the data to the console.

**Windows:** every example README gives its OS-specific steps for Linux / macOS and for Windows
(PowerShell), or says that it is Linux-only. Run scripts come as `.sh` / `.bat` pairs
(`run-uberjar.sh` / `run-uberjar.bat`, `run-inprocess.sh` / `run-inprocess.bat`); on Windows run
the `.bat` from PowerShell, e.g. `.\run-uberjar.bat`. sfcup installs SFC as the `sfcx` command on
every OS. Platform limits: [Platform support](../README.md#platform-support).

## Start here

Every step needs Java 17+; **Needs** lists what else it takes.

| Step | Example | Needs |
|---|---|---|
| 1 | [Quickstart step 2](../../README.md#2-first-data--no-hardware-no-cloud): simulated signals printed to the console | SFC installed with [sfcup](../../README.md#1-install) |
| 2 | [Quickstart step 3](../../README.md#3-real-opc-ua-to-s3-tables): a real OPC-UA server into S3 Tables (Apache Iceberg) | Docker, an AWS account and the AWS CLI |
| 3 | [PLC simulator to file and S3 Tables][ex-plc-sim-s3tables]: S7, ADS and PCCC without hardware | A clone of this repository and Rust 1.98+ to build the simulator; AWS credentials only for the S3 Tables part |
| 4 | [Simulator to S3 Tables][ex-sim-s3tables]: one pipeline run in-process and from the uberjar | A clone of this repository and AWS credentials for S3 Tables |
| 5 | [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode): the same adapter and target as uberjar, in-process and IPC | SFC installed with [sfcup](../../README.md#1-install); the in-process part also downloads three release bundles |

## Protocol to AWS pipelines

| Example | Gist | Protocol adapter | Target | Mode |
|---|---|---|---|---|
| [Simulator to S3 Tables][ex-sim-s3tables] | High-frequency simulated machine tags into Apache Iceberg on S3 Tables, with tuning guidance for sustained writes. Ships an optional Cognito-secured web app that queries the tables with DuckDB in Lambda. Runnable either way — `run-inprocess.sh` / `run-inprocess.bat` with per-module `JarFiles`, or `run-uberjar.sh` / `run-uberjar.bat` with none — so the two deployment shapes sit side by side on one pipeline. | [Simulator][simulator] | [S3 Tables][s3tables], [Debug][debug] | [in-process][m-inproc] or [uberjar][m-uberjar] |
| [PLC simulator to file and S3 Tables][ex-plc-sim-s3tables] | No hardware needed. A Siemens S7-1500, a Beckhoff TwinCAT 3 and an Allen-Bradley MicroLogix 1400, all simulated by [`omni-plc-sim`](../../ci/omni-plc-sim/README.md), are read every 100 ms and written to the console, to local JSON files and to an Iceberg table on S3 Tables. Build omni-plc-sim with cargo, install SFC with `sfcup` (`sfcup.ps1` on Windows), run one configuration, then chart the table in the explorer of the Simulator to S3 Tables example. | [S7][s7], [ADS][ads], [PCCC][pccc] | [File][file], [S3 Tables][s3tables], [Debug][debug] | [uberjar][m-uberjar] |
| [OPC-UA to SiteWise][ex-opcua-sitewise] | Step-by-step workshop: OPC-UA server on EC2 into SiteWise, including asset models, assets and SiteWise Monitor dashboards. Linux-only by design: its commands run in an AWS Cloud9 terminal, and Cloud9 is no longer available to new customers; the example's README describes how to run it without Cloud9. | [OPC-UA][opcua] | [SiteWise][sitewise], [Debug][debug] | [in-process][m-inproc] |
| [OPC-UA to SiteWise Edge][ex-opcua-swedge] | OPC-UA (umati in Docker) to your own SiteWise Edge gateway (Greengrass V2 + EMQX) over MQTT/TLS, so it keeps working through intermittent connectivity. | [OPC-UA][opcua] | [SiteWise Edge][swedge], [Debug][debug] | [in-process][m-inproc] |
| [OPC-UA to MSK][ex-opcua-msk] | OPC-UA into an Amazon MSK topic with IAM authentication. In-process delivery does not work today: the MSK target cannot load its IAM authentication classes in-process, so nothing is written. Run it from the uberjar or use the IPC variant below. | [OPC-UA][opcua] | [MSK][msk], [Debug][debug] | [in-process][m-inproc] |
| [OPC-UA to MSK over IPC][ex-ipc-opcua-msk] | The same pipeline with the adapter and target split into separate gRPC services — the pattern for segregated OT/IT networks. | [OPC-UA][opcua] | [MSK][msk], [Debug][debug] | [IPC][m-ipc] |
| [OPC-UA to IoT Core with filters][ex-filters] | Reads a public OPC-UA demo server and publishes to IoT Core, demonstrating [metadata](../README.md#metadata), [transformations](../sfc-data-processing-filtering.md#transformations) and all three [filter types](../sfc-data-processing-filtering.md#data-filtering): [change](../core/change-filter-configuration.md), [value](../core/value-filter-configuration.md) and [condition](../core/condition-filter-configuration.md). | [OPC-UA][opcua] | [IoT Core][iotcore], [Debug][debug] | [uberjar][m-uberjar] |
| [Siemens S7 to SiteWise][ex-s7-sitewise] | S7 tags into SiteWise, with a variant that auto-creates the models and assets. | [S7][s7] | [SiteWise][sitewise], [Debug][debug] | [in-process][m-inproc] |
| [Siemens S7 to OPC-UA][ex-s7-opcua] | Republishes S7 tags as an OPC-UA server, either from an explicit data model or with an auto-created address space. Needs an S7-1200 PLC (DB120). | [S7][s7] | [OPC-UA][opcua-target], [Debug][debug] | [in-process][m-inproc] |
| [Beckhoff ADS to S3][ex-ads-s3] | Reads a Beckhoff controller over ADS/TCP and writes to S3. Includes the `main.tmc` declaring the variables, and channels for most TwinCAT data types plus the system symbols. | [ADS][ads] | [S3][s3], [Debug][debug] | [in-process][m-inproc] |
| [Beckhoff ADS to S3 over IPC][ex-ipc-ads-s3] | The same pipeline as separate gRPC services. | [ADS][ads] | [S3][s3], [Debug][debug] | [IPC][m-ipc] |
| [Rockwell PCCC to S3][ex-pccc-s3] | Reads an Allen-Bradley controller over PCCC and writes to S3. | [PCCC][pccc] | [S3][s3], [Debug][debug] | [in-process][m-inproc] |
| [Mitsubishi SLMP to S3][ex-slmp-s3] | SLMP into S3, split across six files (channels, structures, adapter and target types, a configuration template for the target, the IoT credentials client) to show `@file` [includes](../sfc-configuration.md#including-configuration-sections), [selective inclusion](../sfc-configuration.md#selective-inclusions) and [configuration templates](../sfc-configuration.md#configuration-templates). | [SLMP][slmp] | [S3][s3], [Debug][debug] | [in-process][m-inproc] |
| [Mitsubishi SLMP to S3 over IPC][ex-ipc-slmp-s3] | The same, with the adapter and target as gRPC services declared in a separate `servers.json`. | [SLMP][slmp] | [S3][s3], [Debug][debug] | [IPC][m-ipc] |

## Cloud to shop floor

| Example | Gist | Protocol adapter | Target | Mode |
|---|---|---|---|---|
| [IoT Core to OPC-UA write][ex-iot-opcua-write] | The reverse direction: subscribes to an MQTT topic and writes the received values to OPC-UA nodes on a server. Needs AWS IoT Core and an OPC UA server with a writable node. | [MQTT][mqtt] | [OPC-UA Writer][opcua-writer], [Debug][debug] | [in-process][m-inproc] |

## AWS IoT Greengrass deployments

| Example | Gist | Protocol adapter | Target | Mode |
|---|---|---|---|---|
| [Greengrass in-process][ex-gg-inproc] | Step-by-step lab deploying SFC as five Greengrass V2 components (sfc-main plus one per adapter and target); only sfc-main runs and loads the others' jars in one process. For Linux core devices; on Windows use the [Greengrass uberjar][ex-gg-uberjar] example. | [OPC-UA][opcua] | [S3][s3], [MQTT][mqtt-target] (to AWS IoT Core), [Debug][debug] | [in-process][m-inproc] |
| [Greengrass IPC][ex-gg-ipc] | The same lab with the adapter and targets as separate Greengrass components talking over gRPC. For Linux core devices; on Windows use the [Greengrass uberjar][ex-gg-uberjar] example. | [OPC-UA][opcua] | [S3][s3], [MQTT][mqtt-target] (to AWS IoT Core), [Debug][debug] | [IPC][m-ipc] |
| [Greengrass uberjar][ex-gg-uberjar] | Packages SFC as a single artifact jar, so the component runs on Windows and Linux with no container and nothing to unpack. Needs Java 17+ on the core device and a local MQTT broker on port 1883. | [MQTT][mqtt] | [Debug][debug] | [uberjar][m-uberjar] |

## Configuration providers

A [config provider](../sfc-extending.md#custom-configuration-handlers) supplies or rewrites the configuration SFC runs.

| Example | Gist | Protocol adapter | Target | Mode |
|---|---|---|---|---|
| [OPC-UA auto discovery][ex-opcua-discovery] | Browses the configured OPC-UA servers and generates the channel list for each source, so you do not have to enumerate nodes by hand. Nested nodes and a `Prefix` do not work yet: the provider joins their channel IDs with `/`, which SFC rejects (see the example's known limitation). | [OPC-UA][opcua] | [Debug][debug] | [in-process][m-inproc]; bundled in the [uberjar][m-uberjar] |
| [MQTT config provider][ex-mqtt-cfg] | Subscribes to an MQTT topic and accepts either a configuration payload or a pre-signed URL to download one — remote reconfiguration without touching the host. | — | — | [in-process][m-inproc]; bundled in the [uberjar][m-uberjar] |
| [YAML config provider][ex-yaml-cfg] | Lets you write SFC configurations in YAML instead of JSON; the bootstrap JSON only names the provider and the YAML file. | [OPC-UA][opcua] | [IoT Core][iotcore], [S3][s3], [Debug][debug] | [in-process][m-inproc]; bundled in the [uberjar][m-uberjar] |
| [Custom config provider template][ex-custom-cfg] | Minimal Kotlin skeleton to start your own provider from. | — | — | bundled in the [uberjar][m-uberjar] |

## Extending SFC

For custom protocol adapters and targets see [Extending SFC](../sfc-extending.md); every adapter under
[`adapters/`](../../adapters) and every target under [`targets/`](../../targets) is a working
implementation to start from, e.g. [`adapters/simulator`](../../adapters/simulator) and
[`targets/debug-target`](../../targets/debug-target).

| Example | Gist | Protocol adapter | Target | Mode |
|---|---|---|---|---|
| [Custom target formatter][ex-formatter] | Kotlin project for a [custom formatter](../sfc-extending.md#custom-formatters), to control exactly how target data is serialised. | — | — | bundled in the [uberjar][m-uberjar] |
| [Custom log writer][ex-logwriter] | Template for a [custom log writer](../sfc-extending.md#custom-logging) that routes SFC log output somewhere of your own choosing. | — | — | bundled in the [uberjar][m-uberjar] |

## Reference material

| Example | Gist | Protocol adapter | Target | Mode |
|---|---|---|---|---|
| [Transformation templates][ex-templates] | Ready-made target templates that turn SFC target data into CSV, XML and YAML, including an aggregated variant. See [target templates](../sfc-target-templates.md). | — | — | — |
| [Configuration signing][ex-sign] | Application that signs an SFC configuration, for [securing the configuration](../sfc-configuration.md#securing-the-configuration). | — | — | bundled in the [uberjar][m-uberjar] |
| [Self-signed test certificates][ex-certs] | Scripts that generate a CA plus server and client certificates for testing TLS between SFC components (gRPC IPC); see [securing component traffic](../sfc-securing-component-traffic.md). Testing only. Each first deletes `*.pem`, `*.srl` and `*.cnf` in the current folder, so run it in an empty one. `generate-test-certififcates.sh` (bash) on Linux and macOS, `generate-test-certificates.ps1` (Windows PowerShell 5.1, needs `openssl.exe`, for example from Git for Windows) on Windows. | — | — | — |
| [J1939 DBC file][ex-j1939] | An open-source J1939 DBC file to use with the [J1939 adapter][j1939]. | [J1939][j1939] (Linux only) | — | — |

<!-- examples -->
[ex-sim-s3tables]: ../../examples/in-process-sim-s3tables/README.md
[ex-plc-sim-s3tables]: ../../examples/uberjar-plc-sim-s3tables/README.md
[ex-opcua-sitewise]: ../../examples/in-process-opcua-sitewise/README.md
[ex-opcua-swedge]: ../../examples/in-process-opcua-sitewiseedge/README.md
[ex-opcua-msk]: ../../examples/in-process-opcua-msk/README.md
[ex-ipc-opcua-msk]: ../../examples/ipc-opcua-msk/README.md
[ex-filters]: ../../examples/opcua-to-iot-using-filters/README.md
[ex-s7-sitewise]: ../../examples/in-process-s7-sitewise/README.md
[ex-s7-opcua]: ../../examples/in-process-s7-opcua/README.md
[ex-ads-s3]: ../../examples/in-process-ads-s3/README.md
[ex-ipc-ads-s3]: ../../examples/ipc-ads-s3/README.md
[ex-pccc-s3]: ../../examples/in-process-pccc-s3/README.md
[ex-slmp-s3]: ../../examples/in-process-slmp-s3/README.md
[ex-ipc-slmp-s3]: ../../examples/ipc-slmp-s3/README.md
[ex-iot-opcua-write]: ../../examples/in-process-iot-core-opcua-write/README.md
[ex-gg-inproc]: ../../examples/greengrass-in-process/README.md
[ex-gg-ipc]: ../../examples/greengrass-ipc/README.md
[ex-gg-uberjar]: ../../examples/greengrass-uberjar/README.md
[ex-opcua-discovery]: ../../examples/opcua-auto-discovery/README.md
[ex-mqtt-cfg]: ../../examples/mqtt-config-provider/README.md
[ex-yaml-cfg]: ../../examples/yaml-custom-config-provider/README.md
[ex-custom-cfg]: ../../examples/custom-config-provider/README.md
[ex-formatter]: ../../examples/custom-target-formatter/README.md
[ex-logwriter]: ../../examples/custom-log-writer/README.md
[ex-templates]: ../../examples/transformation-templates/README.md
[ex-sign]: ../../examples/sign-sfc-config/README.md
[ex-certs]: ../../examples/test-certificates/README.md
[ex-j1939]: ../../examples/j1939dbc/README.md

<!-- deployment models -->
[m-inproc]: ../sfc-deployment.md#in-process
[m-ipc]: ../sfc-deployment.md#ipc
[m-uberjar]: ../sfc-deployment.md#uberjar

<!-- protocol adapters -->
[ads]: ../adapters/ads.md
[j1939]: ../adapters/j1939.md
[mqtt]: ../adapters/mqtt.md
[opcua]: ../adapters/opcua.md
[pccc]: ../adapters/pccc.md
[s7]: ../adapters/s7.md
[simulator]: ../adapters/simulator.md
[slmp]: ../adapters/slmp.md

<!-- targets -->
[debug]: ../targets/debug.md
[file]: ../targets/file.md
[iotcore]: ../targets/aws-iot-core.md
[msk]: ../targets/aws-msk.md
[mqtt-target]: ../targets/mqtt.md
[opcua-target]: ../targets/opcua.md
[opcua-writer]: ../targets/opcua-writer.md
[s3]: ../targets/aws-s3.md
[s3tables]: ../targets/aws-s3-tables.md
[sitewise]: ../targets/aws-sitewise.md
[swedge]: ../targets/aws-sitewiseedge.md
