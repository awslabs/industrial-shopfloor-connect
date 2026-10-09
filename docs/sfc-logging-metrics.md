# SFC Logging and metrics collection

- [Logging](#logging)

- [Metrics Collection](#metrics-collection)
  
  - [Running Metrics writers as an IPC service](#running-metrics-writers-as-an-ipc-service)
  - [Running metric writers in-process](#running-metric-writers-in-process)
  
  

# Logging

By default, log information is written to the console.

There are 4 log levels: Error (stderr), Warning, Info and Trace (stdout). Set them with `-error`, `-warning`, `-info` or
`-trace` on the command line of the SFC core or a protocol adapter, target or metrics writer service, or with the
top-level `"LogLevel"` key; `-nocolor` removes the ANSI colours (on Windows the output is never coloured).

Logging output will contain the system date and time, the logging level and a message; the `[Class:method]` source of
the event is shown only at Trace level. The logging infrastructure will intercept and blank the values of secrets
configured in the SFC configuration.

Instead of writing to the console, a custom log writer can be implemented and [configured](./core/sfc-configuration.md#logwriter). Details on how to implement a
custom log writer can be found in section [Custom Logging](./sfc-extending.md#custom-logging); template project:
[examples/custom-log-writer](../examples/custom-log-writer/README.md). With the uberjar, give the `LogWriter` entry an
empty `"JarFiles": []`; SFC ignores a `LogWriter` without the `JarFiles` key. For example, the template writer is
included in the uberjar:

```json
"LogWriter": {
  "JarFiles": [],
  "FactoryClassName": "com.amazonaws.sfc.log.CustomLogWriter"
}
```



## Metrics collection

Metrics collection is enabled by adding a Metrics configuration section in the top level of the SFC configuration. This section specifies the writer for metrics data, which can be either an in-process metrics writer (`MetricsWriter`) or a `MetricsServer`. In the uberjar the CloudWatch writer is built in, so set only its `FactoryClassName` (see [AWS CloudWatch Metrics](./metrics/aws-cloudwatch.md)); per-module in-process adds `"JarFiles": ["${SFC_DEPLOYMENT_DIR}/aws-cloudwatch-metrics/lib"]`; IPC uses `Writer.MetricsServer` with the address and port number of the service.

Metrics can be disabled by setting the "Enabled" property to false in the Metrics section. This disables metrics collection from all sources. A property "Namespace" can be set for use by the writer implementation, with a default value of "SFC". `CollectCoreMetrics` (default true) turns the metrics of the SFC core itself on or off.

The metrics collector automatically gathers warning and error messages from SFC logging. The default collection interval (`Metrics.Interval`) is 10 seconds, which can be modified by setting the "Interval" property to the desired time in seconds; `CloudWatch.Interval` (default 60) is how often the CloudWatch writer flushes.

```json
"Metrics": {
  "Writer": {
    "MetricsWriter": { "FactoryClassName": "com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriter" }
  },
  "CloudWatch": { "Region": "eu-west-1" }
}
```

All properties: [MetricsConfiguration](./core/metrics-configuration.md). Writers: [AWS CloudWatch writer](./metrics/aws-cloudwatch.md), all [metric writers](./metrics/README.md).

For each metrics data point the following information is collected:

- name
- value
- units
- timestamp
- dimensions

By default, the dimensions are:

- Source: name of the component that generated the datapoint. For protocol adapters this is the identifier of the
  adapter or the adapter and the source (separated by a ":" ) from the configuration. For targets the source is the
  identifier of the target from the configuration. For the core it is "SfcCore".
- Category: can be "Target", "Adapter" or "Core"
- Type: the actual type of the connector (e.g., "OpcuaAdapter"), target (e.g., "AwsSqsTargetWriter") or "SfcCore"

Additional dimensions can be added by adding a "CommonDimensions" property in the metrics section which is a map with
name-value pairs.

Additionally, each adapter or target can have a Metrics section with an Enabled property to enable or disable the
collection of metrics for that component, and a map of CommonDimensions which will be added to every data point
collected for that component.

Additional settings can be set for the actual configured writer. For the AWS CloudWatch Metrics writer they go in a
section named "CloudWatch" inside the Metrics section (region, credentials, write interval and batch size), see
[AWS CloudWatch Metrics](./metrics/aws-cloudwatch.md), which also names the `cloudwatch:PutMetricData` permission the
writer needs.

The following metric values are collected:

| **Metric name**         | **Description**                                               | **Collected by**                                                |
|-------------------------|---------------------------------------------------------------|-----------------------------------------------------------------|
| BytesReceived           | Bytes read by the adapter                                     | Modbus TCP                                                      |
| BytesSend               | Bytes sent by the adapter or target                           | Modbus TCP; MQTT, NATS, SiteWise Edge targets                   |
| BytesWritten            | Bytes written by target                                       | Most targets                                                    |
| ConnectionErrors        | Number of failed connections                                  | Adapters except J1939, REST and Simulator; OPC UA Writer target |
| Connections             | Number of connections                                         | Adapters except J1939, REST and Simulator; OPC UA Writer target |
| Errors                  | Number of logged errors                                       | Core and all connectors and targets                             |
| Memory                  | Used memory by process in MB                                  | Core, all adapters, targets except AWS Lambda and AWS MSK       |
| Messages                | Number of messages processed                                  | Core; targets except OPC UA and OPC UA Writer                   |
| MessagesBufferedCount   | Number of buffered messages                                   | StoreForwardTarget                                              |
| MessagesBufferedDeleted | Buffer cleanups that deleted messages                         | StoreForwardTarget                                              |
| MessagesBufferedSize    | Size of buffered messages in bytes                            | StoreForwardTarget                                              |
| ReadDuration            | Time in milliseconds used by adapter to read data from source | All adapters                                                    |
| ReadError               | Number of read errors                                         | Core; adapters except J1939, MQTT and NATS                      |
| Reads                   | Number of reads                                               | All adapters                                                    |
| ReadSuccess             | Number of succeeded reads                                     | All adapters                                                    |
| RecordsWritten          | Number of records written                                     | AWS S3 Tables target                                            |
| ValuesRead              | Number of values read                                         | All adapters                                                    |
| ValuesWritten           | Number of values written                                      | OPC UA Writer target                                            |
| Warnings                | Number of logged warnings                                     | Core and all connectors and targets                             |
| WriteDuration           | Time in milliseconds used by target to write data             | Targets except Router and Store and forward                     |
| WriteError              | Number of failed writes                                       | Core; targets except Debug and Store and forward                |
| Writes                  | Writes by targets                                             | All targets                                                     |
| WriteSuccess            | Number of successful writes                                   | Core and all targets                                            |



## Running Metrics writers as an IPC service.

The writers have a service wrapper that enables these writers to be executed as an IPC Service process. For each
writer, a tar file named after the module is generated by the build process (`aws-cloudwatch-metrics.tar.gz`) that
includes the script files to start the service, `bin/aws-cloudwatch-metrics` and `bin\aws-cloudwatch-metrics.bat`, as
well as all required libraries (`lib/*.jar`).

| **Writer**             | **Application name**   | **Main class**                                                 |
|------------------------|------------------------|----------------------------------------------------------------|
| AWS CloudWatch Metrics | aws-cloudwatch-metrics | com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriterService |

Start the service before SFC, on the port of the `Metrics.Writer.MetricsServer` entry:

**Linux / macOS**

```shell
aws-cloudwatch-metrics/bin/aws-cloudwatch-metrics -port 50050
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\aws-cloudwatch-metrics\lib\*" com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriterService -port 50050
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriterService -port 50050` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriterService -port 50050`).

On Windows, start the service with `java -cp` as shown, not with `bin\aws-cloudwatch-metrics.bat`; see [Platform support](./README.md#platform-support).

The writers do have all the following command line parameters in common.

| Parameter     | Description                                                                                                                                                                                                                                                                                                                                                                                            |
|---------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| -connection   | Currently ignored: the metrics service always listens in PlainText, so keep the `ConnectionType` of the `MetricsServer` entry at its default `PlainText`. Security level used to secure traffic between SFC core and metrics service. PlainText : No encryption ServerSideTLS : Data is encrypted, requires -cert and -key parameters MutualTLS : Data is encrypted, required -cert, ca and -key parameters The connection type must match the connection type, as set to the ConnectionType attribute for the client, to communicates with the metrics service. |
| -cert         | Currently ignored: the metrics service always listens in PlainText. Server certificate file to secure IPC (gRPC) traffic for connection types ServerSideTLS and MutualTLS                                                                                                                                                                                                                              |
| -key          | Currently ignored: the metrics service always listens in PlainText. Server private file to secure IPC (gRPC) traffic for connection types ServerSideTLS and MutualTLS                                                                                                                                                                                                                                  |
| -ca           | Currently ignored: the metrics service always listens in PlainText. CA certificate file to secure IPC (gRPC) traffic for connection type MutualTLS                                                                                                                                                                                                                                                     |
| -config       | Configuration file; the service then takes its port from `Metrics.Writer.MetricsServer.Port` in that file. Use only one of -config, -port and -envport.                                                                                                                                                                                                                                                |
| -envport      | The name of the environment variable that contains the port number for the service to listen on for requests.                                                                                                                                                                                                                                                                                          |
| -error        | Set log output level to error level. (Error message only)                                                                                                                                                                                                                                                                                                                                              |
| -h, -help     | Shows command line parameter help.                                                                                                                                                                                                                                                                                                                                                                     |
| -info         | Set log output level to info level. (Info, warning and error messages)                                                                                                                                                                                                                                                                                                                                 |
| -interface    | Network interface the service listens on. Default: the address the host name resolves to.                                                                                                                                                                                                                                                                                                              |
| -nocolor      | Turns off the colours of the log levels in the console output.                                                                                                                                                                                                                                                                                                                                        |
| -port         | port number for the service to listen on for requests.                                                                                                                                                                                                                                                                                                                                                 |
| -trace        | Set log output level to most detailed trace level (Info, warning, error, and detailed trace messages)                                                                                                                                                                                                                                                                                                  |
| -warning      | Set log output level to warning level. (Error and warning messages)                                                                                                                                                                                                                                                                                                                                    |

The port number, used by the service, can be specified using different methods which are applied in the following order

- The value of the `-port` command line parameter
- The value of the environment variable specified by the `-envport` parameter
- The `Port` of `Metrics.Writer.MetricsServer` in the configuration file passed with `-config`

After the service is started is it waiting for an initialization call on the specified port. The core is using an IPC
client to send the configuration data, which has common but also writer type specific elements, to the service that will
use it to initialize the actual writer. The client will use a client streaming method call to stream the metrics data to
the writer.

## Running metric writers in-process

To run metric writers in the same process as the SFC core, they need to be implemented for the same JDK as used for the
core. To make it possible to use a custom writer without making changes to the SFC code, there are no links in the core
to the libraries that implement the writer. In the configuration of an in-process metric writer type, the pathnames of
the jar files that contain the classes that implement the writer need to be explicitly configured, unless the writer is
already on the classpath, as in the uberjar. When the SFC core
creates an instance of the writer, it loads the configured jar files and uses a static factory method to create the
actual instance. The name of the factory class, which could be the actual writer class itself, needs to be configured as
well.

The jar files are part of the writer deployment and can be found in the lib directory of the deployment package
(`aws-cloudwatch-metrics.tar.gz`). To specify the path to the jar files it is recommended to use a placeholder, instead
of hard-coding, the directory where the adapter, targets and writers are deployed and set an environment variable for
this directory:

**Linux / macOS**

```shell
export SFC_DEPLOYMENT_DIR=/sfc
```

**Windows (PowerShell)**

```powershell
$env:SFC_DEPLOYMENT_DIR = "C:/sfc"
```

```json
"Writer": {
  "MetricsWriter": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/aws-cloudwatch-metrics/lib"],
    "FactoryClassName": "com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriter"
  }
}
```

With the uberjar, omit `JarFiles`: the CloudWatch writer is built in.

