## TuningConfiguration

[SFC Configuration](./sfc-configuration.md) > [Tuning](./sfc-configuration.md#tuning) 

[SFC tuning](../sfc-tuning.md) parameters. Tuning parameters can be set to adjust sizes of internal channels and timeouts. The SFC log output will output messages when internal channels start blocking when these are at their maximum capacity or when timeouts occur waiting for a channel to unblock.

- [Schema](#schema)
- [Examples](#examples)


**Properties:**

- [AggregatorChannelSize](#aggregatorchannelsize)
- [AggregatorChannelTimeout](#aggregatorchanneltimeout)
- [AllSourcesReadTimeout](#allsourcesreadtimeout)
- [ChannelSizePerMetricsProvider](#channelsizepermetricsprovider)
- [MaxConcurrentSourceReaders](#maxconcurrentsourcereaders)
- [MetricsChannelTimeout](#metricschanneltimeout)
- [ScheduleReaderResultsChannelSize](#schedulereaderresultschannelsize)
- [ScheduleReaderResultsChannelTimeout](#schedulereaderresultschanneltimeout)
- [TargetForwardingChannelSize](#targetforwardingchannelsize)
- [TargetForwardingChannelTimeout](#targetforwardingchanneltimeout)
- [TargetResubmitChannelSize](#targetresubmitchannelsize)
- [TargetResubmitChannelTimeout](#targetresubmitchanneltimeout)
- [TargetResultsChannelSize](#targetresultschannelsize)
- [TargetResultsChannelTimeout](#targetresultschanneltimeout)
- [WriterInputChannelSize](#writerinputchannelsize)
- [WriterInputChannelTimeout](#writerinputchanneltimeout)

---
### AggregatorChannelSize
Specifies the size of the internal buffer used for sending data to the aggregator component. The default value is 1000 items. You can increase this value if you experience timeouts on **ScheduleReader:aggregationChannel**. Conversely, you can decrease it to reduce memory consumption used for aggregation operations. This setting helps balance throughput with memory usage in the aggregation process

**Type**: Int

Default is 1000

---
### AggregatorChannelTimeout
Specifies the timeout period (in milliseconds) for writing to the internal buffer that sends data to the aggregation component. The default value is 1000 milliseconds (1 second). If writing operations exceed this timeout, they will be considered failed. You should increase this value if you experience timeout errors on **ScheduleReader:aggregationChannel** and have limited available memory. This setting helps ensure reliable data flow to aggregation while preventing indefinite blocking

**Type**: Int

Default is 1000

---
### AllSourcesReadTimeout
Defines the maximum time (in milliseconds) allowed for completing reads from all configured data sources. The default value is 60000 milliseconds (60 seconds). If reading from all sources is not completed within this timeout period, the operation will be considered failed. This timeout helps prevent the system from hanging when there are issues with data source connectivity or responsiveness.

**Type**: Int

Default is 60000

---
### ChannelSizePerMetricsProvider
Specifies the buffer size allocated for each metrics provider in the internal metrics processor. The default value is 100 items. You can increase this value if you encounter timeouts on **MetricsProcessor:metricsChannel.** Alternatively, you can decrease it to reduce memory consumption. This setting helps balance the throughput of metrics processing with memory utilization.

**Type**: Int

Default is 100



---
### MaxConcurrentSourceReaders
Defines the maximum number of data sources that can be read simultaneously by a single SFC Schedule. The default value is 5 concurrent source readers. This setting controls the level of parallel processing when reading from multiple data sources, helping to balance system resource utilization and performance.

**Type**: Int

Default is 5

---
### MetricsChannelTimeout
Specifies the timeout period (in milliseconds) for writing to the internal metrics processor buffer. The default value is 10000 milliseconds (10 seconds). If writing operations exceed this timeout, they will be considered failed. You should increase this value if you experience timeout errors on metrics channels and have limited available memory. This setting helps ensure reliable metrics processing while preventing indefinite blocking

**Type**: Int

Default is 10000

---
### ScheduleReaderResultsChannelSize
Specifies the size of the internal buffer used for storing data read from sources. The default value is 10000 items. You can increase this value if you experience timeouts on **ScheduleReader:resultsChannel**. Conversely, you can decrease it to reduce memory consumption by the reader component. This setting helps balance read performance with memory utilization.

**Type**: Int

Default is 10000

Increment when getting timeouts on ScheduleReader:resultsChannel, reduce to limit memory use by reader

---
### ScheduleReaderResultsChannelTimeout
Specifies the timeout period (in milliseconds) for writing to the internal buffer when reading from sources. The default value is 5000 milliseconds (5 seconds). If writing operations exceed this timeout, they will be considered failed. You should increase this value if you experience timeout errors on **ScheduleReader:resultsChannel** and have limited available memory. This setting helps ensure reliable data reading while preventing indefinite blocking.

**Type**: Int

Default is 5000

---
### TargetForwardingChannelSize
Specifies the size of the internal buffer used for forwarding data between chained targets. The default value is 1000 items. You can increase this value if you experience timeouts on forwarding channels. Alternatively, you can decrease it to reduce memory consumption. This setting helps balance the throughput of data forwarding between chained targets with memory utilization

**Type**: Int

Default is 1000

Increment when getting timeouts on forwarding channels, reduce to limit memory use 

---
### TargetForwardingChannelTimeout
Specifies the timeout period (in milliseconds) for writing to the forwarding buffer used between chained targets. The default value is 1000 milliseconds (1 second). If writing operations exceed this timeout, they will be considered failed. You should increase this value if you experience timeout errors on forwarding channels and have limited available memory. This setting helps ensure reliable data forwarding while preventing indefinite blocking.

**Type**: Int

Default is 1000

---
### TargetResubmitChannelSize
Specifies the size of the internal buffer used for resubmitting data in chained targets. The default value is 100 items. You can increase this value if you experience timeouts on **resubmit** channels. Alternatively, you can decrease it to reduce memory consumption. This setting helps balance the throughput of data resubmission between chained targets with memory utilization

**Type**: Int

Default is 100

Increment when getting timeouts on resubmit channels, reduce to limit memory use 

---
### TargetResubmitChannelTimeout
Specifies the timeout period (in milliseconds) for writing to the resubmit buffer used by chained targets. The default value is 10000 milliseconds (10 seconds). If writing operations exceed this timeout, they will be considered failed. You should increase this value if you experience timeout errors on resubmit channels and have limited available memory. This setting helps ensure reliable data resubmission while preventing indefinite blocking

**Type**: Int

Default is 10000

---
### TargetResultsChannelSize
Specifies the size of the internal buffer used for storing target processing results. The default value is 1000 items. You can increase this value if you experience timeouts on **resultChannels**. Alternatively, you can decrease it to reduce memory consumption. This setting helps balance the throughput of target result processing with memory utilization.

**Type**: Int

Default is 1000

---
### TargetResultsChannelTimeout
Specifies the timeout period (in milliseconds) for writing to the target results buffer. The default value is 5000 milliseconds (5 seconds). If writing operations exceed this timeout, they will be considered failed. You should increase this value if you experience timeout errors on result channels and have limited available memory. This setting helps ensure reliable processing of target results while preventing indefinite blocking

**Type**: Int

Default is 5000

---
### WriterInputChannelSize
Specifies the size of the internal buffer used for sending data to writers. The default value is 10000 items. You can increase this value if you experience timeouts on **ScheduleReader:readerOutputChannel** (aggregated schedules: **com.amazonaws.sfc.ScheduleAggregator:readerOutputChannel**). Alternatively, you can decrease it to reduce memory consumption. This setting helps balance the throughput of data transmission to writers with memory utilization.

**Type**: Int

Default is 10000

---
### WriterInputChannelTimeout
Specifies the timeout period (in milliseconds) for writing to the internal buffer that sends data to writers. The default value is 1000 milliseconds (1 second). If writing operations exceed this timeout, they will be considered failed. You should increase this value if you experience timeout errors on readerOutputChannel and have limited available memory. This setting helps ensure reliable data transmission to writers while preventing indefinite blocking.

**Type**: Int

Default is 1000

[^top](#tuningconfiguration)



## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "AggregatorChannelSize": {
      "type": "integer",
      "default": 1000,
      "description": "Size of the aggregator channel"
    },
    "AggregatorChannelTimeout": {
      "type": "integer",
      "default": 1000,
      "description": "Timeout for aggregator channel in milliseconds"
    },
    "AllSourcesReadTimeout": {
      "type": "integer",
      "default": 60000,
      "description": "Timeout for reading from all sources in milliseconds"
    },
    "ChannelSizePerMetricsProvider": {
      "type": "integer",
      "default": 100,
      "description": "Channel size for each metrics provider"
    },
    "MaxConcurrentSourceReaders": {
      "type": "integer",
      "default": 5,
      "description": "Maximum number of concurrent source readers"
    },
    "MetricsChannelTimeout": {
      "type": "integer",
      "default": 10000,
      "description": "Timeout for metrics channel in milliseconds"
    },
    "ScheduleReaderResultsChannelSize": {
      "type": "integer",
      "default": 10000,
      "description": "Size of the schedule reader results channel"
    },
    "ScheduleReaderResultsChannelTimeout": {
      "type": "integer",
      "default": 5000,
      "description": "Timeout for schedule reader results channel in milliseconds"
    },
    "TargetForwardingChannelSize": {
      "type": "integer",
      "default": 1000,
      "description": "Size of the target forwarding channel"
    },
    "TargetForwardingChannelTimeout": {
      "type": "integer",
      "default": 1000,
      "description": "Timeout for target forwarding channel in milliseconds"
    },
    "TargetResubmitChannelSize": {
      "type": "integer",
      "default": 100,
      "description": "Size of the target resubmit channel"
    },
    "TargetResubmitChannelTimeout": {
      "type": "integer",
      "default": 10000,
      "description": "Timeout for target resubmit channel in milliseconds"
    },
    "TargetResultsChannelSize": {
      "type": "integer",
      "default": 1000,
      "description": "Size of the target results channel"
    },
    "TargetResultsChannelTimeout": {
      "type": "integer",
      "default": 5000,
      "description": "Timeout for target results channel in milliseconds"
    },
    "WriterInputChannelSize": {
      "type": "integer",
      "default": 10000,
      "description": "Size of the writer input channel"
    },
    "WriterInputChannelTimeout": {
      "type": "integer",
      "default": 1000,
      "description": "Timeout for writer input channel in milliseconds"
    }
  }
}

```



## Examples

Increase number of concurrent source readers

```json
{
  "MaxConcurrentSourceReaders": 10
}
```



Full configuration with the default values. Start from the defaults and change only the parameter named in a channel warning.

```json
{
  "AggregatorChannelSize": 1000,
  "AggregatorChannelTimeout": 1000,
  "AllSourcesReadTimeout": 60000,
  "ChannelSizePerMetricsProvider": 100,
  "MaxConcurrentSourceReaders": 5,
  "MetricsChannelTimeout": 10000,
  "ScheduleReaderResultsChannelSize": 10000,
  "ScheduleReaderResultsChannelTimeout": 5000,
  "TargetForwardingChannelSize": 1000,
  "TargetForwardingChannelTimeout": 1000,
  "TargetResubmitChannelSize": 100,
  "TargetResubmitChannelTimeout": 10000,
  "TargetResultsChannelSize": 1000,
  "TargetResultsChannelTimeout": 5000,
  "WriterInputChannelSize": 10000,
  "WriterInputChannelTimeout": 1000
}
```



