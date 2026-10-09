Example: OPC UA to AWS IoT Core using filters
=============================================

## What does the example do?
This example reads data from a public, open OPC UA server (uademo.prosysopc.com) and sends it to AWS IoT Core, demonstrating the 
usage of *[Metadata](../../docs/README.md#metadata)*, *[Transformations](../../docs/sfc-data-processing-filtering.md#transformations)* as well as the following filter types: *[Change Filter](../../docs/sfc-data-processing-filtering.md#data-change-filters)*, *[Condition Filter](../../docs/sfc-data-processing-filtering.md#condition-filters)*, *[Value Filter](../../docs/sfc-data-processing-filtering.md#value-filters)*.  

The public OPC UA server exposes simulation tags which we will use. We use two tags:  
1. A counter tag that is incremented by 1 from 0 to 30 in an infinite loop.  
2. A tag producing random values in the range -2 to 2.  
  
The counter tag is used as a trigger. Whenever its value differs by at least 50% from the last value we forwarded, we forward the data.  
To do so, we use a *Change Filter*.  
Here's an example of how it works:  
- last forwarded value 1, new value 2: change +100% -> value is forwarded, channel value exists.  
- last forwarded value 3, new value 4: change only +33% -> value is read but dropped, channel value does not exist.  

Starting at 0, the filter therefore forwards the counter values 0, 1, 2, 3, 5, 8, 12, 18 and 27. Its `AtLeast` of 60000 ms
re-sends an unchanged value after a minute; it does not force out changes smaller than 50%.  

Three flavors of the random value tag are connected to the trigger tag through a *Condition Filter*.  
That data is only forwarded if the trigger channel has a value.   

Besides, the example demonstrates a *Value Filter* only forwarding data greater than zero and also a *Transformation* truncating values to two decimals (`TruncAt`).  
Further, the application of *Metadata* is demonstrated.

A real-world use case for this setup is to create a snapshot of certain OPC-UA tags when the trigger tag is changed.  
This can be used in scenarios where the tags hold final processing data like torque moments to be captured when a part's processing is finished on a machine.

## How to set up and run the example?
The setup of the scenario is similar to the steps in the [Quickstart example](../../README.md#quickstart) of this repo with small modifications.  
Please note that sending data to AWS IoT Core might incur a cost when exceeding the free tier limit.

>**Requirements**: Java 17 or newer, aws cli [Credentials Configuration](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-configure.html#configure-precedence). 
On Windows: `winget install EclipseAdoptium.Temurin.17.JDK` and `winget install Amazon.AWSCLI`.
Make sure you have AWS permissions as described in [AWS IoT Core Target](../../docs/targets/aws-iot-core.md)

### Installation

Install SFC with sfcup as in [step 1 of the Quickstart](../../README.md#1-install). It installs the uberjar, which
already contains the OPC UA adapter and the AWS IoT Core and debug targets, so the configuration below names them by
their `FactoryClassName` only.

### Configure

Next we will define the AWS region we want to send the data to. The configuration reads it as `${AWS_REGION}`:

**Linux / macOS**

```shell
export AWS_REGION="us-east-1"
```

**Windows (PowerShell)**

```powershell
$env:AWS_REGION = "us-east-1"
```

Now we will have to configure the SFC, therefore save the following as `example.json` in a folder of your choice.

```json
  {
    "AWSVersion": "2022-04-02",
    "Name": "OPCUA to AWS IoT core demoing filter features",
    "Version": 1,
    "LogLevel": "Info",
    "ElementNames": {
      "Value": "value",
      "Timestamp": "timestamp",
      "Metadata": "metadata"
    },
    "Schedules": [
      {
        "Name": "OpcuaToIotCore",
        "Interval": 150,
        "Description": "Read data from OPC UA tags and send it IoT Core to demo filters",
        "Active": true,
        "TimestampLevel": "Both",
        "Sources": {
          "OPCUA-SOURCE": [
            "*"
          ]
        },
        "Targets": [
          "IoTCoreTarget",
          "DebugTarget"
        ]
      }
    ],
    "ChangeFilters": {
      "ChangedBy50Percent": {
        "Type": "Percent",
        "Value": 50,
        "AtLeast": 60000
      }
    },
    "ValueFilters": {
      "OnlyWhenGreaterThan0": {
        "Operator": "gt",
        "Value": 0
      }
    },
    "ConditionFilters": {
      "TriggerFired": {
        "Operator": "present",
        "Value": ["TriggerTag"]
      }
    },
    "Transformations": {
      "TwoDigits": [
        {"Operator": "TruncAt", "Operand": 2}
      ]
    },
    "Sources": {
      "OPCUA-SOURCE": {
        "Name": "OPCUA-SOURCE",
        "ProtocolAdapter": "OPC-UA",
        "AdapterOpcuaServer": "OPCUA-SERVER-1",
        "Description": "Remote OPCUA test server",
        "SourceReadingMode": "Subscription",
        "SubscribePublishingInterval": 100,
        "Metadata": {
          "Some": "...arbitrary data",
          "Attached": "...to every message"
        },
        "Channels": {
          "TriggerTag": {
            "Name": "Trigger",
            "NodeId": "ns=3;i=1001",
            "ChangeFilter": "ChangedBy50Percent"
          },
          "DataTagToReadWhenTriggerFired": {
            "Name": "SomeRandomValue",
            "NodeId": "ns=3;i=1002",
            "ConditionFilter": "TriggerFired",
            "Metadata": {
              "More": "Metadata",
              "Attached": "...to this channel"
            }
          },
          "Rounded2Digits": {
            "Name": "RandomValueRounded",
            "NodeId": "ns=3;i=1002",
            "ConditionFilter": "TriggerFired",
            "Transformation": "TwoDigits",
            "Metadata": {
              "Digits": 2
            }
          },
          "Rounded2DigitsAndGreater0": {
            "Name": "RandomValueRoundedAndGreaterThan0",
            "NodeId": "ns=3;i=1002",
            "ConditionFilter": "TriggerFired",
            "Transformation": "TwoDigits",
            "ValueFilter": "OnlyWhenGreaterThan0",
            "Metadata": {
              "Digits": 2,
              "Cuttoff": 0
            }
          }          
        }
      }
    },
    "Targets": {
      "DebugTarget": {
        "Active": true,
        "TargetType": "DEBUG-TARGET"
      },
      "IoTCoreTarget": {
        "Active": true,
        "TargetType": "AWS-IOT-CORE",
        "Region": "${AWS_REGION}",
        "TopicName": "some/iot/topic"
      }
    },
    "TargetTypes": {
      "DEBUG-TARGET": {
        "FactoryClassName": "com.amazonaws.sfc.debugtarget.DebugTargetWriter"
      },
      "AWS-IOT-CORE": {
        "FactoryClassName": "com.amazonaws.sfc.awsiotcore.AwsIotCoreTargetWriter"
      }      
    },
    "AdapterTypes": {
      "OPCUA": {
        "FactoryClassName": "com.amazonaws.sfc.opcua.OpcuaAdapter"
      }
    },
    "ProtocolAdapters": {
      "OPC-UA": {
        "AdapterType": "OPCUA",
        "OpcuaServers": {
          "OPCUA-SERVER-1": {
            "Address": "opc.tcp://uademo.prosysopc.com",
            "Path": "OPCUA/SimulationServer",
            "Port": 53530,
            "ConnectTimeout": "10000",
            "ReadBatchSize": 500
          }
        }
      }
    }
  }
```

<br/>
With the file being created everything is set up so you can run the process from the folder of `example.json`:

```shell
sfcx -config example.json -info
```

### Observe result

The debug target prints the forwarded values, with their metadata, to the console. Once SFC runs, the data also becomes visible in AWS IoT Core.  

To observe the data in AWS IoT Core, log on to your AWS account, and use the built-in MQTT client  
of the AWS IoT Core console to subscribe to the topic named in the *IoTCoreTarget* definition.  
Also, make sure you are using the region set in `AWS_REGION`.

Docs used: [OPC UA adapter](../../docs/adapters/opcua.md) · [AWS IoT Core target](../../docs/targets/aws-iot-core.md) · [Debug target](../../docs/targets/debug.md) · [Data filtering](../../docs/sfc-data-processing-filtering.md#data-filtering) · [Change filter](../../docs/core/change-filter-configuration.md) · [Value filter](../../docs/core/value-filter-configuration.md) · [Condition filter](../../docs/core/condition-filter-configuration.md) · [TruncAt](../../docs/core/transformation-operator-configuration.md#truncat) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)

