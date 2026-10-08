# Target Adapters

Shop Floor Connectivity target connectors enable data transmission from industrial devices to various destinations. These connectors handle the delivery of collected data, applying optional transformations using Apache Velocity templates. The following list details the available target connectors that can be configured to send your industrial data to different services and endpoints.

Each target page has a *Deploy this target* section for the [uberjar, in-process and IPC modes](../sfc-deployment.md#configure-a-component-in-each-mode); the fixed `TargetType` value (required in every mode), `FactoryClassName` and IPC service class of every target are listed in [Target types and classes](../sfc-running-targets.md#target-types-and-classes). Runnable configurations: [examples catalog](../examples/README.md#start-here).

## Service targets

- **[AWS IoT Core Service](./aws-iot-core.md)**

  AWS IoT Core is a managed cloud service that enables connected devices to securely interact with cloud applications and other devices.

- **[AWS Kinesis](./aws-kinesis.md)**

  Amazon Kinesis Data Streams ingests and stores data streams for real-time processing.

- **[AWS Kinesis Firehose](aws-kinesis-firehose.md)**

  Amazon Kinesis Data Firehose is a managed service for ingesting and delivering streaming data in real-time.

- **[AWS Lambda ](./aws-lambda.md)**

  AWS Lambda is a serverless compute service that runs code in response to events and manages underlying resources.

- **[AWS MSK](./aws-msk.md)**

  Amazon MSK is a fully managed service for running Apache Kafka workloads without infrastructure management.

- **[AWS S3](./aws-s3.md)**

  Amazon S3 is a highly scalable object storage service.

- **[AWS S3-Tables](./aws-s3-tables.md)**

  Amazon S3 Tables stores tabular data as Apache Iceberg tables in table buckets.

- **[AWS SiteWise](./aws-sitewise.md)**

  AWS IoT SiteWise is a managed service for collecting, organizing, and monitoring industrial equipment data at scale.

- **[AWS SiteWise Edge](./aws-sitewiseedge.md)**

  Sends data over MQTT to an on-premises AWS IoT SiteWise Edge gateway.

- **[AWS SNS](./aws-sns.md)**

  Amazon SNS is a managed pub/sub messaging service for decoupled application communications.

- **[AWS SQS](./aws-sqs.md)**

  Amazon SQS is a managed message queuing service for decoupling distributed applications.

## Local targets

- **[Debug](./debug.md)**

  Console target outputs collected industrial data to standard output for monitoring and debugging.

- **[File](./file.md)**

  File target writes collected industrial data to files on the local filesystem

- **[MQTT](./mqtt.md)**

  MQTT target publishes collected industrial data to topics on an MQTT message broker.

- **[NATS](./nats.md)**

  NATS target streams collected industrial data to subjects on a NATS messaging system.

- **[OPCUA](./opcua.md)**

  OPC UA server target exposes collected industrial data through a target-hosted OPC UA server for client access. Examples: [Simulation to OPC UA](../adapters/simulator.md#simulation-to-opc-ua-example) (no hardware), [in-process-s7-opcua](../../examples/in-process-s7-opcua/README.md).

- [**OPCUA Writer**](./opcua-writer.md)

  OPCUA target writing data to nodes of an external OPCUA server. Example: [in-process-iot-core-opcua-write](../../examples/in-process-iot-core-opcua-write/README.md).


## Intermediate adapters

These targets sit between the SFC core and other targets, see [target chaining](../sfc-targets-chaining.md).

- **[Router](./router.md)**

  Routing target redirects data to alternate targets based on primary target delivery success or failure.

- **[Store and Forward](./store-and-forward-target.md)**

  Buffer target temporarily stores industrial data in local storage when primary target loses connectivity, ensuring data preservation and forwarding after connection restoration.
