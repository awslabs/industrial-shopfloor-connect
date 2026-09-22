# Uberjar OPC UA tests

Exercises OPC UA in **both directions** from the uberjar — SFC as an OPC UA *server*, and SFC as an
OPC UA *client*. Neither test needs a PLC or an AWS account.

| Config | Direction | What it needs |
|---|---|---|
| [`sim-to-opcua.json`](sim-to-opcua.json) | SFC **serves** OPC UA — simulated signals published on SFC's own server | nothing |
| [`umati-to-debug.json`](umati-to-debug.json) | SFC **reads** OPC UA — the umati sample server printed to the console | Docker |

The point of this example is the uberjar invocation and the configuration style it enables. Every
other in-process example deploys each component separately and points `JarFiles` at its `lib`
directory; here there is a single artifact and the components are found on its own classpath, so
**neither configuration contains a `JarFiles` entry**.

## Why this differs from the other in-process examples

| | Per-module deployment | Uberjar (this example) |
|---|---|---|
| Artifacts | one `tar.gz` per adapter/target, unpacked side by side | one `sfc-uberjar-<version>.jar` |
| Launch | `sfc-main/bin/sfc-main -config …` | `java -jar sfc-uberjar-<version>.jar -config …` |
| Config | `"JarFiles": ["${SFC_DEPLOYMENT_DIR}/opcua-target/lib"]` | **no `JarFiles`** — loaded from the jar's classpath |
| `SFC_DEPLOYMENT_DIR` | required | not used |

As [Running the SFC core process](../../docs/sfc-running-core-process.md#running-the-process-from-a-single-jar-file)
puts it: to load a component from the jar itself, simply omit the `JarFiles` entry.

The trade-off is worth knowing: because everything shares one flat classpath, every module in the
uberjar must agree on one version of every shared dependency. A component whose dependencies cannot
be reconciled with the rest of the product has to be deployed per-module or over IPC instead.

---

## 1. SFC as an OPC UA server — `sim-to-opcua.json`

```
 simulator adapter ──► SFC core ──► opcua-target ──► opc.tcp://localhost:4841/sfc
```

```shell
java -jar sfc-uberjar-<version>.jar -config sim-to-opcua.json -info
```

> Run from a writable working directory. The OPC UA target creates `issuers/`, `trusted/` and
> `rejected/` certificate directories, plus a self-signed server certificate and key, in the current
> directory on first start.

Six simulated channels, updated every 1000 ms, published under namespace `2:SFC`:

| Channel | Simulation | Data type | Range |
|---|---|---|---|
| `sinus` | Sinus | Double | 0–100 |
| `triangle` | Triangle | Double | 0–100 |
| `sawtooth` | Sawtooth | Double | 0–100 |
| `square` | Square | Double | 0–100 |
| `random` | Random | Byte | 0–100 |
| `counter` | Counter | Int | 0–1000 |

`AutoCreate: true` lets the target build the address space from the incoming data, so no `DataModels`
section is needed.

Connect any OPC UA client to:

```
opc.tcp://localhost:4841/sfc
```

An anonymous `None/None` endpoint is published, along with signed and encrypted variants for
`Basic128Rsa15`, `Basic256` and `Basic256Sha256`, and a discovery endpoint at
`opc.tcp://localhost:4841/sfc/discovery`. Change the port with `ServerTcpPort`.

Expected output:

```
INFO  - Creating an in-process reader for adapter "SimulatorAdapter" of protocol adapter type SIMULATOR
INFO  - Creating in process target writer for target ID OpcuaTarget
INFO  - Binding endpoint opc.tcp://localhost:4841/sfc to 0.0.0.0:4841 [None/None]
INFO  - Creating namespace 2:SFC for model SFC
INFO  - OPCUA server: 0 reads and 366 writes over the last 1m
```

---

## 2. SFC as an OPC UA client — `umati-to-debug.json`

The regular case: read an external OPC UA server and print the data. This uses the
[umati sample server](https://github.com/umati/Sample-Server), which offers a realistic machine
address space and needs only Docker.

```
 umati sample server ──► opcua adapter ──► SFC core ──► DebugTarget (stdout)
   (Docker, :4840)
```

```shell
# start the sample server
docker run -d -p 4840:4840 ghcr.io/umati/sample-server:main

# read it
java -jar sfc-uberjar-<version>.jar -config umati-to-debug.json -info
```

Nine channels — three from the standard OPC UA server object, six from the umati machine model:

| Channel | NodeId | Notes |
|---|---|---|
| `ServerStatus` | `ns=0;i=2256` | full `ServerStatusDataType` structure |
| `ServerTime` | `ns=0;i=2256` | same node, narrowed with `"Selector": "@.currentTime"` |
| `State` | `ns=0;i=2259` | server state enum |
| `AbsoluteErrorTime` | `ns=20;i=59217` | |
| `AbsoluteLength` | `ns=20;i=59235` | |
| `AbsoluteMachineOffTime` | `ns=20;i=59210` | |
| `AbsoluteMachineOnTime` | `ns=20;i=59219` | |
| `AbsolutePiecesIn` | `ns=20;i=59237` | |
| `FeedSpeed` | `ns=20;i=59208` | |

`ServerStatus` is worth noting: it returns a nested structure, so it also shows that the adapter
decodes `ExtensionObject` values rather than only scalars.

Expected output:

```
INFO  - Client for source "OPCUA-SOURCE" connected to opc.tcp://localhost:4840//
INFO  - {
  "schedule": "OpcuaSchedule",
  "sources": {
    "OPCUA-SOURCE": {
      "values": {
        "ServerStatus": { "value": { "currentTime": "...",
                                     "state": { "value": 0, "name": "Running" },
                                     "buildInfo": { "productName": "open62541 OPC UA Server", ... } } },
        "FeedSpeed": { "value": 250.0, "timestamp": "..." },
        ...
```

### Polling or subscription

The config ships with `"SourceReadingMode": "Polling"`, where SFC reads every node on each schedule
interval. Change one value to have the server push changes instead:

```json
"SourceReadingMode": "Subscription"
```

`SubscribePublishingInterval` (already present, 100 ms) then applies. The difference is visible in the
output: polling emits channels in configuration order sharing one read timestamp, while subscription
emits them in notification order, each carrying its own source timestamp from the server.

---

## Pointing the client at SFC's own server

The two configs can be combined to read SFC through SFC. Note the path — the target's default
`ServerPath` is `sfc`, so the endpoint is `…:4841/sfc`, not `…:4841/`:

```json
"OpcuaServers": {
  "SFC-OPCUA": {
    "Address": "opc.tcp://localhost", "Path": "/sfc", "Port": 4841, "ConnectTimeout": "10000"
  }
}
```

## See also

- [Running the SFC core process](../../docs/sfc-running-core-process.md) — the uberjar and its limits
- [OPC UA adapter](../../docs/adapters/opcua.md) — reading modes, events, filters and security
- [OPC UA target](../../docs/targets/opcua.md) — address space, security and data model options
- [Simulator adapter](../../docs/adapters/simulator.md) — all available simulation types
- [in-process-s7-opcua](../in-process-s7-opcua) — the same target in a per-module deployment
