# SFC Example in process configuration for AWS IoT Core to OPC UA Write

The file [`iot-core-opcua-write.json`](iot-core-opcua-write.json) contains an example template for reading data from a 
AWS IoT Core topic and writing the received value to a tag of an OPCUA Server. This sample could be used for integrating cloud-side generated set points to control systems at a plant level.

It needs an OPC UA server with a writable node: the `OPCUAWrite` target connects to
`opc.tcp://localhost:4840/myopcua/server/` and writes the received temperature to the node `ns=2;i=2`. Change
`Address`, `Port`, `Path` and `NodeId` of the `OPCUAWrite` target for your server.
&nbsp;

In order to use the configuration, make the changes described below and
use it as the value of the `-config` parameter when starting sfc-main, as
shown under [Run SFC from deployment directory](#run-sfc-from-deployment-directory).

A debug target is included in the example to optionally write the output
to the console.
&nbsp;  
&nbsp;  


## Deployment directory

The `JarFiles` entries and the certificate paths of the configuration use
the placeholder `${SFC_DEPLOYMENT_DIR}`, which SFC replaces with the value
of the environment variable `SFC_DEPLOYMENT_DIR`. Point it at the directory
into which you unpack the module bundles `sfc-main`, `debug-target`,
`opcua-writer-target` and `mqtt` of the
[latest release](https://github.com/awslabs/industrial-shopfloor-connect/releases/latest)
(for another layout, change the `JarFiles` paths); the certificates go into
its `certs` folder. `sfc-main` needs a Java 17 (or newer) runtime (Windows:
`winget install EclipseAdoptium.Temurin.17.JDK`). More about this mode:
[In-process](../../docs/sfc-deployment.md#in-process).

**Linux / macOS**

```shell
export SFC_DEPLOYMENT_DIR="$HOME/sfc"
mkdir -p "$SFC_DEPLOYMENT_DIR/certs"
for m in sfc-main debug-target opcua-writer-target mqtt; do
  curl -fsSL "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz" | tar -xzf - -C "$SFC_DEPLOYMENT_DIR"
done
```

**Windows (PowerShell)**

```powershell
$env:SFC_DEPLOYMENT_DIR = "C:/sfc"
New-Item -ItemType Directory -Force C:\sfc\certs | Out-Null
foreach ($m in "sfc-main", "debug-target", "opcua-writer-target", "mqtt") {
    curl.exe -fsSL -o "C:\sfc\$m.tar.gz" "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz"
    tar -xf "C:\sfc\$m.tar.gz" -C C:\sfc
}
```

## Update AWS IoT Core endpoint configuration
Replace the placeholders in the EndPoint configuration with your AWS account specific endpoint information.
You can retrieve your endpoint by running the aws cli command:  `aws iot describe-endpoint --endpoint-type iot:Data-ATS`.
Keep the `ssl://` prefix in front of the endpoint.

```json
      "Brokers": {
        "default-broker": {
          "EndPoint": "ssl://XXX-ats.iot.XXX.amazonaws.com"
        }
      }
```

## Configure IoT Credentials
Follow the instructions for creating a new thing in the AWS IoT Core [`Documentation`](https://docs.aws.amazon.com/iot/latest/developerguide/iot-quick-start.html). You will create a new IoT Thing and download its connection kit, which will include files that you will need in the next step.
The policy of the thing's certificate must allow `iot:Connect` on `client/MqttAdapter-*` (the adapter connects with a
client ID that starts with `MqttAdapter-`), `iot:Subscribe` on `topicfilter/temperature` and `iot:Receive` on
`topic/temperature`.
Finally, download the [`Amazon Root CA`](https://www.amazontrust.com/repository/AmazonRootCA1.pem) and move the CA file and the things cert and key to the local folder that is referenced in the broker configuration.
In the terminal in which you set `SFC_DEPLOYMENT_DIR`, from the folder with the connection kit (replace
`<thing>` with the name of the kit's files):

**Linux / macOS**

```shell
curl -fsSL -o "$SFC_DEPLOYMENT_DIR/certs/AmazonRootCA1.pem" https://www.amazontrust.com/repository/AmazonRootCA1.pem
cp <thing>.cert.pem "$SFC_DEPLOYMENT_DIR/certs/sfc.cert.pem"
cp <thing>.private.key "$SFC_DEPLOYMENT_DIR/certs/sfc.private.key"
```

**Windows (PowerShell)**

```powershell
curl.exe -fsSL -o C:\sfc\certs\AmazonRootCA1.pem https://www.amazontrust.com/repository/AmazonRootCA1.pem
Copy-Item <thing>.cert.pem C:\sfc\certs\sfc.cert.pem
Copy-Item <thing>.private.key C:\sfc\certs\sfc.private.key
```

```json
      "Brokers": {
        "default-broker": {
          "Certificate": "${SFC_DEPLOYMENT_DIR}/certs/sfc.cert.pem",
          "PrivateKey": "${SFC_DEPLOYMENT_DIR}/certs/sfc.private.key",
          "RootCA": "${SFC_DEPLOYMENT_DIR}/certs/AmazonRootCA1.pem"
        }
      }
```

See [MqttBrokerConfiguration](../../docs/adapters/mqtt.md#mqttbrokerconfiguration) for all broker settings.

## Target section
```json
"Targets": [
  "OPCUAWrite",
  "#DebugTarget"
]
```

In order to write the data to both the OPCUA server and the console
uncomment the DebugTarget by deleting the '#'.  
&nbsp;

## Run SFC from deployment directory

In the terminal in which you set `SFC_DEPLOYMENT_DIR`, start the `sfc-main`
of the deployment directory from this example's folder:

**Linux / macOS**

```shell
"$SFC_DEPLOYMENT_DIR/sfc-main/bin/sfc-main" -config iot-core-opcua-write.json
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\sfc-main\lib\*" com.amazonaws.sfc.MainController -config iot-core-opcua-write.json
```

On Windows start `sfc-main` with `java -cp` as shown, not with
`bin\sfc-main.bat` ([Platform support](../../docs/README.md#platform-support)).
With the uberjar from [sfcup](../../README.md#1-install), remove the
`JarFiles` entries and run `sfcx -config iot-core-opcua-write.json`; keep
`SFC_DEPLOYMENT_DIR` set, because the certificate paths use it.

To try it, publish `{"temperature": 21.5}` to the topic `temperature`, for
example with the MQTT test client in the AWS IoT console. The `OPCUAWrite`
target then writes 21.5 to the node `ns=2;i=2`.

Docs used: [MQTT adapter brokers](../../docs/adapters/mqtt.md#mqttbrokerconfiguration) · [OPC UA Writer target](../../docs/targets/opcua-writer.md) · [Debug target](../../docs/targets/debug.md) · [In-process mode](../../docs/sfc-deployment.md#in-process) · [All examples](../../docs/examples/README.md)
