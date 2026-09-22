# Examples

Every example in [`examples/`](../../examples). The **Mode** column links to the
[deployment model](../sfc-deployment.md) each one uses:

- **[in-process][m-inproc]** — adapters and targets run inside the `sfc-main` JVM, loaded from the
  `JarFiles` paths in the configuration
- **[IPC][m-ipc]** — they run as separate gRPC services; see
  [running adapters](../sfc-running-adapters.md) and [running targets](../sfc-running-targets.md)
- **[uberjar][m-uberjar]** — in-process from one jar that already contains every component, so the
  configuration needs no `JarFiles` at all

Most examples also wire up the [Debug target][debug] so you can see the data on the console; it is
listed only where it is part of the point.

## Protocol to AWS pipelines

| Example | Gist | Protocol adapter | Target | Mode |
|---|---|---|---|---|
| [Simulator to S3 Tables][ex-sim-s3tables] | High-frequency simulated machine tags into Apache Iceberg on S3 Tables, with tuning guidance for sustained writes. Ships an optional Cognito-secured web app that queries the tables with DuckDB in Lambda. Runnable either way — `run-inprocess.sh` with per-module `JarFiles`, or `run-uberjar.sh` with none — so the two deployment shapes sit side by side on one pipeline. | [Simulator][simulator] | [S3 Tables][s3tables], [Debug][debug] | [in-process][m-inproc] or [uberjar][m-uberjar] |
| [OPC-UA to SiteWise][ex-opcua-sitewise] | Step-by-step workshop: OPC-UA server on EC2 into SiteWise, including asset models, assets and SiteWise Monitor dashboards. | [OPC-UA][opcua] | [SiteWise][sitewise], [Debug][debug] | [in-process][m-inproc] |
| [OPC-UA to SiteWise Edge][ex-opcua-swedge] | The same ingestion, but to SiteWise Edge on-premises, so it keeps working through intermittent connectivity. | [OPC-UA][opcua] | [SiteWise Edge][swedge], [Debug][debug] | [in-process][m-inproc] |
| [OPC-UA to MSK][ex-opcua-msk] | OPC-UA into an Amazon MSK topic. | [OPC-UA][opcua] | [MSK][msk], [Debug][debug] | [in-process][m-inproc] |
| [OPC-UA to MSK over IPC][ex-ipc-opcua-msk] | The same pipeline with the adapter and target split into separate gRPC services — the pattern for segregated OT/IT networks. | [OPC-UA][opcua] | [MSK][msk], [Debug][debug] | [IPC][m-ipc] |
| [OPC-UA to IoT Core with filters][ex-filters] | Reads a public OPC-UA demo server and publishes to IoT Core, demonstrating [metadata](../README.md#metadata), [transformations](../sfc-data-processing-filtering.md#transformations) and all three filter types. | [OPC-UA][opcua] | [IoT Core][iotcore], [Debug][debug] | [in-process][m-inproc] |
| [Siemens S7 to SiteWise][ex-s7-sitewise] | S7 tags into SiteWise, with a variant that auto-creates the models and assets. | [S7][s7] | [SiteWise][sitewise], [Debug][debug] | [in-process][m-inproc] |
| [Uberjar OPC-UA tests][ex-uberjar-opcua] | Both OPC-UA directions run straight from the uberjar with a single `java -jar`, so neither configuration carries any `JarFiles`. `run-uberjar.sh server` publishes simulated signals as an OPC-UA server on port 4841 and needs no external system; `run-uberjar.sh client` reads the umati sample server in Docker and prints to the console. | [Simulator][simulator], [OPC-UA][opcua] | [OPC-UA][opcua-target], [Debug][debug] | [uberjar][m-uberjar] |
| [Siemens S7 to OPC-UA][ex-s7-opcua] | Republishes S7 tags as an OPC-UA server, either from an explicit data model or with an auto-created address space. | [S7][s7] | [OPC-UA][opcua-target], [Debug][debug] | [in-process][m-inproc] |
| [Beckhoff ADS to S3][ex-ads-s3] | Reads a Beckhoff controller over ADS/TCP and writes to S3. Includes the `main.tmc` declaring the variables, and one channel per supported address type. | [ADS][ads] | [S3][s3], [Debug][debug] | [in-process][m-inproc] |
| [Beckhoff ADS to S3 over IPC][ex-ipc-ads-s3] | The same pipeline as separate gRPC services. | [ADS][ads] | [S3][s3], [Debug][debug] | [IPC][m-ipc] |
| [Rockwell PCCC to S3][ex-pccc-s3] | Reads an Allen-Bradley controller over PCCC and writes to S3. | [PCCC][pccc] | [S3][s3], [Debug][debug] | [in-process][m-inproc] |
| [Mitsubishi SLMP to S3][ex-slmp-s3] | SLMP into S3, split across several configuration files — channels, structures, types and templates — and using the AWS IoT credentials provider rather than static keys. | [SLMP][slmp] | [S3][s3], [Debug][debug] | [in-process][m-inproc] |
| [Mitsubishi SLMP to S3 over IPC][ex-ipc-slmp-s3] | The same, with the adapter and target as gRPC services declared in a separate `servers.json`. | [SLMP][slmp] | [S3][s3], [Debug][debug] | [IPC][m-ipc] |

## Cloud to shop floor

| Example | Gist | Protocol adapter | Target | Mode |
|---|---|---|---|---|
| [IoT Core to OPC-UA write][ex-iot-opcua-write] | The reverse direction: subscribes to an MQTT topic and writes the received values to OPC-UA nodes on a server. | [MQTT][mqtt] | [OPC-UA Writer][opcua-writer], [Debug][debug] | [in-process][m-inproc] |

## AWS IoT Greengrass deployments

| Example | Gist | Protocol adapter | Target | Mode |
|---|---|---|---|---|
| [Greengrass in-process][ex-gg-inproc] | Step-by-step lab deploying SFC as a Greengrass V2 component, with everything in one process. | [OPC-UA][opcua] | [S3][s3], [IoT Core][iotcore], [Debug][debug] | [in-process][m-inproc] |
| [Greengrass IPC][ex-gg-ipc] | The same lab with the adapter and targets as separate Greengrass components talking over gRPC. | [OPC-UA][opcua] | [S3][s3], [IoT Core][iotcore], [Debug][debug] | [IPC][m-ipc] |
| [Greengrass uberjar][ex-gg-uberjar] | Packages SFC as a single artifact jar, so the component runs on Windows and Linux with no container and nothing to unpack. | [MQTT][mqtt] | [Debug][debug] | [uberjar][m-uberjar] |

## Configuration providers

A [config provider](../sfc-extending.md) supplies or rewrites the configuration `sfc-main` runs.

| Example | Gist | Protocol adapter | Target | Mode |
|---|---|---|---|---|
| [OPC-UA auto discovery][ex-opcua-discovery] | Browses the configured OPC-UA servers and generates the channel list for each source, so you do not have to enumerate nodes by hand. | [OPC-UA][opcua] | [Debug][debug] | [in-process][m-inproc] adapter, [IPC][m-ipc] target |
| [MQTT config provider][ex-mqtt-cfg] | Subscribes to an MQTT topic and accepts either a configuration payload or a pre-signed URL to download one — remote reconfiguration without touching the host. | — | — | — |
| [YAML config provider][ex-yaml-cfg] | Lets you write SFC configurations in YAML instead of JSON; the bootstrap JSON only names the provider and the YAML file. | [OPC-UA][opcua] | [S3][s3], [IoT Core][iotcore], [Debug][debug] | [in-process][m-inproc] |
| [Custom config provider template][ex-custom-cfg] | Minimal Kotlin skeleton to start your own provider from. | — | — | — |

## Extending SFC

| Example | Gist | Protocol adapter | Target | Mode |
|---|---|---|---|---|
| [Custom target formatter][ex-formatter] | Kotlin project for a [custom formatter](../sfc-extending.md#custom-formatters), to control exactly how target data is serialised. | — | — | — |
| [Custom log writer][ex-logwriter] | Template for routing SFC log output somewhere of your own choosing. | — | — | — |

## Reference material

| Example | Gist | Protocol adapter | Target | Mode |
|---|---|---|---|---|
| [Transformation templates][ex-templates] | Ready-made target templates that turn SFC target data into CSV, XML and YAML, including an aggregated variant. | — | — | — |
| [Configuration signing][ex-sign] | Application that signs an SFC configuration, for [securing the configuration](../sfc-configuration.md#securing-the-configuration). | — | — | — |
| [Self-signed test certificates][ex-certs] | Script that generates certificates for testing OPC-UA and gRPC security. Testing only. | — | — | — |
| [J1939 DBC file][ex-j1939] | An open-source J1939 DBC file to use with the [J1939 adapter][j1939]. | [J1939][j1939] | — | — |

Also worth starting with: the [Quickstart lab](../../README.md#quickstart) in the root README,
which walks OPC-UA to S3 end to end.

<!-- examples -->
[ex-sim-s3tables]: ../../examples/in-process-sim-s3tables/README.md
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
[ex-uberjar-opcua]: ../../examples/uberjar-opcua-tests/README.md
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
[m-inproc]: ../sfc-deployment.md#in-process-and-ipc-deployment-models
[m-ipc]: ../sfc-deployment.md#in-process-and-ipc-deployment-models
[m-uberjar]: ../sfc-deployment.md#single-file-deployments

<!-- protocol adapters -->
[ads]: ../adapters/ads.md
[j1939]: ../adapters/j1939.md
[mqtt]: ../adapters/mqtt.md
[opcua]: ../adapters/opcua.md
[pccc]: ../adapters/pccc.md
[s7]: ../adapters/s7.md
[simulator]: ../adapters/simulator.md
[slmp]: ../adapters/slmp.md
[sql]: ../adapters/sql.md

<!-- targets -->
[debug]: ../targets/debug.md
[iotcore]: ../targets/aws-iot-core.md
[msk]: ../targets/aws-msk.md
[opcua-target]: ../targets/opcua.md
[opcua-writer]: ../targets/opcua-writer.md
[s3]: ../targets/aws-s3.md
[s3tables]: ../targets/aws-s3-tables.md
[sitewise]: ../targets/aws-sitewise.md
[swedge]: ../targets/aws-sitewiseedge.md
