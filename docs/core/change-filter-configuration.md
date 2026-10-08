## ChangeFilterConfiguration

[SFC Configuration](./sfc-configuration.md) > [ChangeFilters](./sfc-configuration.md#changefilters)

A change filter passes a channel value only if it differs enough from the last value that passed the filter (Type Always compares with the first value that passed, see [Type](#type)). With [AtLeast](#atleast), an unchanged value is passed again after a minimum interval.

For more information see [DataFiltering](../sfc-data-processing-filtering.md#data-filtering)

Reference a change filter by its ID from a [source](./source-configuration.md#changefilter) (applies to all its channels) or a [channel](./channel-configuration.md#changefilter) (overrides the source). It sees the value after the channel transformation. Absolute and Percent work on numeric values only; use Always for strings and booleans. Percent is relative to the last value that passed.

- [Schema](#schema)
- [Examples](#examples)


**Properties:**
- [AtLeast](#atleast)
- [Type](#type)
- [Value](#value)

---
### AtLeast
Interval in milliseconds. If the value is exactly equal to the last value that passed (for Type Always: the first value that passed), it is passed again once AtLeast milliseconds have elapsed since that value last passed. Values that changed by less than [Value](#value) stay filtered; AtLeast does not force them through.

**Type**: Long

---
### Type
The Type property defines how changes in values are evaluated by the filter. It accepts three possible values:

- "Absolute": Filters based on the absolute numerical difference between values
- "Percent": Filters based on the relative percentage change between values. Known limitation: while the last value that passed is negative, every changed value passes
- "Always": Passes every value that differs from the first value that passed. A value equal to that first value counts as unchanged, so without AtLeast the values A, B, A, B pass as A, B, B

If not specified, it defaults to "Always". This property determines the method used to compare current and previous values when deciding whether to pass or filter the data

**Type**: String

---
### Value
- The Value property specifies the threshold amount that determines when a change should be filtered. Its interpretation depends on the Type setting:
  - For "Absolute" type: Represents the minimum absolute numerical difference required between values
  - For "Percent" type: Represents the minimum percentage change required between values
  - For "Always" type: This value is ignored

The default value is 0.0. The value must be greater than or equal to 0 (this is not checked at startup)

**Type**: Double

Default is 0.0

[^top](#changefilterconfiguration)



## Schema



```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "Type": {
      "type": "string",
      "enum": [
        "Absolute",
        "Percent",
        "Always"
      ],
      "default": "Always",
      "description": "Type of change filter to apply"
    },
    "Value": {
      "type": "number",
      "default": 0.0,
      "description": "Threshold value for the filter"
    },
    "AtLeast": {
      "type": "integer",
      "description": "Interval in milliseconds to pass a value again when it did not change"
    }
  },
  "additionalProperties": false
}
```



## Examples

Absolute change filter:

```json
{
  "Type": "Absolute",
  "Value": 5.0
}
```



Percentage change filter:

```json
{
  "Type": "Percent",
  "Value": 10.0
}
```



Any change:

```json
{
  "Type": "Always"
}
```



Absolute change filter, with at least a value every 5 seconds even when value did not change

```json
{
  "Type": "Absolute",
  "Value": 5.0,
  "AtLeast" : 5000
}
```



**Runnable example:** [OPC UA to AWS IoT Core using filters](../../examples/opcua-to-iot-using-filters/README.md) (Percent filter with AtLeast on a trigger channel).

[^top](#changefilterconfiguration)
