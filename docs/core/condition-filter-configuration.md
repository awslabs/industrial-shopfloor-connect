## ConditionFilterConfiguration

[SFC Configuration](./sfc-configuration.md) > [ConditionFilters](./sfc-configuration.md#conditionfilters)

A condition filter passes a channel value only if other channels of the same source are present (or absent) in the same read, regardless of their values. It is evaluated after transformations, change filters and value filters have run, so a channel removed by its change filter or value filter counts as absent. Channels are named by their ID (the key in the Channels of the source), not by their Name. Reference a condition filter by its ID from a [channel](./channel-configuration.md#conditionfilter).

- [Schema](#schema)
- [Examples](#examples)

**Properties:**

- [Operator](#operator)
- [Value](#value)

  

---
### Operator
Filter operator to apply

**Type**: String, value must be any of these operators:

| Operator | Alias | Value | Passes when |
|---|---|---|---|
| `all` | `##` | channel ID or list of channel IDs | all listed channels are present |
| `any` | `**` | channel ID or list of channel IDs | at least one listed channel is present |
| `none` | `!!` | channel ID or list of channel IDs | none of the listed channels is present |
| `present` | `#` | one channel ID (of a list only the first item is used) | the channel is present |
| `absent` | `!` | one channel ID (of a list only the first item is used) | the channel is absent |
| `only` | `^` | `true` or `false` | `true`: the filtered channel is the only channel left for the source in this read; `false`: it is not |
| `notonly` | `$` | `true` or `false` | `true`: the source has more than one channel left in this read; `false`: exactly one |
| `and` | `&&` | list of conditions | all nested conditions match |
| `or` | `\|\|` | list of conditions | any nested condition matches |


A valid  operator must be specified.

---
### Value
Filter value.

If the operator is "and" ("&&") or "or" ("||") it is a nested list of conditions that all (and) or any (or) must match for the value to pass. Each condition that is part of an "and" or "or" list can have additional nested "and" ("&&") or "or" ("||") operators. Only "and" and "or" evaluate nested conditions; "all", "any" and "none" treat every list item as a channel ID.

Only the top-level Operator is checked at startup. A misspelt operator inside "and"/"or" is ignored, and an "and"/"or" group left empty passes every value.

**Type**: String, String[], Boolean or list of Conditions.

**Note: The operands are the IDs of channels, not the actual values for that channel that have been read from their source. For "only" and "notonly" the operand is true or false.**

Operand used by the filter operator, or a list of nested ConditionConfigurations if the operator is "and" ("&&") or "or" ("||"). If the operand is a channel ID or a list of channel IDs, the ID is the key of the channel in the channels table for a source. Valid JMESPath expressions can be used as well to specify channel IDs to match against.

[^top](#conditionfilterconfiguration)



## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "Operator": {
      "type": "string",
      "description": "The operator to use for the condition",
      "enum": [
        "all","##",
        "any","**",
        "none","!!",
        "present","#",
        "absent","!",
        "only","^",
        "notonly","$",
        "and","&&",
        "or","||"
      ]
    },
    "Value": {
      "description": "A channel ID, a list of channel IDs, a boolean (only, notonly) or nested conditions (and, or)",
      "oneOf": [
        {
          "type": "string",
          "description": "ID of the channel"
        },
        {
          "type": "array",
          "items": {
            "type": "string"
          },
          "description": "List of channel IDs"
        },
        {
          "type": "boolean",
          "description": "Value for the only and notonly operators"
        },
        {
          "$ref": "#",
          "description": "Single nested condition filter"
        },
        {
          "type": "array",
          "items": {
            "$ref": "#"
          },
          "description": "List of nested condition filters"
        }
      ]
    }
  },
  "required": [
    "Operator",
    "Value"
  ],
  "additionalProperties": false
}
```



## Examples



Simple channel condition, include if  "temperature_sensor" channel is present

```json
{
  "Operator": "present",
  "Value": "temperature_sensor"
}
```



All channels condition, include if both "temperature" and "humidity" channels are present

```json
{
  "Operator": "all",
  "Value": ["temperature", "humidity"]
}
```



Nested AND condition, include if  channel "temperature" is present and "humidity" is absent

```json
{
  "Operator": "and",
  "Value": [
    {
      "Operator": "present",
      "Value": "temperature"
    },
    {
      "Operator": "absent",
      "Value": "humidity"
    }
  ]
}
```



Complex AND condition, include if any of "pressure", "temperature" channel  are present  and channel "error_state" is absent

```json
{
  "Operator": "and",
  "Value": [
    {
      "Operator": "any",
      "Value": ["pressure", "temperature"]
    },
    {
      "Operator": "absent",
      "Value": "error_state"
    }
  ]
}
```



Deeply nested conditions:

```json
{
  "Operator": "and",
  "Value": [
    {
      "Operator": "or",
      "Value": [
        {
          "Operator": "present",
          "Value": "sensor1"
        },
        {
          "Operator": "absent",
          "Value": "sensor2"
        }
      ]
    },
    {
      "Operator": "none",
      "Value": "error_flag"
    }
  ]
}
```



Combined conditions

```json
{
  "Operator": "and",
  "Value": [
    {
      "Operator": "present",
      "Value": "temperature"
    },
    {
      "Operator": "and",
      "Value": [
        {
          "Operator": "present",
          "Value": "humidity"
        },
        {
          "Operator": "absent",
          "Value": "fault"
        }
      ]
    }
  ]
}
```



**Runnable example:** [OPC UA to AWS IoT Core using filters](../../examples/opcua-to-iot-using-filters/README.md) (forward tags only when a trigger channel passed its change filter).

[^top](#conditionfilterconfiguration)

