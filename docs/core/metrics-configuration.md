## MetricsConfiguration

[SFC Configuration](./sfc-configuration.md) > [Metrics](./sfc-configuration.md#metrics)

Configuration section for metrics collection and management in SFC, controlling how operational metrics are gathered and output. Settings include collection intervals, core metrics toggle, custom dimensions, and namespace organization. Supports both IPC and in-process writer implementations through a required Writer configuration that determines how metrics data is processed and stored. Adapters and targets have their own `Metrics` section with only Enabled and CommonDimensions, see [MetricsSourceConfiguration](./metrics-source-configuration.md).

- [Schema](#schema)
- [Examples](#examples)

**Properties:**

- [CollectCoreMetrics](#collectcoremetrics)
- [CommonDimensions](#commondimensions)
- [Enabled](#enabled)
- [Interval](#interval)
- [Namespace](#namespace)
- [Writer](#writer)

---
### CollectCoreMetrics
Controls whether detailed core system metrics are collected. When enabled (default), gathers fundamental performance and operational metrics from the SFC core components.

**Type**: Boolean

Default is true

---
### CommonDimensions
Defines additional contextual key-value pairs that are automatically attached to every metric datapoint collected. These dimensions help categorize and filter metrics, such as environment, location, or deployment identifiers.

**Type**: Map(String,String)

Optional

---
### Enabled
Master switch for the entire metrics collection system. When true (default), the metrics collection system is active and gathering data. When false, all metrics collection is disabled regardless of other settings.

**Type**: Boolean

Default is true

---
### Interval
Specifies how frequently (in seconds) the system collects metrics from all sources - adapters, targets, and core components. Default value is 10 seconds; must be at least 1 second.

**Type**: Integer

Default is 10

---
### Namespace
Defines the organizational container name that groups all collected metrics. Default value is "SFC". The namespace helps isolate and identify metrics from different applications or components within the monitoring system.

**Type**: String

Default is "SFC"

---
### Writer
Specifies the configuration for the component responsible for outputting collected metrics data. This required property determines how and where metrics are written, supporting both IPC and in-process implementations for metrics storage or transmission.

**Type**: [MetricsWriterConfiguration](./metrics-writer-configuration.md)

For the AWS CloudWatch writer add a `CloudWatch` object (`Region`, `CredentialProviderClient`, `Interval`, `BatchSize`) next to `Writer` in this Metrics section; see [AWS CloudWatch Metrics](../metrics/aws-cloudwatch.md) and [Metrics collection](../sfc-logging-metrics.md#metrics-collection).

[^top](#metricsconfiguration)

## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "CollectCoreMetrics": {
      "type": "boolean",
      "description": "Flag to enable/disable collection of core metrics",
      "default": true
    },
    "CommonDimensions": {
      "type": "object",
      "description": "Map of dimension names to values, both strings",
      "patternProperties": {
        "^.*$": {
          "type": "string"
        }
      },
      "additionalProperties": false
    },
    "Enabled": {
      "type": "boolean",
      "description": "Flag to enable/disable metrics collection",
      "default": true
    },
    "Interval": {
      "type": "integer",
      "description": "Interval in seconds for metrics collection",
      "minimum": 1,
      "default": 10
    },
    "Namespace": {
      "type": "string",
      "description": "Namespace for the metrics",
      "default": "SFC"
    },
    "Writer": {
      "$ref": "#/definitions/MetricsWriterConfiguration",
      "description": "The metrics writer implementation configuration"
    }
  },
  "required": [
    "Writer"
  ]
}
```



## Examples

The examples use the AWS CloudWatch metrics writer. How the deployment modes differ: [Configure a component in each mode](../sfc-deployment.md#configuration-in-each-mode).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
{
  "Enabled": true,
  "Interval": 60,
  "CommonDimensions": {
    "Environment": "Production",
    "Plant": "us-west"
  },
  "Writer": {
    "MetricsWriter": {
      "FactoryClassName": "com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriter"
    }
  },
  "CloudWatch": {
    "Region": "eu-west-1"
  }
}
```



**In-process** - module bundle `aws-cloudwatch-metrics` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
{
  "Enabled": true,
  "Interval": 60,
  "CommonDimensions": {
    "Environment": "Production",
    "Plant": "us-west"
  },
  "Writer": {
    "MetricsWriter": {
      "JarFiles": ["${SFC_DEPLOYMENT_DIR}/aws-cloudwatch-metrics/lib"],
      "FactoryClassName": "com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriter"
    }
  },
  "CloudWatch": {
    "Region": "eu-west-1"
  }
}
```



**IPC** - `MetricsServer` instead of `MetricsWriter`; the writer runs as its own service:

```json
{
  "Interval": 60,
  "CommonDimensions": {
    "Environment": "Production",
    "Plant": "us-west"
  },
  "Writer": {
    "MetricsServer": {
      "Address": "localhost",
      "Port": 50050
    }
  },
  "CloudWatch": {
    "Region": "eu-west-1"
  }
}
```

Start the service before SFC, on the port of its `MetricsServer` entry: see [MetricsWriterConfiguration examples](./metrics-writer-configuration.md#examples).

[^top](#metricsconfiguration)
