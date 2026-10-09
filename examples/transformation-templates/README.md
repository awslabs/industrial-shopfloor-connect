# Transformation Templates

Example target templates for transforming SFC target data to CSV, XML and YAML formats. How templates work:
[SFC Target data transformation templates](../../docs/sfc-target-templates.md).

| File | Output |
|---|---|
| [DataToCSV.vm](./DataToCSV.vm) | One CSV line per value: source, value name, value and timestamp |
| [AggregatedDataToCSV.vm](./AggregatedDataToCSV.vm) | One CSV line per value with its `count`, `avg`, `min`, `max` and `stddev` aggregations |
| [DataToXML.vm](./DataToXML.vm) | XML, including metadata and the source and value timestamps |
| [DataToYaml.vm](./DataToYaml.vm) | YAML, including metadata and the source and value timestamps |

## Use it

Name a template file in the [Template](../../docs/core/target-configuration.md#template) property of a target, for
example the `DebugTarget` of the [Quickstart `simulator.json`](../../README.md#2-helloworld-simulator-example),
which prints the result to the console:

```json
"Targets": {
  "DebugTarget": {
    "Active": true,
    "TargetType": "DEBUG-TARGET",
    "Template": "DataToCSV.vm"
  }
}
```

Copy the template next to the configuration and start SFC in that directory (the same command in Windows PowerShell):

```shell
sfcx -config simulator.json -info
```

- A relative `Template` path resolves against the directory SFC is started from. On Windows, write an absolute path
  with forward slashes, e.g. `"Template": "C:/sfc/templates/DataToCSV.vm"`.
- The Quickstart schedule sets `"TimestampLevel": "Both"`, so the data has timestamps at source and value level, which
  `DataToXML.vm` and `DataToYaml.vm` use; set it the same way when you use these two templates. `DataToCSV.vm` leaves
  its timestamp column empty when the `TimestampLevel` is neither `Channel` nor `Both`.
- `AggregatedDataToCSV.vm` needs a schedule with an [Aggregation](../../docs/core/aggregation-configuration.md) whose
  `Output` includes `count`, `avg`, `min`, `max` and `stddev` for every value.
- The templates use the default [ElementNames](../../docs/core/sfc-configuration.md#elementnames) (`schedule`,
  `sources`, `values`, `value`, `timestamp`, `metadata`); adapt them if your configuration renames these elements.
- A target takes a `Template` or a [Formatter](../../docs/core/target-configuration.md#formatter), not both.

Docs used: [Target templates](../../docs/sfc-target-templates.md) · [Template](../../docs/core/target-configuration.md#template) · [Aggregation](../../docs/core/aggregation-configuration.md) · [All examples](../../docs/examples/README.md)
