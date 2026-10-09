[SFC Configuration](../core/sfc-configuration.md) > [Metrics](../core/sfc-configuration.md#metrics) 

# AWS CloudWatch Metrics



The [Amazon CloudWatch Metrics](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/working_with_metrics.html) Writer is a metrics writer for Shop Floor Connectivity (SFC) that publishes metrics data collected by SFC components to Amazon CloudWatch Metrics. This enables monitoring and analysis of industrial device and SFC operational data through CloudWatch's visualization, alerting, and analytics capabilities. The writer publishes SFC metrics as standard-resolution CloudWatch metrics. The namespace is the `Namespace` of the Metrics section, and `CommonDimensions` there add dimensions, see [Metrics collection](../sfc-logging-metrics.md#metrics-collection).

## Deploy this metrics writer

The writer has no type code: it is set in the `Writer` of the top-level `Metrics` section, and its own settings go in `Metrics.CloudWatch` ([AwsCloudWatchConfiguration](#awscloudwatchconfiguration)). How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode). All metrics settings: [MetricsConfiguration](../core/metrics-configuration.md).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"Metrics": {
  "Writer": {
    "MetricsWriter": { "FactoryClassName": "com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriter" }
  },
  "CloudWatch": { "Region": "eu-west-1" }
}
```

**In-process** - module bundle `aws-cloudwatch-metrics` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"Metrics": {
  "Writer": {
    "MetricsWriter": {
      "JarFiles": ["${SFC_DEPLOYMENT_DIR}/aws-cloudwatch-metrics/lib"],
      "FactoryClassName": "com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriter"
    }
  },
  "CloudWatch": { "Region": "eu-west-1" }
}
```

**IPC** - `MetricsServer` instead of `MetricsWriter`; the writer runs as its own service:

```json
"Metrics": {
  "Writer": {
    "MetricsServer": { "Address": "localhost", "Port": 50050 }
  },
  "CloudWatch": { "Region": "eu-west-1" }
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

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriterService -port 50050` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriterService -port 50050`).

The process that runs the writer needs `cloudwatch:PutMetricData`.

**Examples:** none yet - add the uberjar `Metrics` section above to [Quickstart step 2](../../README.md#2-helloworld-simulator-example). All: [examples catalog](../examples/README.md)

## AwsCloudWatchConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [Metrics](../core/sfc-configuration.md#metrics) 

The AwsCloudWatchConfiguration class defines the configuration settings for the AWS CloudWatch Metrics Writer, set as `CloudWatch` in the `Metrics` section. It defines region, credentials, batch size and publishing interval for the CloudWatch service.

Writer channel: two top-level keys of the configuration set the writer's internal buffer channel, `CloudWatchMetricsChannelSize` (default 1000) and `CloudWatchMetricsChannelTimeout` (default 10000 ms). When sending to that channel blocks or times out, the writer's log message names the key to raise. An IPC service does not receive them and uses the defaults.

- [Schema](#schema)
- [Example](#example)

**Properties:**

- [BatchSize](#batchsize)
- [CredentialProviderClient](#credentialproviderclient)
- [Interval](#interval)
- [Region](#region)



---
### BatchSize
The BatchSize property determines how many data points are collected in a buffer before being written as a single batch to the CloudWatch service. This batching helps optimize API calls and improve throughput. The maximum allowed value is 1000 data points, which is also the default value if not specified.

**Type**: Int

Default and max value is 1000

---
### CredentialProviderClient
The CredentialProviderClient property specifies which AWS credential provider client to use for authentication. It references a client defined in the SFC's top-level configuration under [AwsIotCredentialProviderClients](../core/sfc-configuration.md#awsiotcredentialproviderclients) section. This client uses X.509 certificates to obtain temporary AWS credentials through the  [AWS IoT credentials provider](../sfc-aws-service-credentials.md).

If no CredentialProviderClient is configured the [AWS Java SDK credential provider chain is used](https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/credentials.html#credentials-chain)

**Type:** String

---
### Interval
The Interval property defines the time period (in seconds) between writes to the CloudWatch service. Buffered metrics will be published when this interval expires, or earlier if the buffer reaches the configured [BatchSize](#batchsize). This helps optimize the frequency of API calls while ensuring timely delivery of metrics. If not specified, the default interval is 60 seconds.

**Type**: Integer

---
### Region
The Region property specifies the AWS Region where the CloudWatch metrics will be published. This should be set to the AWS Region identifier where you want your metrics to be stored and accessed (e.g., "us-east-1", "eu-west-1"). If not specified, the writer will use the default region configured in the AWS SDK through environment variables, configuration files, or instance metadata.

**Type**: String



[^top](#aws-cloudwatch-metrics)



## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AwsCloudWatchConfiguration",
  "type": "object",
  "properties": {
    "BatchSize": {
      "type": "integer",
      "description": "Size of the batch for CloudWatch metrics",
      "minimum": 1,
      "maximum": 1000,
      "default": 1000
    },
    "CredentialProviderClient": {
      "type": "string",
      "description": "Name of the AWS IoT credentials provider client"
    },
    "Interval": {
      "type": "integer",
      "description": "Interval in seconds between metrics submissions",
      "minimum": 1,
      "default": 60
    },
    "Region": {
      "type": "string",
      "description": "AWS region for CloudWatch"
    }
  }
}

```

## Example

```json
{
  "Metrics": {
    "Writer": {
      "MetricsWriter": {
        "FactoryClassName": "com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriter"
      }
    },
    "CloudWatch": {
      "BatchSize": 500,
      "CredentialProviderClient": "MyAwsCredentialsProvider",
      "Interval": 120,
      "Region": "us-west-2"
    }
  }
}

```