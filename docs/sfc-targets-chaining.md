# Target Chaining

- [Target chaining](#target-chaining)
    - [Configuring a chain](#configuring-a-chain)
- [Store and forward target](#store-and-forward)
- [Router Target](#routing)



## Target chaining

Targets receive data from the SFC core to deliver to a target-specific destination, which could be a local store, a local service, or a cloud service. To enhance the functionality of target data delivery, for example to store and forward or to route the data, special intermediate targets can be configured between the sfc-core and the final targets. These intermediate targets create the instances of the targets they forward the data to. From the sfc-core's perspective, these intermediate targets appear as regular targets when writing data. 

However, they serve a unique purpose:

- Intermediate targets implement specific logic to process the received data. They then pass the processed data to the next targets in the chain. They provide a handler to subsequent targets for reporting delivery results.

- The data messages can be acknowledged (ACK) if successfully delivered to the destination, not acknowledged (NACK) when the target classifies the failure as temporary, or reported as an error otherwise (e.g., due to invalid data format). Intermediate targets can then take appropriate actions based on the results received from the next targets in the chain; the store and forward target buffers NACKed messages and deletes the ones reported as an error.

This strategy allows for the addition of new functionalities in data delivery to target destinations without modifying the actual end-targets. It provides a flexible and modular approach to extending the capabilities of the SFC system's data delivery process.

Developers: the `TargetResultHandler` that an intermediate target passes to the targets it creates is described in [Creating in-process adapter instances](./sfc-extending.md#creating-in-process-adapter-instances).



```mermaid
%%{init: {'theme':'base','themeVariables':{
  'background':'#0a0e14','primaryColor':'#0d1117','primaryTextColor':'#e6faff',
  'primaryBorderColor':'#1f6feb','lineColor':'#7d8590','fontFamily':'monospace',
  'clusterBkg':'#0a0e14','clusterBorder':'#1f6feb'}}}%%
flowchart LR
    CORE(["<b>SFC Core</b>"]):::core
    MID(["<b>Intermediate target</b><br/><i>e.g. store &amp; forward, router</i>"]):::tool
    END(["<b>Target</b><br/><i>the end destination</i>"]):::tool

    CORE == "target data" ==> MID
    MID == "target data" ==> END
    END -. "target results<br/>ack · nack · error" .-> MID
    MID -. "target results" .-> CORE

    classDef core fill:#0d1117,stroke:#ff6b35,stroke-width:2px,color:#ffd4c2,font-weight:bold;
    classDef tool fill:#0d1117,stroke:#1f6feb,stroke-width:2px,color:#e6faff,font-weight:bold;
    classDef data fill:#0d1117,stroke:#ff2bd6,stroke-width:1px,color:#ffb3f0;
    classDef aws fill:#0d1117,stroke:#b6ff00,stroke-width:2px,color:#d9ffb3;
    classDef ext fill:#0d1117,stroke:#7d8590,stroke-width:1px,color:#9aa4b2,stroke-dasharray:5 3;
```

<p align="center"><em>Target chaining</em></p>

### Configuring a chain

Reference only the intermediate target in the schedule; the targets behind it are listed in its `Targets` and defined in `Targets` like any other target. This example puts a store and forward target in front of an AWS S3 target (uberjar style, `FactoryClassName` only):

```json
"Schedules": [
  {
    "Name": "OpcuaToS3",
    "Interval": 1000,
    "Sources": { "OPCUA-SOURCE": ["*"] },
    "Targets": ["Buffered"]
  }
],
"Targets": {
  "Buffered": {
    "TargetType": "STORE-FORWARD",
    "Directory": "/var/sfc/buffer",
    "RetainFiles": 10000,
    "RetainPeriod": 1440,
    "Targets": ["S3Target"]
  },
  "S3Target": {
    "TargetType": "AWS-S3",
    "Region": "us-east-1",
    "BucketName": "YOUR_BUCKET_NAME"
  }
},
"TargetTypes": {
  "STORE-FORWARD": { "FactoryClassName": "com.amazonaws.sfc.storeforward.StoreForwardTargetWriter" },
  "AWS-S3": { "FactoryClassName": "com.amazonaws.sfc.awss3.AwsS3TargetWriter" }
}
```

The `Directory` must exist before SFC starts (on Windows write it with forward slashes, e.g. `"C:/sfc/buffer"`). In the in-process mode the `TargetTypes` entries add `JarFiles`, and a next target with a `TargetServer` runs as an IPC service, see [Configure a component in each mode](./sfc-deployment.md#configure-a-component-in-each-mode).

## Store and forward

The [Store and forward](./targets/store-and-forward-target.md) target is an intermediate target. It buffers the messages that the targets behind it could not deliver, based on the results these targets return, and resubmits the buffered data when they can deliver again.

**Current limitations:**

- Messages that the next target reports as an error are deleted, not buffered. The AWS IoT Core, Kinesis, Firehose, Lambda, S3, SiteWise and SQS targets return a NACK only when the service host name cannot be resolved or the connection pool is shut down, so for them a refused connection or a connect timeout counts as an error and those messages are lost. The AWS MSK target returns a NACK only on a timeout, the MQTT and SiteWise Edge targets only on a timeout or when they have no client, and the AWS SNS and AWS S3 Tables targets never.
- Enable metrics collection (a top-level `Metrics` section with a `Writer`, see [Metrics collection](./sfc-logging-metrics.md#metrics-collection)). Without it, the target stops resubmitting buffered messages once the next targets recover.
- Configure at least two of `RetainFiles`, `RetainPeriod` and `RetainSize`; a configuration with exactly one is rejected.



## Routing

The [Router Target](./targets/router.md) enables intelligent data routing by redirecting messages to alternate targets based on the delivery outcome of a primary target. Implemented as an intermediate target that can be configured between SFC-Core and end targets, it can be used for bundling data over a network, routing to alternative targets if data cannot be written to primary targets, and routing to a success target after successful delivery. The RouterTargetConfiguration schema defines the routing policy and routes, including primary, alternate, and success targets, allowing flexible configuration of the data flow through the processing pipeline.

> **Known issue:** a router that runs as an IPC service (with `TargetServer`) does not start yet: the core passes the service only the targets listed in the router's `Targets` property, not the targets of its `Routes`. Run the router in-process or from the uberjar.

A success target only receives data that its primary target acknowledged (ACK); data delivered through the alternate target is not forwarded to the success target.





