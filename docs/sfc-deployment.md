# SFC Deployment

- [Deployment options](#deployment-options)
- [Choose a deployment mode](#choose-a-deployment-mode)
- [Configuration in each mode](#configuration-in-each-mode)
- [Publish to AWS with sfcup](#publish-to-aws-with-sfcup)
  - [Container image in Amazon ECR](#container-image-in-amazon-ecr)
  - [AWS IoT Greengrass v2 component](#aws-iot-greengrass-v2-component)
- [SFC Control Plane](#sfc-control-plane)
- [Details wrt. In-process and IPC deployment models](#details-wrt-in-process-and-ipc-deployment-models)

## Deployment options

The SFC core module is implemented to run in a Java Virtual Machine (JVM). Input adapters and targets can be implemented for the JVM as well, or for other runtimes, depending on the platforms where these are deployed and the libraries required for the protocol implementation.

JVM implementations have the option to be loaded in the same process as the SFC Core. When other runtimes are used, any language can be used for the implementation. These adapters and targets run as separate processes and use streaming gRPC IPC to communicate with the SFC core.

The framework contains classes that speed up the development of JVM protocol and target services, as well as an abstraction layer for the gRPC IPC layer.

The components don't have any runtime environment-specific dependencies (the few OS limits are listed under [Platform support](./README.md#platform-support)). They can be deployed as:

- *Standalone applications* on target platforms supporting the JVM or runtimes used to implement additional adapters and targets.
  sfcup installs the uberjar and the `sfcx` command ([Quickstart](../README.md#1-install)).
- *AWS IoT Greengrass v2 components*. `sfcup.sh --aws-greengrass` (Windows: `sfcup.ps1 -AwsGreengrass`)
  creates one from the uberjar, for Linux and Windows core devices: [AWS IoT Greengrass v2 component](#aws-iot-greengrass-v2-component).
- *Docker* or *Kubernetes* containers. `sfcup.sh --aws-ecr` (Windows: `sfcup.ps1 -AwsEcr`) builds the `sfcx`
  image, which runs the core or any IPC service, and pushes it to Amazon ECR: [Container image in Amazon ECR](#container-image-in-amazon-ecr).
- *Launch packages* of the SFC Control Plane, which configures, runs and monitors SFC on Linux, macOS and
  Windows hosts from a web app in your AWS account: [SFC Control Plane](#sfc-control-plane).

## Choose a deployment mode

SFC runs its adapters and targets in one of three modes (`Uberjar`, `In-Process` or `IPC`). The mode decides where their code comes from and in which process it runs; schedules, sources, channels and transformations are configured the same way in all three, and the modes can be mixed in one configuration.

| | Uberjar | In-process | IPC |
|---|---|---|---|
| Processes | one: the core with every adapter and target | one: `sfc-main`, which loads each adapter and target from its own module bundle | the core (uberjar or `sfc-main`) plus one service per adapter or target, on the same or on other hosts |
| Artifacts to deploy | one, installed by [sfcup](../README.md#1-install) | `sfc-main` plus one bundle per adapter and target in use | the core, and on each service host the uberjar or the bundles of its services |
| `AdapterTypes` / `TargetTypes` entries | `FactoryClassName` only | `FactoryClassName` plus one `JarFiles` path per component | none; adapters and targets name an `AdapterServer` / `TargetServer` |
| Start | `sfcx -config <file>` | `sfc-main/bin/sfc-main -config <file>` (Windows: `java -cp`, see [In-process](#in-process)) | each service with `-port`, then the core |
| Dependency versions | one set, shared | independent per component, except for the libraries that `sfc-main` itself carries | independent per service when started from its bundle |
| Download size | about 240 MB, once | about 95-180 MB per module plus about 110 MB for `sfc-main`; each bundle carries its own copy of the shared libraries | the uberjar or the bundles, on each host that runs a service |
| Best for | getting started, single-host deployments, Greengrass components, CI | production images tuned to a site, and components with conflicting dependencies | flexible deployment on IT/OT networks, load spread over several hosts, non-JVM components |
| Example | [PLC simulator to file and S3 Tables](../examples/uberjar-plc-sim-s3tables/README.md) | [Simulator to S3 Tables](../examples/in-process-sim-s3tables/README.md) | [OPC-UA to MSK over IPC](../examples/ipc-opcua-msk/README.md) |

New to SFC? Start with the uberjar: the [Quickstart](../README.md#1-install) installs it and shows first data in a minute, and the [examples catalog](./examples/README.md#start-here) lists the next steps.

## Configuration in each mode

Every adapter and target has a type code, listed in [Protocol adapter types and classes](./sfc-running-adapters.md#protocol-adapter-types-and-classes) and [Target types and classes](./sfc-running-targets.md#target-types-and-classes). `AdapterType` and `TargetType` are mandatory in every mode and must equal that code, and in the uberjar and in-process modes the `AdapterTypes` and `TargetTypes` keys are the same code. Instance names, the keys under `ProtocolAdapters`, `Targets`, `Sources`, `AdapterServers` and `TargetServers`, are free.

Each mode is shown below with the [Quickstart `simulator.json`](../README.md#2-helloworld-simulator-example). Only the sections that differ are listed; the rest of the file stays as it is. All modes need a Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`).

### Uberjar

This is the default as shipped using sfcup. Every component is on the uberjar's classpath, so the type entries name `FactoryClassName` only:

```json
"Targets": {
  "DebugTarget": { "Active": true, "TargetType": "DEBUG-TARGET" }
},
"TargetTypes": {
  "DEBUG-TARGET": { "FactoryClassName": "com.amazonaws.sfc.debugtarget.DebugTargetWriter" }
},
"ProtocolAdapters": {
  "SimulatorAdapter": { "AdapterType": "SIMULATOR" }
},
"AdapterTypes": {
  "SIMULATOR": { "FactoryClassName": "com.amazonaws.sfc.simulator.SimulatorAdapter" }
}
```

```shell
sfcx -config simulator.json -info
```



Example: [PLC simulator to file and S3 Tables](../examples/uberjar-plc-sim-s3tables/README.md).

### In-process

`sfc-main` loads each component from its own module bundle, so each type entry adds the `lib` directory of that bundle in `JarFiles`:

```json
"TargetTypes": {
  "DEBUG-TARGET": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/debug-target/lib"],
    "FactoryClassName": "com.amazonaws.sfc.debugtarget.DebugTargetWriter"
  }
},
"AdapterTypes": {
  "SIMULATOR": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/simulator/lib"],
    "FactoryClassName": "com.amazonaws.sfc.simulator.SimulatorAdapter"
  }
}
```

Unpack the bundles `sfc-main`, `simulator` and `debug-target` into one directory, point `SFC_DEPLOYMENT_DIR` at it, and start `sfc-main`:

**Linux / macOS**

```shell
export SFC_DEPLOYMENT_DIR="$HOME/sfc"
mkdir -p "$SFC_DEPLOYMENT_DIR"
for m in sfc-main simulator debug-target; do
  curl -fsSL "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz" | tar -xzf - -C "$SFC_DEPLOYMENT_DIR"
done
"$SFC_DEPLOYMENT_DIR/sfc-main/bin/sfc-main" -config simulator.json -info
```

**Windows (PowerShell)**

```powershell
$env:SFC_DEPLOYMENT_DIR = "C:/sfc"
New-Item -ItemType Directory -Force C:\sfc | Out-Null
foreach ($m in "sfc-main", "simulator", "debug-target") {
    curl.exe -fsSL -o "C:\sfc\$m.tar.gz" "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz"
    tar -xf "C:\sfc\$m.tar.gz" -C C:\sfc
}
java -cp "C:\sfc\sfc-main\lib\*" com.amazonaws.sfc.MainController -config simulator.json -info
```

On Windows start `sfc-main` with `java -cp` as shown, not with `bin\sfc-main.bat`; see [Platform support](./README.md#platform-support). More on placeholders and `JarFiles`: [Running protocol adapters in-process](./sfc-running-adapters.md#running-protocol-adapters-in-process) and [Running targets in-process](./sfc-running-targets.md#running-targets-in-process).

Example: [Simulator to S3 Tables](../examples/in-process-sim-s3tables/README.md), which runs the same pipeline in-process and from the uberjar.

### IPC

Each adapter and target runs in its own service process. Remove `AdapterTypes` and `TargetTypes`, keep `AdapterType` and `TargetType`, and point the adapter and the target at a server entry:

```json
"Targets": {
  "DebugTarget": { "Active": true, "TargetType": "DEBUG-TARGET", "TargetServer": "DebugTargetServer" }
},
"TargetServers": {
  "DebugTargetServer": { "Address": "localhost", "Port": 50001 }
},
"ProtocolAdapters": {
  "SimulatorAdapter": { "AdapterType": "SIMULATOR", "AdapterServer": "SimulatorAdapterServer" }
},
"AdapterServers": {
  "SimulatorAdapterServer": { "Address": "localhost", "Port": 50000 }
}
```

Start each service in its own terminal, on the port of its server entry, and then the core. From the module bundles unpacked under [In-process](#in-process):

**Linux / macOS**

```shell
~/sfc/simulator/bin/simulator -port 50000
~/sfc/debug-target/bin/debug-target -port 50001
~/sfc/sfc-main/bin/sfc-main -config simulator.json -info
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\simulator\lib\*" com.amazonaws.sfc.simulator.SimulatorService -port 50000
java -cp "C:\sfc\debug-target\lib\*" com.amazonaws.sfc.debugtarget.DebugTargetService -port 50001
java -cp "C:\sfc\sfc-main\lib\*" com.amazonaws.sfc.MainController -config simulator.json -info
```

Or from the uberjar installed by sfcup, which contains every service:

**Linux / macOS**

```shell
java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.simulator.SimulatorService -port 50000
java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.debugtarget.DebugTargetService -port 50001
sfcx -config simulator.json -info
```

**Windows (PowerShell)**

```powershell
java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.simulator.SimulatorService -port 50000
java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.debugtarget.DebugTargetService -port 50001
sfcx -config simulator.json -info
```

The records now print in the terminal of the debug target service. The first values arrive about 10 seconds after the core starts, because an adapter service applies its configuration only when the core sends it for the second time. In `Address` use `localhost` or the address of the service host: services listen only on the address their host name resolves to, which is not necessarily `127.0.0.1`. Service options and current limitations: [Running SFC protocol adapters](./sfc-running-adapters.md#running-the-jvm-protocol-adapters-as-an-ipc-service) and [Running SFC targets](./sfc-running-targets.md#running-targets-as-an-ipc-service).

Example: [OPC-UA to MSK over IPC](../examples/ipc-opcua-msk/README.md).

## Publish to AWS with sfcup

sfcup can publish the uberjar to your AWS account instead of installing it. Both modes use the same
`sfc-uberjar.tar.gz` as the installer (the release, or `--local` / `-Local` for a source build), unpack it
into a scratch directory and install nothing locally. Both need the AWS CLI v2 with credentials;
`--dry-run` / `-DryRun` only prints the generated Dockerfile or recipe.

### Container image in Amazon ECR

Builds the `sfcx` image (Amazon Corretto 21, the uberjar in `/opt/sfc`) and pushes it to the ECR
repository `sfcx` (created if missing), tagged with the SFC version. Needs docker, podman or finch;
on Windows with Linux containers.

**Linux / macOS**

```shell
./sfcup.sh --aws-ecr --region eu-central-1
```

**Windows (PowerShell)**

```powershell
.\sfcup.ps1 -AwsEcr -Region eu-central-1
```

Options: `--repo` / `-Repo`, `--tag` / `-Tag`, `--platform` / `-Platform` (for example `linux/amd64`).
One image runs every variant:

| Run | Command |
|---|---|
| sfc-main (the default) | `docker run --rm -v "$PWD:/cfg" IMAGE -config /cfg/sfc-config.json -info` |
| sfc-main, configuration from `SFC_CONFIG` | `docker run --rm -e SFC_CONFIG="$(cat sfc-config.json)" IMAGE` |
| one IPC service | `docker run --rm -p 50000:50000 IMAGE ipc opcua -port 50000` |
| list the IPC services | `docker run --rm IMAGE ipc list` |
| usage | `docker run --rm IMAGE help` |

`ipc <service>` takes the module name (`simulator`, `opcua`, `s7`, `aws-s3-target`, `debug-target`, ...)
and starts its service class from the uberjar; `JAVA_OPTS` passes JVM options.

### AWS IoT Greengrass v2 component

Uploads the jar to S3 (bucket `sfcx-greengrass-<account>-<region>`, created if missing) and creates the
component `com.amazonaws.sfc.Sfcx`, version = the release version, for Linux and Windows core devices.
Its default configuration (`SfcConfig`) is the simulator to the debug target from the
[quickstart](../README.md#2-helloworld-simulator-example); the debug target writes to the component
log.

**Linux / macOS**

```shell
./sfcup.sh --aws-greengrass --region eu-central-1
```

**Windows (PowerShell)**

```powershell
.\sfcup.ps1 -AwsGreengrass -Region eu-central-1
```

Options: `--bucket` / `-Bucket`, `--component` / `-Component`, `--component-version` /
`-ComponentVersion` (`x.y.z`, each part at most 999999; a `--local` build gets
`0.<days since 1970>.<second of the day>`, because a component version can be created only once).

- The core device needs Java 17 or newer on the PATH of the Greengrass user; the install step checks it.
- Each time the component starts, the run step writes the configuration to `{work:path}/sfc-config.json`
  from the `SFC_CONFIG_JSON` environment variable (`printf` on Linux, `[IO.File]::WriteAllText` on
  Windows) and then starts sfc-main, so no shell ever parses the JSON.
- The token exchange role of the core device needs `s3:GetObject` on the bucket.
- Another SFC configuration: deploy the component with a configuration update that resets
  `/SfcConfig` and merges `{"SfcConfig": {...}}`.

## SFC Control Plane

The [SFC Agentic Control Plane](https://github.com/aws-samples/sample-sfc-agentic-control-plane), built by the
SFC team, manages the full lifecycle of SFC deployments from a serverless web app in your AWS account:

- **Configure:** edit SFC configurations in a JSON editor, or have an AI agent on Amazon Bedrock AgentCore
  generate them; the agent validates each configuration against the SFC specification it reads from this
  repository. Configurations are versioned, and one version is pinned for packaging.
- **Package:** a launch package is a zip with the configuration, an AWS IoT device certificate and role alias
  for short-lived AWS credentials, the runtime agent `aws-sfc-runtime-agent`, and launchers for Linux
  (`run.sh`), macOS (`run.command`) and Windows (`run.bat`). A package can also be registered as an AWS IoT
  Greengrass component for Linux core devices.
- **Run:** the launchers offer to install Amazon Corretto 21 and uv if they are missing. The runtime agent downloads
  `sfc-main` and the module bundles that the configuration names from this repository's GitHub releases, and
  runs SFC in [in-process](#in-process) mode.
- **Operate:** heartbeats, logs in Amazon CloudWatch and live channel values show up in the web app. From
  there you push a new configuration version, restart SFC or switch it to trace logging, without logging in
  to the host.
- **Fix:** from the error lines in the logs, the AI agent proposes a corrected configuration, shown as a diff.

It is deployed with the AWS CDK, see its
[Deployment & Quickstart](https://github.com/aws-samples/sample-sfc-agentic-control-plane#deployment--quickstart).

## Details wrt. In-process and IPC deployment models

Protocols, adapters, and targets can be implemented as jar files containing Java bytecode. These can be configured to be loaded and executed in the SFC core process. The configuration for each adapter or target type includes:

- A list of jar files (`JarFiles`) that are explicitly loaded by the SFC core process. It is left out when the component is already on the classpath of the core, as in the [uberjar](#uberjar).
- The name of a static factory class that implements a method called 'newInstance'.

The 'newInstance' method is called by the core to create a new instance. The configuration is passed to this method and is used to initialize the adapter or target instance.

This approach allows for flexible and modular implementation of protocols, adapters, and targets within the SFC core process.

<p align="center">
<img src="img/fig07.png" width="35%"/>


<p align="center">
    <em>SFC In-process deployment (e.g. in a single host context)</em>


As an alternative, components can be deployed to run in their own processes and communicate with the core using gRPC. This deployment model allows for the following scenarios:

- Non-JVM execution environments or languages to build/execute components
- Flexible deployment on IT/OT networks
- Distribution of load over multiple systems
- Application of lifecycle control with Greengrass v2 or Docker/Kubernetes

When the processes running the adapter or target services are started, a port number is passed as a parameter on which the service listens for requests from the core. Alternatively, the path to a configuration file can be used, from which the process will retrieve the port number (an adapter service then also needs the `-adapter` parameter to select its adapter, and a target service the `-target` parameter if the configuration file contains more than one active target).

During initialization, the SFC core sends an initialization request to the protocol source and/or target servers, containing only the sections of its configuration used by that adapter or target. When the configuration is modified and the core process is restarted, it sends an initialization request to each adapter or target with the newly updated subset of relevant configuration data. Adapter services may currently keep their previous configuration in that case; restart them as well.

If an adapter or target server is stopped, it will be detected by the SFC Core. The core will attempt to reconnect to the service and send an initialization request when it succeeds in connecting to a new instance of the server.

As the SFC core acts as the provider for configuration data to the servers, these will always work with the latest and consistent configuration data from a single source. No additional configuration files need to be distributed to the protocol and adapter processes.



<p align="center">
<img src="img/fig08.png" width="50%"/>


<p align="center">
    <em>SFC IPC deployment (e.g. in a distributed OT/IT context)</em>


See Also:

- [Running the SFC core process](./sfc-running-core-process.md) — the command-line options of `sfcx` and `sfc-main`
- [Running SFC protocol adapters - IPC mode](./sfc-running-adapters.md)
- [Running SFC targets - IPC mode](./sfc-running-targets.md)
- In-process example: [Simulator to S3 Tables](../examples/in-process-sim-s3tables/README.md), in-process and from the uberjar
- IPC examples: [OPC-UA to MSK](../examples/ipc-opcua-msk/README.md), [ADS to S3](../examples/ipc-ads-s3/README.md), [SLMP to S3](../examples/ipc-slmp-s3/README.md)
- [Uberjar PLC simulator example](../examples/uberjar-plc-sim-s3tables/README.md) — S7, ADS and PCCC from `omni-plc-sim` to a file and S3 Tables
- [SFC Agentic Control Plane](https://github.com/aws-samples/sample-sfc-agentic-control-plane) — manages the full lifecycle of SFC deployments, see [SFC Control Plane](#sfc-control-plane)
- All examples: [examples catalog](./examples/README.md)


