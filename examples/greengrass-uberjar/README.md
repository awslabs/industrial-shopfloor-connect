SFC `uberjar` setup in Greengrass V2
=======================================

# Introduction

This setup will demonstrate how to integrate SFC into Greengrass V2 with a single artifact jar.
In this way the component can run on windows and linux, does not require any container, unpack zips or so.
It uses the uberjar created by SFC that contains the SFC core, all adapters, targets and the dependencies.
As this is an executable jar the sfc config can be read through the environment configuration which allows to run the same command on all platforms.

Because every adapter and target is inside the jar, the `AdapterTypes` and `TargetTypes` entries name only their
`FactoryClassName` ([uberjar mode](../../docs/sfc-deployment.md#uberjar)). Started without `-config`, SFC reads its
configuration from the `SFC_CONFIG` environment variable, which the recipe sets from the component configuration
([configuration from an environment variable](../../docs/sfc-running-core-process.md#additional-functionality-to-specify-the-config-via-environment-variables)).

# Preconditions

We assume you have a running AWS IoT Greengrass core. If you don't have one running yet please look here:
[Getting started with AWS IoT Greengrass V2](https://docs.aws.amazon.com/greengrass/v2/developerguide/getting-started.html) .

The core device also needs:

- **Java 17 or newer** as the `java` that the component starts. SFC is built for Java 17, so an older `java` fails with
  `UnsupportedClassVersionError` in `com.amazonaws.sfc.log`. On Linux check it with `sudo java -version` (the recipe
  sets `RequiresPrivilege`). On Windows install it with e.g. `winget install EclipseAdoptium.Temurin.17.JDK`, make sure
  its `bin` folder is listed under System variables > Path, then restart the device.
- **An MQTT broker** on the core device at `127.0.0.1:1883`, without TLS and without user name and password, for example
  [Eclipse Mosquitto](https://mosquitto.org/download/). The sample configuration reads the topic `setpoint/x1` from it;
  for another broker change the address and port in `EndPoint` and the `Port` under `ProtocolAdapters.MQTT.Brokers`.

The setup here will just explain how to build the SFC component that then can be deployed to the running Greengrass core.

# Setup

## Step 1: Create an uberjar for SFC

If you installed SFC with [sfcup](../../README.md#1-install), the uberjar `sfc-uberjar-<version>.jar` of the installed
release is already on disk: in `~/.sfc/current/lib/` on Linux / macOS, and in `$HOME\.sfc\versions\<release>\lib\`
on Windows (`$HOME\.sfc\current.txt` names the release). The same jar is in `sfc-uberjar/lib/` of `sfc-uberjar.tar.gz`
on the [releases page](https://github.com/awslabs/industrial-shopfloor-connect/releases/latest).

To build it yourself instead, checkout SFC to your local directory. Then execute the following command to build a
uberjar (this needs a JDK 17 or newer):

**Linux / macOS**

```shell
cd core/sfc-uberjar
bash ../../gradlew build
```

**Windows (PowerShell)**

```powershell
cd core\sfc-uberjar
..\..\gradlew.bat build
```

This will produce an executable uberjar in `build/libs` like `build/libs/sfc-uberjar-<version>.jar` (a few hundred MB;
ignore the small `-thin.jar` next to it). `<version>` comes from the nearest git tag (`v1.11.0` gives `1.11.0`), or is
`0.0.0-dev` without git metadata.

## Step 2: Create an Amazon S3 bucket if it doesn't exist

AWS IoT Greengrass can only deploy artifacts from an Amazon S3 bucket in the same AWS region
as the greengrass component is created.
If you have an S3 bucket you want to use you can go to Step 3 if not please create an Amazon S3 bucket
in the same region where you want to build the component. (Greengrass will not allow you to create a component 
with an artefact link to a different region) 

## Step 3: Upload the jar to the Amazon S3 bucket

Upload the uberjar from Step 1 to the S3 bucket under the name `sfc-uberjar.jar`; the recipe in Step 4 uses that name,
so it stays the same when the SFC version changes. Feel free to put it into a folder if you want. For example with the
AWS CLI, for the jar of an sfcup install:

**Linux / macOS**

```shell
aws s3 cp ~/.sfc/current/lib/sfc-uberjar-*.jar s3://[REPLACE WITH YOUR S3 BUCKET]/sfc-uberjar.jar
```

**Windows (PowerShell)**

```powershell
$jar = Get-ChildItem "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\sfc-uberjar-*.jar"
aws s3 cp $jar.FullName s3://[REPLACE WITH YOUR S3 BUCKET]/sfc-uberjar.jar
```

For a jar you built in Step 1, copy `core/sfc-uberjar/build/libs/sfc-uberjar-<version>.jar` instead (Windows:
`core\sfc-uberjar\build\libs\sfc-uberjar-<version>.jar`).
Please copy the S3 URL e.g. `s3://my-s3-bucket/sfc-uberjar.jar` which you will need in the next step.

## Step 4: Create a Greengrass Component

* Open the AWS Console with AWS IoT Greengrass on the same region where the S3 bucket is located and the Greengrass core is connected to.
* Click on `Greengrass devices`, select `Components` and then click on `Create Component` on the top right.
* replace the sample recipe with the following recipe, which is also in
  [sfc-greengrass-uberjar-recipe.json](sfc-greengrass-uberjar-recipe.json). **Ensure to replace the artifact URI with the S3 path from Step 3** 

```json
{
  "RecipeFormatVersion": "2020-01-25",
  "ComponentName": "com.amazonaws.sfc",
  "ComponentVersion": "1.0.0",
  "ComponentType": "aws.greengrass.generic",
  "ComponentDescription": "SFC all in one",
  "ComponentPublisher": "Me",
  "ComponentConfiguration": {
    "DefaultConfiguration": {
      "SFC_CONFIG": {
        "AWSVersion": "2022-04-02",
        "Name": "MQTT writing to Debug",
        "Version": 1,
        "LogLevel": "Info",
        "Schedules": [
          {
            "Name": "DCSChangeSetpoint",
            "Interval": 1000,
            "Active": true,
            "TimestampLevel": "Both",
            "Sources": {
              "MQTT": [
                "*"
              ]
            },
            "Targets": [
              "DebugTarget"
            ]
          }
        ],
        "Sources": {
          "MQTT": {
            "Name": "MQTT",
            "ProtocolAdapter": "MQTT",
            "AdapterBroker": "local-mqtt-broker",
            "Channels": {
              "setpoint_x1": {
                "Topics": [
                  "setpoint/x1"
                ]
              }
            }
          }
        },
        "Targets": {
          "DebugTarget": {
            "TargetType": "DEBUG-TARGET"
          }
        },
        "TargetTypes": {
          "DEBUG-TARGET": {
            "FactoryClassName": "com.amazonaws.sfc.debugtarget.DebugTargetWriter"
          }
        },
        "AdapterTypes": {
          "MQTT": {
            "FactoryClassName": "com.amazonaws.sfc.mqtt.MqttAdapter"
          }
        },
        "ProtocolAdapters": {
          "MQTT": {
            "AdapterType": "MQTT",
            "ReadMode": "KeepAll",
            "Brokers": {
              "local-mqtt-broker": {
                "EndPoint": "tcp://127.0.0.1:1883",
                "Port": 1883
              }
            }
          }
        }
      }
    }
  },
  "Manifests": [
    {
      "Platform": {
        "os": "*",
        "runtime": "*"
      },
      "Lifecycle": {
        "Run": {
          "RequiresPrivilege": true,
          "Script": "java -jar \"{artifacts:path}/sfc-uberjar.jar\"",
          "Setenv": {
            "SFC_CONFIG": "{configuration:/SFC_CONFIG}"
          }
        }
      },
      "Artifacts": [
        {
          "Uri": "s3://[REPLACE WITH YOUR S3 BUCKET]/sfc-uberjar.jar"
        }
      ]
    }
  ]
}

```
* Click `Create component` to finish creating the component

Instead of the console you can create the component from the file with the AWS CLI, after replacing the S3 bucket
placeholder in it (same command in PowerShell, run in this folder):
`aws greengrassv2 create-component-version --inline-recipe fileb://sfc-greengrass-uberjar-recipe.json --region <region>`.

## Step 5: Deploy the component

* select the Greengrass core device that you have already running in the AWS Console.
* Revise the deployment and add the SFC component.
* Deploy the revised deployment to the Greengrass core.
* Check the logs in the Greengrass log folder, there should be a file called `com.amazonaws.sfc.log`:

**Linux**

```shell
sudo tail -f /greengrass/v2/logs/com.amazonaws.sfc.log
```

**Windows (PowerShell as administrator)**

```powershell
Get-Content C:\greengrass\v2\logs\com.amazonaws.sfc.log -Wait -Tail 50
```

Once SFC has connected to the broker the log shows `Connected to broker for source "MQTT" at tcp://127.0.0.1:1883`;
`Error connecting to tcp://127.0.0.1:1883 for source "MQTT"` means that SFC could not connect to a broker at that
address.

## Step 6: Send a test value

On the core device, publish a value to the topic `setpoint/x1` that the configuration subscribes to, for example with
Mosquitto's `mosquitto_pub` client (on Windows run the same command with the `mosquitto_pub.exe` of your Mosquitto
installation):

```shell
mosquitto_pub -h 127.0.0.1 -t setpoint/x1 -m 42
```

Within a second the Debug target writes the value to `com.amazonaws.sfc.log`, named after its topic `setpoint/x1`.

## Step 7: Clean up

* Revise the deployment again and remove the SFC component, then delete the component version under
  `Greengrass devices` > `Components`.
* Delete `sfc-uberjar.jar` from the S3 bucket.

Docs used: [MQTT adapter](../../docs/adapters/mqtt.md) · [Debug target](../../docs/targets/debug.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [Configuration from an environment variable](../../docs/sfc-running-core-process.md#additional-functionality-to-specify-the-config-via-environment-variables) · [All examples](../../docs/examples/README.md)
