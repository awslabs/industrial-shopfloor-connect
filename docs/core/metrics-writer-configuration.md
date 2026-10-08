## MetricsWriterConfiguration

[SFC Configuration](./sfc-configuration.md) > [Metrics](./metrics-configuration.md) > [Writer](./metrics-configuration.md#writer)

Defines how metrics data is written and transmitted, supporting two modes: in-process writer for direct metrics handling within the application, or IPC-based server configuration for writing metrics through a separate process. This configuration determines the mechanism used to output collected metrics data.

- [Schema](#schema)
- [Examples](#examples)

**Properties:**

- [MetricsServer](#metricsserver)
- [MetricsWriter](#metricswriter)

---
### MetricsServer
Specifies the configuration for an external metrics server that handles metrics data through IPC (Inter-Process Communication). This property defines the connection details (like address and port) for the remote metrics writing service.

The metrics writer service currently accepts PlainText connections only, so leave [ConnectionType](./server-configuration.md#connectiontype) at its default PlainText.

**Type**: [ServerConfiguration](./server-configuration.md )

---
### MetricsWriter
Defines the in-process metrics writer implementation configuration, specifying the factory class and, for module bundles only, the JarFiles containing the metrics writer code (omit JarFiles when running the uberjar). This configuration enables direct metrics handling within the same process as the application.

**Type**: [InProcessConfiguration](./in-process-configuration.md)

[^top](#metricswriterconfiguration)



## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "MetricsWriter": {
          "$ref": "#/definitions/InProcessConfiguration",
          "description": "In-process metrics writer configuration"
        }
      }
    },
    {
      "type": "object",
      "properties": {
        "MetricsServer": {
          "$ref": "#/definitions/ServerConfiguration",
          "description": "Metrics server configuration"
        }
      }
    }
  ]
}
```



## Examples

The examples use the [AWS CloudWatch metrics writer](../metrics/aws-cloudwatch.md) (module `aws-cloudwatch-metrics`). How the deployment modes differ: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
{
  "MetricsWriter": {
    "FactoryClassName": "com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriter"
  }
}
```



**In-process** - module bundle `aws-cloudwatch-metrics` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
{
  "MetricsWriter": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/aws-cloudwatch-metrics/lib"],
    "FactoryClassName": "com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriter"
  }
}
```



**IPC** - `MetricsServer` instead of `MetricsWriter`; the writer runs as its own service:

```json
{
  "MetricsServer": {
    "Address": "localhost",
    "Port": 50050
  }
}
```

Start the service before SFC, on the port of its `MetricsServer` entry:

**Linux / macOS**

```shell
aws-cloudwatch-metrics/bin/aws-cloudwatch-metrics -port 50050
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\aws-cloudwatch-metrics\lib\*" com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriterService -port 50050
```

On Windows use `java -cp` instead of `bin\aws-cloudwatch-metrics.bat`, see [Platform support](../README.md#platform-support).

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriterService -port 50050` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriterService -port 50050`).

[^top](#metricswriterconfiguration)

