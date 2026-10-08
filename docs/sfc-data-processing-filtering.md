# SFC data processing and filtering


- [SFC Dataflow](#sfc-dataflow)

- [Transformations](#transformations)

- [Data Filtering](#data-filtering)
    - [Data Change Filters](#data-change-filters)

    - [Value Filters](#value-filters)

    - [Condition Filters](#condition-filters)

- [Template transformations](#template-transformations)

    

## SFC dataflow

The data collected by the SFC source connector is processed by an internal data pipeline that consists of the following
steps:

- Data collected is read from connector
- Data transformations are applied on individual values if a transformation for a value has been configured.
- Data change filtering is applied at value or source level. Data change filters only let values pass if the new value
  differs from a previously passed value with at least a configured percentage or absolute value, or, while the value
  stays exactly the same, when a configured time period has passed since passing the last value. If a change filter is
  configured at source and value level, then the filter at value level takes precedence.
- Data value filters are applied at value level if a filter has been configured for that value. The value is
  passed if it matches the filter expression which can consist of a combination of one or
  more `==`, `!=`, `>`, `>=`, `<`, `<=`, `&&`, `||` operators. For non-numeric values only the `==` and `!=` operators
  can be used.
- Condition filters are applied at value level if a filter has been configured for that value. The value is passed
  if other values of the same source exist, or do not exist, as the filter specifies.
- Composition of values into structures or decomposing from structures into structures is applied based on source and channel configurations.
- Spreading elements from list values into separate values based on channel configuration.
- If data aggregation is specified the values are buffered until the specified aggregation size is reached. The output
  of an aggregation can be one or more output values from an aggregation (`avg`, `min`, `max`, etc.) on the collected
  values and/or the collected values.
- Data transformations are applied on the aggregated data output values if a transformation is configured for that
  specific output.
- Data values are named according to their configured names. Metadata and timestamp information is added at configured
  levels (top, source and value) as configured.
- The data is transmitted to the configured targets where additional buffering or target specific processing is done.
  Selected targets support the transformation of the data submitted to their destinations by configuring an Apache
  Velocity template that is applied on that data.

```
Source data -> Transformation (*) -> Change filter (*) -> Value filter (*) -> Condition filter (*) -> Decompose / spread / compose (*) -> Aggregation with output transformations (*) -> Naming, timestamps, metadata -> Template or Formatter (*) -> Target
```

(`*`) optional, only applied if configured

[^top](#sfc-data-processing-and-filtering)

## Transformations

Individual values can be transformed by configuring a transformation for the channel.

The configuration snippet below shows how a transformation named "ToInteger" is applied to the channels by setting the "Transformation" setting to the name of this transformation.

```json
"Channels": {
  "SimulationSawtoothInt": {
    "NodeId": "ns=3;i=1003",
    "Transformation": "ToInteger"
  },
  "SimulationSquareInt": {
    "NodeId": "ns=3;i=1005",
    "Transformation": "ToInteger"
  }
}
```

Transformations, which are lists of transformation operators, are defined at the top-level of the sfc-configuration. The operators in a transformation are applied on the values in the listed order.

Below is an example of a "Transformations" section defining 3 transformations, including the "ToInteger" one mentioned above. This transformation first gets the absolute value from the input value, it then rounds it and explicitly converts it into an Integer value. SFC will validate if the input value, or the resulting value of an operator, is valid for the input of the first or next operator of a transformation.

A configured operator consists of the name of the operator specified by the "Operator" setting and in case the operator takes arguments, the value of the argument specified by the "Operand" setting.
Transformations can also be applied to aggregated data if a schedule has an aggregation setup. See the setting "Transformations" in  [Aggregation](./core/aggregation-configuration.md) for more details.


See [TransformationOperator configuration](./core/transformation-operator-configuration.md) for a list of all available operators.


```json
  "Transformations": {
    "ToInteger": [
      {"Operator": "Abs"},
      {"Operator": "Round"},
      {
        "Operator": "ToInt"
      }
    ],
    "ToDegreesCelsius": [
      {"Operator": "Celsius"},
      {"Operator": "TruncAt", "Operand": 2}
    ],
    "TwoDigits": [
      {"Operator": "TruncAt", "Operand": 2}
    ]
  }
```

**Runnable examples:** [OPC UA to AWS IoT Core using filters](../examples/opcua-to-iot-using-filters/README.md) (`TruncAt`), [S7 to an OPC UA data model](../examples/in-process-s7-opcua/README.md) (`Celsius`).


## Data Filtering

The data read from the source can be filtered in three steps: change filters, value filters, then condition filters.
All steps are optional and can be applied individually.

Filters are defined by name at the top level of the configuration and referenced from a source (`ChangeFilter`) or a
channel (`ChangeFilter`, `ValueFilter`, `ConditionFilter`):

```json
"ChangeFilters": {
  "Deadband1": { "Type": "Absolute", "Value": 1.0, "AtLeast": 60000 }
},
"ValueFilters": {
  "Positive": { "Operator": "gt", "Value": 0 }
},
"ConditionFilters": {
  "Triggered": { "Operator": "present", "Value": ["TriggerTag"] }
},
"Sources": {
  "OPCUA-SOURCE": {
    "ProtocolAdapter": "OPC-UA",
    "ChangeFilter": "Deadband1",
    "Channels": {
      "TriggerTag": { "NodeId": "ns=3;i=1001" },
      "Measurement": {
        "NodeId": "ns=3;i=1002",
        "ValueFilter": "Positive",
        "ConditionFilter": "Triggered"
      }
    }
  }
}
```

**Runnable example:** [OPC UA to AWS IoT Core using filters](../examples/opcua-to-iot-using-filters/README.md) uses all three filter types.

### Data Change Filters

A [data change filter](./core/change-filter-configuration.md) can be configured at source and channel values level. If a filter is configured at source level it
is applied on all values for that source. Filters configured at value level take precedence over a filter at source
level. Values only pass a filter if a value has changed at least, or beyond, a configured value since the last value
that was passed. This value can be a percentage or absolute value. The initial value will always pass the filter. With
AtLeast (in milliseconds), a value exactly equal to the last value that passed is passed again once AtLeast
milliseconds have elapsed; values that changed by less than the configured Value stay filtered. Absolute and Percent
need numeric values, while Always also works for strings and booleans.

Current limitations: Always compares every value with the first value that passed, not with the last one, so without
AtLeast the values A, B, A, B pass as A, B, B; Percent passes every value while the last value that passed is negative.


### Value Filters

A [value filter](./core/value-filter-configuration.md) will pass a value if it matches a filter expression. A filter expression can consist of one or
more operators like `==`,`!=`,`>`,`>=`,`<`,`<=`, combined in `&&` and `||` groups. For non-numeric values, only the ==
and != operators can be used. Word forms work too: `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `and`, `or`.

Never apply `>`, `>=`, `<` or `<=` to non-numeric values: the comparison fails and the schedule stops producing output
until SFC is restarted.

### Condition Filters

After applying the change and value filters, if any, [Condition filters](./core/condition-filter-configuration.md) can be used to select values based on other values from the same source. This makes it possible to include or exclude values if other values or combinations of values exist or do not exist in the same source. Operators that can be used include:

- ***any*** : Any of a list of values must exist

```json
  {
        "Operator" : "any",
        "Value"    : ["a","b"]
  }
```

At least one of a or b must exist for this source to include the value on which this filter is applied.

- ***none*** : None of a list of values must exist
```json
{
  "Operator": "none",
  "Value": ["a", "b" ]
}
```

Neither a nor b may exist for the source to include the value on which this filter is applied

- ***all*** : All values of a list of other values must exist

```json
{
  "Operator": "all",
  "Value": ["a", "b"]
}
```

Both value a and b must exist for source to include the value on which this filter is applied

- ***present*** : A specified value must exist

```json
{
  "Operator": "present",
  "Value": [
    "a"
  ]
}
```

Value a must exist for source to include the value on which this filter is applied

- **absent**:  A specified value may not exist

```json
{
  "Operator": "absent",
  "Value": [
    "a"
  ]
}
```

Value a must not exist for source to include the value on which this filter is applied

- ***only*** : The value must be the only value from a source

```json
{
  "Operator": "only",
  "Value": true
}
```

If value is true then the value on which the filter is applied is only included if it is the only value for that source.

If value is false then the value on which the filter is applied is only included if it is not the only value for that
source.

- ***notonly*** : The value must not be the only value from a source

```json
{
  "Operator": "notonly",
  "Value": true
}
```

If value is true then the value on which the filter is applied is only included if it not the only value for that
source.

If value is false then the value on which the filter is applied is only included if it is the only value for that
source.

All the operators above can be combined using the ***and*** and ***or*** operator, which take filter or a list of
filters as the filter value.

```json
{
  "Operator": "and",
  "Value": [
    {
      "Operator": "only",
      "Value": "false"
    },
    {
      "Operator": "all",
      "Value": [
        "a",
        "b"
      ]
    }
  ]
}
```



Filters are applied to values in the source configuration. A value is included when it is not the only value for that source, and both values 'a' and 'b' must exist for that source.

The names used as values for the filters correspond to the keys in the channel configuration of the source (not the 'name' value used to set the name of the value in the output). For structured values with sub-values, these can be specified by adding a '.' followed by the name of these fields, e.g., 'ServerStatus.state'.

Condition filters use JMESPath syntax (https://jmespath.org/) to match the names of values and their sub-values, allowing the use of full JMESPath syntax to build complex filters.

If a field name, or part of it, contains non-alphanumeric characters, it must be enclosed in double quotes, e.g., "System-Status", "System-Status".state, "System.Status".state.

Condition filters are defined as a map in the 'ConditionFilters' section of the configuration. The name of an entry defining a filter can be used as the value of the 'ConditionFilter' for a channel to apply that filter to the channel.



## Template Transformations

Targets that support it can reshape their output with an Apache [Velocity](https://velocity.apache.org/) template set in the target [Template](./core/target-configuration.md#template) property; see [Target data transformation templates](./sfc-target-templates.md).


