# Shop Floor Connectivity and SiteWise Edge

## Introduction

Shop Floor Connectivity (SFC) is a data ingestion technology that can deliver data to multiple AWS Services. SFC extends and unifies data collection capabilities additionally to our existing Industrial Internet of Things (IIoT) data collection services, allowing customers to provide data in a consistent way to a wide range of AWS Services. It allows customers to collect data from their industrial equipment and deliver it to the AWS services that work best for their requirements. Customers get the cost and functional benefits of specific AWS services and save costs on licenses for additional connectivity products.

[AWS IoT SiteWise Edge](https://aws.amazon.com/iot-sitewise/sitewise-edge/) software makes it easy to collect, organize, process, and monitor equipment data on-premises. It enables factory operators to get visibility into their equipment data and make decisions that help improve equipment uptime, product quality, and process efficiency. SiteWise Edge is installed on local hardware such as third-party industrial gateways and computers, or on AWS Outposts and AWS Snow Family compute devices. Since SiteWise Edge runs on-premises, local applications that use data from SiteWise Edge will continue to work even during intermittent cloud connectivity.

*This workshop demonstrates data ingestion from an on premises OPC-UA server to AWS IoT SiteWise Edge using the SFC [in-process deployment](../../docs/sfc-deployment.md#in-process-and-ipc-deployment-models). SFC replaces the gateway's OPC-UA collector: the SiteWise Edge gateway still runs, and SFC, on a separate device, publishes to its MQTT broker.*

## Create and Setup Gateway


**Prerequisites:**

- Ensure your AWS account and region have the associated [Greengrass service role](https://docs.aws.amazon.com/greengrass/v2/developerguide/greengrass-service-role.html) enabled, which is required for external connections to the Greengrass MQTT broker.
- On the device that runs SFC: Java 17 or newer, Docker for the umati OPC-UA sample server, the AWS CLI v2, and network access to the gateway on port 8883. Linux and macOS also need `jq` for step 5 of [Obtain MQTT Client Certificates](#obtain-mqtt-client-certificates-x509).
- On Windows: `winget install EclipseAdoptium.Temurin.17.JDK`, `winget install Docker.DockerDesktop` (in its default Linux-containers mode), `winget install Amazon.AWSCLI`, and PowerShell 7 for step 5 (`winget install Microsoft.PowerShell`). Run the commands of this page in PowerShell; where a step differs from Linux / macOS, its Windows form follows the Linux / macOS one.

1. Sign in to the [AWS Management Console](https://console.aws.amazon.com/)
2. Navigate to the [IoT SiteWise console](https://console.aws.amazon.com/iotsitewise/home#/gateway)
3. Create a SiteWise Edge Gateway by following the instructions in the [AWS IoT SiteWise User Guide](https://docs.aws.amazon.com/iot-sitewise/latest/userguide/create-gateway-ggv2.html).
4. Install the SiteWise Edge Gateway software on a local device by following the instructions in the [AWS IoT SiteWise User Guide](https://docs.aws.amazon.com/iot-sitewise/latest/userguide/install-gateway-software-on-local-device.html).


**Note:** Throughout these instructions, the terms "SiteWise Edge Gateway" and "Greengrass core device" are used interchangeably to refer to the same device.


## Enable Secure MQTT Connectivity on SiteWise Edge Gateway

**Note:** To connect to the MQTT broker, you may need to modify your firewall rules to make port 8883 accessible from the connecting device.

1. Navigate to the [AWS IoT SiteWise Edge Gateways](https://console.aws.amazon.com/iotsitewise/home#/gateway) console
2. Select the SiteWise Edge Gateway you created in the previous section
3. Under the **Gateway configuration** panel, click the link under the **Greengrass core device** heading
4. Click on the **Deployments** tab, and then click the link to the existing deployment
5. Under the **Actions** menu button, click **Revise**
6. In the "Revise deployment" dialog box, click **Revise deployment**
7. Click **Next**
8. Next to the search box, uncheck the **Show only selected components** option
9. Search for and add the following components:
   1. `aws.greengrass.clientdevices.mqtt.EMQX`
   2. `aws.greengrass.clientdevices.Auth`
   3. `aws.greengrass.clientdevices.IPDetector`
10. Click **Next**
11. Select the `aws.greengrass.clientdevices.Auth` component and click **Configure component**
12. Paste the following configuration into the **Configuration to merge** section:

```json
{
  "deviceGroups": {
    "formatVersion": "2021-03-05",
    "definitions": {
      "DemoDeviceGroup": {
        "selectionRule": "thingName: DemoClientThing*",
        "policyName": "DemoClientThingPolicy"
      }
    },
    "policies": {
      "DemoClientThingPolicy": {
        "AllowAll": {
          "statementDescription": "Allow client devices.",
          "operations": [
            "mqtt:connect",
            "mqtt:publish",
            "mqtt:subscribe"
          ],
          "resources": [
            "*"
          ]
        }
      }
    }
  }
}
```

13. Click **Confirm**
14. Select the `aws.greengrass.clientdevices.mqtt.EMQX` component and click **Configure component**
15. Paste the following configuration into the **Configuration to merge** section:

```json
{
    "emqxConfig": {
        "authorization": {
            "no_match": "allow"
        },
        "listeners": {
            "tcp": {
                "default": {
                    "enabled": true,
                    "enable_authn": false
                }
            },
            "ssl": {
                "default": {
                    "enabled": true,
                    "enable_authn": true,
                    "ssl_options": {
                        "keyfile": "{work:path}\\data\\key.pem",
                        "certfile": "{work:path}\\data\\cert.pem",
                        "cacertfile": "{work:path}\\data\\ca.pem",
                        "verify": "verify_peer",
                        "versions": [
                            "tlsv1.3",
                            "tlsv1.2"
                        ],
                        "fail_if_no_peer_cert": true
                    }
                }
            }
        }
    },
    "authMode": "bypass_on_failure",
    "dockerOptions": "-p 8883:8883 -p 127.0.0.1:1883:1883",
    "requiresPrivilege": "true"
}
```

16. Click **Confirm**
17. Click **Skip to Review**
18. Click **Deploy**
19. Wait for the **Deployment status** to change to **completed**


After completing these steps, the EMQX MQTT broker component should be deployed and configured on your SiteWise Edge Gateway.

## Obtain MQTT Client Certificates (X.509)

**Note:** You will need to disable hostname validation in your MQTT client to use the X.509 certificates created in this section.

1. [Configure the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-configure.html) with your [AWS account credentials](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-authentication.html) to access your AWS account
2. Create an IoT policy that allows connections to the Greengrass MQTT broker:

**Linux / macOS**

```shell
aws iot create-policy \
   --policy-name DemoClientThingPolicy \
   --policy-document '{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "iot:Connect",
        "iot:Publish",
        "iot:Subscribe",
        "iot:Receive",
        "greengrass:Discover"
      ],
      "Resource": "*"
    }
  ]
}'
```

**Windows (PowerShell)**

```powershell
@'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["iot:Connect", "iot:Publish", "iot:Subscribe", "iot:Receive", "greengrass:Discover"],
      "Resource": "*"
    }
  ]
}
'@ | Set-Content -Encoding ascii policy.json
aws iot create-policy --policy-name DemoClientThingPolicy --policy-document file://policy.json
```

3. Create an IoT Thing named `DemoClientThing` and save its X.509 certificates:

**Linux / macOS**

```shell
mkdir -p ~/gateway-client-certs
cd ~/gateway-client-certs
THING_NAME=DemoClientThing
aws iot create-thing --thing-name $THING_NAME
CERTIFICATE_ARN=$(aws iot create-keys-and-certificate --private-key-outfile $THING_NAME.key --certificate-pem-outfile $THING_NAME.crt --query "certificateArn" --output text --set-as-active)
aws iot attach-policy --policy-name DemoClientThingPolicy --target $CERTIFICATE_ARN
aws iot attach-thing-principal --thing-name $THING_NAME --principal $CERTIFICATE_ARN
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force "$HOME\gateway-client-certs" | Out-Null
Set-Location "$HOME\gateway-client-certs"
$THING_NAME = "DemoClientThing"
aws iot create-thing --thing-name $THING_NAME
$CERTIFICATE_ARN = aws iot create-keys-and-certificate --private-key-outfile "$THING_NAME.key" --certificate-pem-outfile "$THING_NAME.crt" --query certificateArn --output text --set-as-active
aws iot attach-policy --policy-name DemoClientThingPolicy --target $CERTIFICATE_ARN
aws iot attach-thing-principal --thing-name $THING_NAME --principal $CERTIFICATE_ARN
```

4. Associate the `DemoClientThing` with the Greengrass core. You can retrieve the name of the Greengrass Core by going to the [AWS IoT SiteWise Edge Gateways](https://console.aws.amazon.com/iotsitewise/home#/gateway) console and selecting the gateway. The command is the same in PowerShell:

```shell
aws greengrassv2 batch-associate-client-device-with-core-device --core-device-thing-name <REPLACE WITH CORE NAME> --entries "thingName=$THING_NAME"
```

5. Retrieve the Greengrass Core CA certificate, in the folder of step 3:

**Linux / macOS**

```shell
export AWS_REGION=${AWS_REGION:-$(aws configure get region)}
curl -s --cert ${THING_NAME}.crt \
    --key ${THING_NAME}.key \
    https://greengrass-ats.iot.${AWS_REGION}.amazonaws.com:8443/greengrass/discover/thing/${THING_NAME} | \
    jq -r '.GGGroups[0].CAs[0]' > ${THING_NAME}CA.crt
```

**Windows (PowerShell 7)**

```powershell
Set-Location "$HOME\gateway-client-certs"
$THING_NAME = "DemoClientThing"
$region = if ($env:AWS_REGION) { $env:AWS_REGION } else { aws configure get region }
$pem  = [System.Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPemFile("$PWD\$THING_NAME.crt", "$PWD\$THING_NAME.key")
$cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($pem.Export("Pfx"))
$disc = Invoke-RestMethod -Certificate $cert -Uri "https://greengrass-ats.iot.$region.amazonaws.com:8443/greengrass/discover/thing/$THING_NAME"
$disc.GGGroups[0].CAs[0] | Set-Content -Encoding ascii "${THING_NAME}CA.crt"
```

Run this step in PowerShell 7 (`pwsh`): Windows PowerShell 5.1 cannot read PEM private keys, and the
`curl.exe` that ships with Windows cannot use them either. Without PowerShell 7, run the Linux command in
WSL.

After completing these steps, you should have the following files in the `~/gateway-client-certs` directory (Windows: `$HOME\gateway-client-certs`):


* Certificate Authority (CA): `DemoClientThingCA.crt`
* Client Certificate: `DemoClientThing.crt`
* Client Key: `DemoClientThing.key`


You can test the usage of these certificates with the [mosquitto](https://mosquitto.org/download/) MQTT client, in the same folder. The command is the same in PowerShell; keep the quotes around `'#'`:

```shell
mosquitto_sub -h <gateway_address> -p 8883 -q 0 -t '#' --cafile DemoClientThingCA.crt --cert DemoClientThing.crt --key DemoClientThing.key -i DemoClientThing --insecure
```



## Create SiteWise Model and Asset

To associate incoming data with assets in the cloud, deploy the [sitewise_resources.yaml](./resources/cf-templates/sitewise_resources.yaml) CloudFormation template. Run the command from this example's folder, `examples/in-process-opcua-sitewiseedge` in a clone of this repository; it is the same in PowerShell:

```shell
aws cloudformation deploy --template-file resources/cf-templates/sitewise_resources.yaml --stack-name SFCSiteWiseEdgeDemo
```

After the deployment is complete, you can navigate to the [AWS IoT SiteWise console](https://console.aws.amazon.com/iotsitewise/home) to view the created model and asset.

## Shop Floor Connectivity Setup

### Installation

Follow these instructions to run the Shop Floor Connectivity (SFC) application on a separate device located on the same network as the SiteWise Edge Gateway. First, download the required SFC bundles of this repository's latest release into the deployment directory `SFC_DEPLOYMENT_DIR`, from which the configuration below loads the adapter and the targets. Run all following steps in this terminal, because they rely on the variables set here.

**Linux / macOS**

```shell
# Define the sfc directory, then download and extract the bundles into it
export SFC_DEPLOYMENT_DIR="./sfc"
mkdir -p "$SFC_DEPLOYMENT_DIR"
for m in sfc-main opcua aws-sitewiseedge-target debug-target; do
  curl -fsSL "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz" | tar -xz -C "$SFC_DEPLOYMENT_DIR"
done
```

**Windows (PowerShell)**

```powershell
# Define the sfc directory, then download and extract the bundles into it
$env:SFC_DEPLOYMENT_DIR = "C:/sfc"
New-Item -ItemType Directory -Force C:\sfc | Out-Null
foreach ($m in "sfc-main", "opcua", "aws-sitewiseedge-target", "debug-target") {
    curl.exe -fsSL -o "C:\sfc\$m.tar.gz" "https://github.com/awslabs/industrial-shopfloor-connect/releases/latest/download/$m.tar.gz"
    tar -xf "C:\sfc\$m.tar.gz" -C C:\sfc
    Remove-Item "C:\sfc\$m.tar.gz"
}
```

### Configuration

The configuration is an in-process [SFC configuration](../../docs/core/sfc-configuration.md). The
[OPC-UA adapter](../../docs/adapters/opcua.md) reads the umati nodes, the
[SiteWise Edge target](../../docs/targets/aws-sitewiseedge.md#sitewiseedgetargetconfiguration) publishes
them as TQV messages to the gateway's broker ([TopicName](../../docs/targets/aws-sitewiseedge.md#topicname),
[EndPoint](../../docs/targets/aws-sitewiseedge.md#endpoint)), and `#DebugTarget` is the
[Debug target](../../docs/targets/debug.md), disabled by its `#`.

Save it as `example.json` in the deployment directory, as UTF-8: `sfc/example.json` on Linux / macOS,
`C:\sfc\example.json` on Windows. On Windows save it with an editor, for example
`notepad C:\sfc\example.json`; in Windows PowerShell 5.1, `>` and `Out-File` write UTF-16, which SFC
cannot read.

>**Note:** Please expand the section below, to see the json config...


<details>
<summary>Expand to view the JSON configuration</summary>

```json
{
    "AWSVersion": "2022-04-02",
    "Name": "OPCUA to SiteWise Edge, using in process source and targets",
    "Version": 1,
    "LogLevel": "Info",
    "ElementNames": {
        "Value": "value",
        "Timestamp": "timestamp",
        "Metadata": "metadata"
    },
    "Schedules": [
        {
            "Name": "OpcuaToSiteWiseEdge",
            "Interval": 200,
            "Description": "Read OPCUA and send to SiteWise Edge",
            "Active": true,
            "TimestampLevel": "Both",
            "Sources": {
                "OPCUA-SOURCE": [
                    "*"
                ]
            },
            "Targets": [
                "SiteWiseEdgeTarget",
                "#DebugTarget"
            ]
        }
    ],
    "Sources": {
        "OPCUA-SOURCE": {
            "Name": "OPCUA-SOURCE",
            "ProtocolAdapter": "OPC-UA",
            "AdapterOpcuaServer": "OPCUA-SERVER-1",
            "Description": "OPCUA local test server",
            "SourceReadingMode": "Polling",
            "SubscribePublishingInterval": 100,
            "Channels": {
                "ServerStatus": {
                    "Name": "ServerStatus",
                    "NodeId": "ns=0;i=2256"
                },
                "ServerTime": {
                    "Name": "ServerTime",
                    "NodeId": "ns=0;i=2256",
                    "Selector": "@.currentTime"
                },
                "State": {
                    "Name": "State",
                    "NodeId": "ns=0;i=2259"
                },
                "Machine1AbsoluteErrorTime": {
                    "Name": "AbsoluteErrorTime",
                    "NodeId": "ns=20;i=59217"
                },
                "Machine1AbsoluteLength": {
                    "Name": "AbsoluteLength",
                    "NodeId": "ns=20;i=59235"
                },
                "Machine1AbsoluteMachineOffTime": {
                    "Name": "AbsoluteMachineOffTime",
                    "NodeId": "ns=20;i=59210"
                },
                "Machine1AbsoluteMachineOnTime": {
                    "Name": "AbsoluteMachineOnTime",
                    "NodeId": "ns=20;i=59219"
                },
                "Machine1AbsolutePiecesIn": {
                    "Name": "AbsolutePiecesIn",
                    "NodeId": "ns=20;i=59237"
                },
                "Machine1FeedSpeed": {
                    "Name": "FeedSpeed",
                    "NodeId": "ns=20;i=59208"
                }
            }
        }
    },
    "Targets": {
        "DebugTarget": {
            "Active": true,
            "TargetType": "DEBUG-TARGET"
        },
        "SiteWiseEdgeTarget": {
            "Active": true,
            "TargetType": "AWS-SITEWISEEDGE-TARGET",
            "TopicName": "%channel%",
            "ClientName": "${CLIENT_ID}",
            "EndPoint": "ssl://${GATEWAY_HOSTNAME}",
            "Port": 8883,
            "RootCA": "${GATEWAY_CA_FILE}",
            "Certificate": "${CLIENT_CERTIFICATE_FILE}",
            "PrivateKey": "${CLIENT_KEY_FILE}",
            "VerifyHostname": false,
            "BatchSize": 1000,
            "BatchInterval": 5000,
            "BatchCount": 10
        }
    },
    "TargetTypes": {
        "DEBUG-TARGET": {
            "JarFiles": [
                "${SFC_DEPLOYMENT_DIR}/debug-target/lib"
            ],
            "FactoryClassName": "com.amazonaws.sfc.debugtarget.DebugTargetWriter"
        },
        "AWS-SITEWISEEDGE-TARGET": {
            "JarFiles": [
                "${SFC_DEPLOYMENT_DIR}/aws-sitewiseedge-target/lib"
            ],
            "FactoryClassName": "com.amazonaws.sfc.awssitewiseedge.SiteWiseEdgeTargetWriter"
        }
    },
    "AdapterTypes": {
        "OPCUA": {
            "JarFiles": [
                "${SFC_DEPLOYMENT_DIR}/opcua/lib"
            ],
            "FactoryClassName": "com.amazonaws.sfc.opcua.OpcuaAdapter"
        }
    },
    "ProtocolAdapters": {
        "OPC-UA": {
            "AdapterType": "OPCUA",
            "OpcuaServers": {
                "OPCUA-SERVER-1": {
                    "Address": "opc.tcp://localhost",
                    "Path": "/",
                    "Port": 4840,
                    "ConnectTimeout": "10000",
                    "ReadBatchSize": 500
                }
            }
        }
    }
}
```

</details>

Each value is published to the topic `%channel%`, that is the channel's `Name`. The target also uses
that name as the SiteWise property alias, so it must equal an `Alias` in
[sitewise_resources.yaml](./resources/cf-templates/sitewise_resources.yaml).

Copy the MQTT client certificates to the SFC device into the `swe-certs` directory of the deployment
directory and set the required environment variables. If you created the certificates on another
machine, copy them over first, for example with `scp`.

**Linux / macOS**

```shell
mkdir -p sfc/swe-certs
cp ~/gateway-client-certs/DemoClientThing* sfc/swe-certs/

# define configuration values
export GATEWAY_HOSTNAME=<REPLACE WITH SITEWISE EDGE HOSTNAME>
export CLIENT_ID="DemoClientThing"
export GATEWAY_CA_FILE="./sfc/swe-certs/DemoClientThingCA.crt"
export CLIENT_CERTIFICATE_FILE="./sfc/swe-certs/DemoClientThing.crt"
export CLIENT_KEY_FILE="./sfc/swe-certs/DemoClientThing.key"
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force C:\sfc\swe-certs | Out-Null
Copy-Item "$HOME\gateway-client-certs\DemoClientThing*" C:\sfc\swe-certs\

# define configuration values
$env:GATEWAY_HOSTNAME = "<REPLACE WITH SITEWISE EDGE HOSTNAME>"
$env:CLIENT_ID = "DemoClientThing"
$env:GATEWAY_CA_FILE = "C:/sfc/swe-certs/DemoClientThingCA.crt"
$env:CLIENT_CERTIFICATE_FILE = "C:/sfc/swe-certs/DemoClientThing.crt"
$env:CLIENT_KEY_FILE = "C:/sfc/swe-certs/DemoClientThing.key"
```

### Run

With everything set up, you can start the OPC-UA server and the SFC application. On Linux / macOS run
the commands from the folder that contains `sfc`; on Windows Docker Desktop must run Linux containers.

**Linux / macOS**

```shell
# start umati opc-ua sample server
sudo docker run -d --name umati -p 4840:4840 ghcr.io/umati/sample-server:main

# run sfc
sfc/sfc-main/bin/sfc-main -config sfc/example.json
```

**Windows (PowerShell)**

```powershell
# start umati opc-ua sample server
docker run -d --name umati -p 4840:4840 ghcr.io/umati/sample-server:main

# run sfc
java -cp "C:\sfc\sfc-main\lib\*" com.amazonaws.sfc.MainController -config C:\sfc\example.json
```

On Windows start `sfc-main` with `java -cp` as shown, not with `sfc-main\bin\sfc-main.bat`; see
[Platform support](../../docs/README.md#platform-support).

After completing these steps, the SFC application should be running and ingesting data from the OPC-UA server to the SiteWise Edge Gateway using MQTT.
When the target starts, SFC logs `MQTT Writer for target "SiteWiseEdgeTarget" writer publishing to topic "%channel%" at endpoint ssl://…`.
To see each value SFC reads, remove the `#` from `"#DebugTarget"` in the schedule; to see what reaches
the gateway, subscribe with the `mosquitto_sub` command above.

## Query SiteWise

To view the data ingested from the OPC-UA server, you can go to the [AWS IoT SiteWise console](https://console.aws.amazon.com/iotsitewise/home#/assets) and navigate to the asset `Demo Asset` created earlier. Alternatively, you can query the data using the AWS CLI; the command is the same in PowerShell:

```shell
aws iotsitewise get-asset-property-value-history --property-alias AbsoluteMachineOnTime
```

This command will retrieve the historical values for the `AbsoluteMachineOnTime` property associated with the `Demo Asset`.

You can replace `AbsoluteMachineOnTime` with any other property alias defined in the SiteWise model to query different data points.

## Clean up

Stop SFC with Ctrl-C. Then remove what this walkthrough created: the umati container, the SiteWise
model and asset stack, and the client device with its certificate and policy.

**Linux / macOS**

```shell
sudo docker rm -f umati
aws cloudformation delete-stack --stack-name SFCSiteWiseEdgeDemo
aws greengrassv2 batch-disassociate-client-device-from-core-device --core-device-thing-name <REPLACE WITH CORE NAME> --entries thingName=DemoClientThing
CERTIFICATE_ARN=$(aws iot list-thing-principals --thing-name DemoClientThing --query "principals[0]" --output text)
aws iot detach-thing-principal --thing-name DemoClientThing --principal "$CERTIFICATE_ARN"
aws iot detach-policy --policy-name DemoClientThingPolicy --target "$CERTIFICATE_ARN"
aws iot update-certificate --certificate-id "${CERTIFICATE_ARN##*/}" --new-status INACTIVE
aws iot delete-certificate --certificate-id "${CERTIFICATE_ARN##*/}"
aws iot delete-thing --thing-name DemoClientThing
aws iot delete-policy --policy-name DemoClientThingPolicy
```

**Windows (PowerShell)**

```powershell
docker rm -f umati
aws cloudformation delete-stack --stack-name SFCSiteWiseEdgeDemo
aws greengrassv2 batch-disassociate-client-device-from-core-device --core-device-thing-name <REPLACE WITH CORE NAME> --entries "thingName=DemoClientThing"
$CERTIFICATE_ARN = aws iot list-thing-principals --thing-name DemoClientThing --query "principals[0]" --output text
$CERTIFICATE_ID = $CERTIFICATE_ARN.Split("/")[-1]
aws iot detach-thing-principal --thing-name DemoClientThing --principal $CERTIFICATE_ARN
aws iot detach-policy --policy-name DemoClientThingPolicy --target $CERTIFICATE_ARN
aws iot update-certificate --certificate-id $CERTIFICATE_ID --new-status INACTIVE
aws iot delete-certificate --certificate-id $CERTIFICATE_ID
aws iot delete-thing --thing-name DemoClientThing
aws iot delete-policy --policy-name DemoClientThingPolicy
```

Finally, revise the gateway's deployment as in
[Enable Secure MQTT Connectivity on SiteWise Edge Gateway](#enable-secure-mqtt-connectivity-on-sitewise-edge-gateway)
and remove the components `aws.greengrass.clientdevices.mqtt.EMQX`, `aws.greengrass.clientdevices.Auth`
and `aws.greengrass.clientdevices.IPDetector`, and delete the local `gateway-client-certs` folder and the
deployment directory.

Docs used: [OPC-UA adapter](../../docs/adapters/opcua.md) · [AWS IoT SiteWise Edge target](../../docs/targets/aws-sitewiseedge.md) · [Debug target](../../docs/targets/debug.md) · [In-process mode](../../docs/sfc-deployment.md#in-process) · [All examples](../../docs/examples/README.md)